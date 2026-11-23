"""Claim and file one authenticated, immutable GitHub FreeBuff restart dispatch."""

import argparse
import base64
import hashlib
import io
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from driver_core.audit import AuditLog
from driver_core.observation import GUI, Target
from driver_core.osal import _WindowsWindowApi

from .windows_freebuff_capture import FreeBuffWindow
from .windows_freebuff_dispatch import CONTINUATION, DISK_THREAD, THREAD, Dispatch
from .windows_notepad_window import WindowsWindowScreen

ISSUE = "repos/Treystu/harness/issues/684/comments"
LEDGER = "repos/Treystu/slow-lane-ledger"
BRANCH = "laptop-vision-20261122"
OWNER_ID = 6300031
TRIGGER = re.compile(r"VISION-DISPATCH (dispatch/laptop-driver/inbox/[a-zA-Z0-9_-]+\.json) ([a-f0-9]{40})")
FIELDS = {"action", "thread", "text", "expires_at"}
PHASES = ("search", "query", "select", "prepare", "send")


def api(endpoint, *, method="GET", body=None):
    args = ["gh", "api", "--method", method, endpoint]
    if body is not None:
        args.extend(("--input", "-"))
    result = subprocess.run(args, input=json.dumps(body) if body is not None else None,
                            capture_output=True, text=True, timeout=20, check=False)
    if result.returncode:
        raise RuntimeError(f"GitHub {method} failed for {endpoint}: {result.stderr.strip()[:220]}")
    return json.loads(result.stdout)


def approved(comment, now):
    match = TRIGGER.fullmatch((comment.get("body") or "").strip())
    if comment.get("user", {}).get("id") != OWNER_ID or not match:
        return None
    path, digest = match.groups()
    blob = api(f"{LEDGER}/contents/{path}?ref=main")
    if blob.get("sha") != digest or blob.get("size", 0) > 2048:
        raise RuntimeError("the pinned private ledger blob did not match")
    raw = base64.b64decode(blob["content"])
    git_data = f"blob {len(raw)}\0".encode("ascii") + raw
    if hashlib.sha1(git_data, usedforsecurity=False).hexdigest() != digest:
        raise RuntimeError("the decoded mission bytes did not match the pinned blob")
    mission = json.loads(raw)
    if (not isinstance(mission, dict) or mission.keys() != FIELDS
            or mission["action"] != "restart-existing"
            or mission["thread"] not in (THREAD, DISK_THREAD)
            or mission["text"] != CONTINUATION):
        raise RuntimeError("dispatch is outside the exact restart vocabulary")
    expiry = datetime.fromisoformat(mission["expires_at"])
    if expiry.tzinfo is None or expiry <= now:
        raise RuntimeError("dispatch expiry is missing or has passed")
    return mission, digest


class Bystander:
    def __init__(self, title, freebuff):
        self.api = _WindowsWindowApi()
        matches = self.api.find_exact_visible(title)
        if len(matches) != 1 or matches[0] == freebuff.handle:
            raise RuntimeError("bystander title did not resolve to one distinct visible window")
        self.hwnd = matches[0]
        self.title = title
        self.pid = freebuff.pid
        self.process = self.pid(self.hwnd)

    def require_window(self):
        if self.pid(self.hwnd) != self.process or self.api.title_of(self.hwnd) != self.title:
            raise RuntimeError("bystander window identity changed")
        return self.hwnd


def capture_set(output, phase, windows, audit):
    from PIL import Image

    hashes = {}
    for label, window in windows:
        capture = WindowsWindowScreen(window, source=label).capture(Target(label, GUI))
        (output / f"{phase}-{label}.png").write_bytes(capture.payload)
        hashes[label] = hashlib.sha256(capture.payload).hexdigest()
        image = Image.open(io.BytesIO(capture.payload))
        stop_cue = Dispatch.stop_visible(image) if label == "freebuff" and image.size == (1800, 1131) else None
        audit.append("capture", step_id=phase, target=label,
                     sha256=hashes[label], stop_cue=stop_cue)
    return hashes


def publish(output, number):
    paths = [output / "runner.jsonl", *(output / phase / "driver.jsonl" for phase in PHASES)]
    links = []
    for path in paths:
        if not path.is_file():
            continue
        name = "runner.jsonl" if path.parent == output else f"{path.parent.name}.jsonl"
        destination = f"dispatch/laptop-driver/evidence/t8/{number}/{name}"
        receipt = api(f"{LEDGER}/contents/{destination}", method="PUT", body={
            "branch": BRANCH, "message": f"File T8 trace {number} {name}",
            "content": base64.b64encode(path.read_bytes()).decode("ascii"),
        })
        links.append(receipt["content"]["html_url"])
    return links


def execute(output, number, mission, digest, bystanders):
    audit = AuditLog(output / "runner.jsonl")
    audit.append("decision", step_id="claim", comment=number, thread=mission["thread"], blob=digest)
    api(ISSUE, method="POST", body={"body": f"T8 ack #{number}: claimed the pinned restart for `{mission['thread']}`."})
    state = "started"
    windows = []
    before = {}
    try:
        freebuff = FreeBuffWindow()
        windows = [("freebuff", freebuff)]
        windows.extend((f"bystander-{index}", Bystander(title, freebuff))
                       for index, title in enumerate(bystanders, start=1))
        before = capture_set(output, "before", windows, audit)
        for phase in PHASES:
            helper = Path(__file__).with_name("windows_freebuff_runner_action.ps1")
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(helper),
                 "-Python", sys.executable, "-Thread", mission["thread"],
                 "-Phase", phase, "-Evidence", str(output / phase)],
                capture_output=True, text=True, timeout=65, check=False)
            if result.returncode:
                detail = result.stdout.strip().splitlines()
                raise RuntimeError(f"{phase}: {detail[-1] if detail else 'driver exited unsuccessfully'}")
            audit.append("verification", step_id=phase, passed=True)
            time.sleep(2)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        state = f"parked: {error}"
    finally:
        if windows:
            try:
                after = capture_set(output, "after", windows, audit)
                for label in before.keys() & after.keys():
                    if label != "freebuff":
                        audit.append("verification", step_id="bystander-comparison",
                                     target=label, same_pixels=before[label] == after[label])
            except (OSError, RuntimeError) as error:
                audit.append("escalation", step_id="after", reason=str(error))
        audit.append("verification", step_id="result", state=state)
        links = publish(output, number)
        api(ISSUE, method="POST", body={"body": (
            f"T8 result #{number}: {state}. PNGs retained locally; trace links: "
            + " ".join(f"[{index}]({url})" for index, url in enumerate(links, start=1)))})
    print(state)
    return int(state != "started")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--since", required=True, help="UTC GitHub comment timestamp to watch from")
    parser.add_argument("--wait", type=int, default=120)
    parser.add_argument("--bystander-title", action="append", default=[])
    args = parser.parse_args()
    args.state.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + args.wait
    seen = set()
    while True:
        for comment in api(f"{ISSUE}?since={args.since}&per_page=100"):
            number = comment["id"]
            execution = args.state / str(number)
            if number in seen or execution.exists():
                continue
            seen.add(number)
            try:
                result = approved(comment, datetime.now(timezone.utc))
            except (RuntimeError, KeyError, ValueError, TypeError) as error:
                api(ISSUE, method="POST", body={"body": f"T8 refused #{number}: {error}"})
                continue
            if result is None:
                continue
            mission, digest = result
            try:
                (args.state / f"blob-{digest}").mkdir()
                execution.mkdir()
            except FileExistsError:
                continue
            return execute(execution, number, mission, digest, args.bystander_title)
        if time.monotonic() >= deadline:
            print("No approved dispatch in the watch window.")
            return 0
        time.sleep(min(12, max(0, deadline - time.monotonic())))


if __name__ == "__main__":
    raise SystemExit(main())
