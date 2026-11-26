"""Claim and file one authenticated, immutable GitHub FreeBuff restart dispatch."""

import argparse
import base64
import hashlib
import io
import json
import os
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
from .windows_focus import activate_exact
from .windows_freebuff_dispatch import (
    CONTINUATION, DISK_THREAD, QUEUE_PLACEHOLDER, QUEUE_REGION, THREAD, Dispatch,
)
from .windows_notepad_window import WindowsWindowScreen

ISSUE = "repos/Treystu/harness/issues/684/comments"
LEDGER = "repos/Treystu/slow-lane-ledger"
BRANCH = "laptop-vision-20261122"
OWNER_ID = 6300031
DEMO_COMMENT = 7091945084
DEMO_SHA256 = "f681100dcf1350fef5f66927912be3b1ad7d61d58a75c12c53ca825086356526"
TRIGGER = re.compile(r"VISION-DISPATCH (dispatch/laptop-driver/inbox/[a-zA-Z0-9_-]+\.json) ([a-f0-9]{40})")
FIELDS = {"action", "thread", "text", "expires_at"}
PHASES = ("search", "query", "select", "prepare", "send")


class UncertainDriverExit(RuntimeError):
    """The driver process tree could not be confirmed stopped."""


def _hidden_subprocess_kwargs():
    """Return Windows CREATE_NO_WINDOW kwargs so background subprocesses never flash a console."""
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


_TRANSIENT_GH_MARKERS = (
    "unexpected end of json input",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
    "timed out",
    "rate limit",
    "connection reset",
    "http 429",
    "http 500",
    "http 502",
    "http 503",
    "http 504",
)


def _is_transient_gh_error(message):
    text = (message or "").casefold()
    return any(marker in text for marker in _TRANSIENT_GH_MARKERS)


def api(endpoint, *, method="GET", body=None, attempts=3):
    args = ["gh", "api", "--method", method, endpoint]
    if body is not None:
        args.extend(("--input", "-"))
    payload = json.dumps(body) if body is not None else None
    delays = (1.5, 3.0)
    last_error = None
    for attempt in range(max(1, attempts)):
        try:
            result = subprocess.run(
                args, input=payload, capture_output=True, text=True, encoding="utf-8",
                timeout=20, check=False, **_hidden_subprocess_kwargs())
        except subprocess.TimeoutExpired as exc:
            last_error = RuntimeError(f"GitHub {method} timed out for {endpoint}: {exc}")
            if attempt + 1 < attempts:
                time.sleep(delays[min(attempt, len(delays) - 1)])
                continue
            raise last_error from exc
        if result.returncode == 0:
            if not (result.stdout or "").strip():
                return {}
            try:
                return json.loads(result.stdout)
            except ValueError as exc:
                last_error = RuntimeError(f"GitHub {method} invalid JSON for {endpoint}: {exc}")
                if attempt + 1 < attempts:
                    time.sleep(delays[min(attempt, len(delays) - 1)])
                    continue
                raise last_error from exc
        err_text = result.stderr.strip()[:220]
        last_error = RuntimeError(f"GitHub {method} failed for {endpoint}: {err_text}")
        if attempt + 1 < attempts and _is_transient_gh_error(err_text):
            time.sleep(delays[min(attempt, len(delays) - 1)])
            continue
        raise last_error
    raise last_error


def approved(comment, now):
    match = TRIGGER.fullmatch((comment.get("body") or "").lstrip("\ufeff").strip())
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


def one_shot_dispatch():
    comment = api(f"repos/Treystu/harness/issues/comments/{DEMO_COMMENT}")
    digest = hashlib.sha256(comment["body"].encode("utf-8")).hexdigest()
    if (comment["id"] != DEMO_COMMENT or comment["user"]["id"] != OWNER_ID
            or comment["issue_url"] != "https://api.github.com/repos/Treystu/harness/issues/684"
            or digest != DEMO_SHA256):
        raise RuntimeError("the one-shot oversight comment failed identity or content verification")
    return {"thread": THREAD, "fallback": DISK_THREAD}, digest


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
    paths = [output / "runner.jsonl", *sorted(output.glob("**/driver.jsonl")),
             *sorted(output.glob("t5-*/observe-running/observed-stop.png")),
             *sorted(output.glob("project-census/project-*.json")),
             *sorted(output.glob("project-census/candidate-*/visual-census-*-open.png")),
             *sorted(output.glob("before-*.png")), *sorted(output.glob("after-*.png"))]
    links = []
    for path in paths:
        if not path.is_file():
            continue
        parts = path.relative_to(output).parts
        name = "-".join(parts[:-1]) + ".jsonl" if path.name == "driver.jsonl" else "-".join(parts)
        destination = f"dispatch/laptop-driver/evidence/t8/{number}/{name}"
        receipt = api(f"{LEDGER}/contents/{destination}", method="PUT", body={
            "branch": BRANCH, "message": f"File T8 trace {number} {name}",
            "content": base64.b64encode(path.read_bytes()).decode("ascii"),
        })
        links.append(receipt["content"]["html_url"])
    return links


def same_pixels(before, after):
    from PIL import Image, ImageChops

    with Image.open(before) as first, Image.open(after) as second:
        return first.size == second.size and not ImageChops.difference(
            first.convert("RGB"), second.convert("RGB")).getbbox()


def reconcile_demo(output):
    """File a read-only verdict for the original demo after its state classifier timed out."""
    from PIL import Image, ImageOps

    runner = output / "runner.jsonl"
    send = output / "send" / "driver.jsonl"
    for trace in (runner, send):
        if not trace.is_file() or not AuditLog(trace).verify().ok:
            raise RuntimeError("the original hash-chained demo traces are required")
    records = [json.loads(line) for line in send.read_text(encoding="utf-8").splitlines()]
    sends = [r for r in records if r["step_id"] == "send-once"]
    if (len(sends) != 1 or not sends[0]["ok"]
            or sends[0]["consent"]["params"]["thread"] != THREAD
            or sends[0]["consent"]["params"]["text"] != CONTINUATION
            or not any(r.get("exact_label") == CONTINUATION and r["seq"] < sends[0]["seq"]
                       for r in records)):
        raise RuntimeError("the trace did not bind one successful send to the exact OCR draft")
    captures = [row for line in runner.read_text(encoding="utf-8").splitlines()
                if (row := json.loads(line))["kind"] == "capture"]
    if {(row["step_id"], row["target"]) for row in captures} != {
        (phase, target) for phase in ("before", "after")
        for target in ("freebuff", "bystander-1", "bystander-2")
    }:
        raise RuntimeError("the original capture inventory is incomplete")
    for row in captures:
        png = output / f"{row['step_id']}-{row['target']}.png"
        if hashlib.sha256(png.read_bytes()).hexdigest() != row["sha256"]:
            raise RuntimeError(f"capture changed after recording: {png.name}")
    if not all(same_pixels(output / f"before-bystander-{n}.png",
                           output / f"after-bystander-{n}.png") for n in (1, 2)):
        raise RuntimeError("the archived bystander pixels differ")
    with Image.open(output / "before-freebuff.png") as before, Image.open(output / "after-freebuff.png") as after:
        if Dispatch.stop_visible(before) or not Dispatch.stop_visible(after):
            raise RuntimeError("the captured target Stop cue did not change from idle to running")
        crop = after.crop(QUEUE_REGION)
        png = output / "reconciled-queue-ocr.png"
        ImageOps.invert(ImageOps.grayscale(crop.resize((crop.width * 3, crop.height * 3)))).save(png)
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-File",
         str(Path(__file__).with_name("windows_ocr_exact.ps1")), "-Path", str(png), "-Label", QUEUE_PLACEHOLDER],
        check=True, timeout=10, capture_output=True, **_hidden_subprocess_kwargs())
    receipt = api(ISSUE, method="POST", body={"body": (
        f"T8 reconciled #{DEMO_COMMENT}: one exact OCR-verified send to `{THREAD}`. "
        "Archived PNG hashes match the sealed trace. Stop changed false→true, exact queue placeholder verified, "
        "and both bystander RGB comparisons are identical. Read-only reconciliation. "
        f"[Original runner trace](https://github.com/Treystu/slow-lane-ledger/blob/{BRANCH}/"
        f"dispatch/laptop-driver/evidence/t8/{output.name}/runner.jsonl).")})
    print(receipt["html_url"])
    return 0


def _platform_state_lines(stdout):
    return [line.strip() for line in (stdout or "").splitlines() if line.strip().startswith("Platform state:")]


def run_phases(output, thread, audit, phases=PHASES, *, standing=False, timeout=65):
    for phase in phases:
        helper = Path(__file__).with_name("windows_freebuff_runner_action.ps1")
        command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-File",
                   str(helper), "-Python", sys.executable, "-Thread", thread, "-Phase", phase,
                   "-Evidence", str(output / phase), *(["-Standing"] if standing else [])]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   **_hidden_subprocess_kwargs())
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as cause:
            try:
                ended = subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                                       capture_output=True, timeout=10, check=False,
                                       **_hidden_subprocess_kwargs())
                if ended.returncode:
                    raise UncertainDriverExit(f"{phase}: driver tree termination unverified") from cause
                process.communicate(timeout=10)
            except (OSError, subprocess.TimeoutExpired) as error:
                raise UncertainDriverExit(f"{phase}: driver tree termination unverified") from error
            raise RuntimeError(f"{phase}: driver tree terminated after deadline") from cause
        platform_states = _platform_state_lines(stdout)
        refused = [line for line in platform_states if line.lower().startswith("platform state: refused")]
        if refused:
            audit.append("escalation", step_id=phase, target=thread, state=refused[-1])
            raise RuntimeError(f"{phase}: {refused[-1]}")
        resumed = [line for line in platform_states if "resumed-and-running" in line]
        if resumed and not process.returncode:
            # R7: the expired session's own staged mission was resumed and
            # started, so the continuation must NOT be sent over it.
            audit.append("verification", step_id="resumed-without-send", target=thread,
                         state=resumed[-1])
            time.sleep(2)
            return True
        if process.returncode:
            detail = stdout.strip().splitlines()
            if phase in {"prepare", "vision-resume"} and detail and "already running; no restart input" in detail[-1]:
                audit.append("verification", step_id=phase, target=thread, state="already running")
                return False
            errors = stderr.strip().splitlines()
            message = detail[-1] if detail else errors[-1][:200] if errors else "driver exited unsuccessfully"
            raise RuntimeError(f"{phase}: {message}")
        audit.append("verification", step_id=phase, target=thread, passed=True,
                     platform_state=platform_states[-1] if platform_states else None)
        time.sleep(2)
    return True


BYSTANDER_IDLE = "no live turn"


def bystander_needs_pair(value):
    """Only a live observation is paired; an idle or failed one is not."""
    return value is True


def observe_bystander(output, audit, phase):
    """Observe the separate lane, telling an idle lane apart from a failed read.

    Measured 2026-11-24 on dispatch 7125497229 (an SCMessenger boundary restart):
    the precheck demanded Lane 1's Stop square and refused with "the separate
    Lane 1 Stop square is absent" thirteen times running, so the dispatch never
    reached its own phases. Lane 1 was idle, which is why the square could not be
    there - and an idle lane has no live turn for this dispatch to disturb, so
    the observation it guards is not applicable rather than failed. Any other
    failure still parks: a lane that will not render is not evidence of safety.
    """
    folder = output / f"t5-{phase}"
    folder.mkdir()
    try:
        # A bystander observation is evidence, not the dispatch's own gate: it
        # gets a short budget so an idle or unreadable lane cannot eat the run.
        # Measured on 7125647656: the probe alone exceeded its deadline and every
        # retry paid it again before the dispatch's own phases began.
        run_phases(folder, THREAD, audit, ("observe-running",), standing=True, timeout=20)
        return True
    except UncertainDriverExit:
        raise
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        if "Stop square is absent" in str(error):
            audit.append("verification", step_id=f"t5-{phase}-idle", target=THREAD,
                         state=BYSTANDER_IDLE, detail=str(error))
            return BYSTANDER_IDLE
        audit.append("escalation", step_id=f"t5-{phase}", reason=str(error), target=THREAD)
        return False


def _utc_iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pickup_latency_note(filed_at, claimed_at, completed_at):
    filed = str(filed_at or "").strip()
    pickup = ""
    if filed:
        try:
            fdt = datetime.fromisoformat(filed.replace("Z", "+00:00"))
            cdt = datetime.fromisoformat(claimed_at.replace("Z", "+00:00"))
            pickup = f", pickup {max(0.0, (cdt - fdt).total_seconds()):.1f}s"
        except ValueError:
            pickup = ""
    return f" Timestamps: filed {filed or 'unknown'}, claimed {claimed_at}, completed {completed_at}{pickup}."


def execute(output, number, mission, digest, bystanders):
    audit = AuditLog(output / "runner.jsonl")
    claimed_at = _utc_iso_now()
    filed_at = str(mission.get("filed_at") or "").strip()
    audit.append("decision", step_id="claim", comment=number, thread=mission["thread"],
                 blob=digest, filed_at=filed_at or None, claimed_at=claimed_at)
    dispatch_id = mission.get("dispatch", number)
    ack_timing = f" (filed {filed_at}, claimed {claimed_at})" if filed_at else f" (claimed {claimed_at})"
    if not mission.get("skip_pre_ack"):
        api(ISSUE, method="POST", body={"body": f"Vision restart ack #{dispatch_id}: `{mission['thread']}`, receipt {number}{ack_timing}."})
    state = "verified running"
    windows = []
    before = {}
    foreground = None
    prior = None
    uncertain = None
    try:
        freebuff = FreeBuffWindow()
        if mission.get("standing"):
            foreground = freebuff.api.foreground()
            if not foreground:
                raise RuntimeError("the original foreground window could not be identified")
            prior = (freebuff.pid(foreground), freebuff.api.title_of(foreground))
        windows = [("freebuff", freebuff)]
        windows.extend((f"bystander-{index}", Bystander(title, freebuff))
                       for index, title in enumerate(bystanders, start=1))
        before = capture_set(output, "before", windows, audit)
        phases = mission.get("phases", ("prepare", "send") if mission.get("resume_inside") else PHASES)
        t5_before = False
        if mission.get("standing") and not mission.get("skip_t5") and mission["thread"] != THREAD:
            # Never a gate: this dispatch does not touch that lane, and the
            # before/after pixel comparison still records whether it moved.
            t5_before = observe_bystander(output, audit, "before")
        if not run_phases(output, mission["thread"], audit, phases, standing=mission.get("standing", False),
                          timeout=mission.get("phase_timeout", 65)):
            fallback = mission.get("fallback")
            if not fallback:
                # The child proved the session's identity and then found its turn
                # already running, so no input was sent: that is a standup, not a park.
                state = "verified running: the session was already in a turn; no input sent"
                audit.append("verification", step_id="already-running", target=mission["thread"],
                             passed=True)
            else:
                folder = output / "disk-fallback"
                folder.mkdir()
                if not run_phases(folder, fallback, audit):
                    raise RuntimeError("both authorized sessions are already running")
        if bystander_needs_pair(t5_before):
            paired = observe_bystander(output, audit, "after")
            audit.append("verification", step_id="t5-pair", target=THREAD, passed=paired)
    except UncertainDriverExit as error:
        uncertain = error
        state = f"parked: {error}"
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        state = f"parked: {error}"
    finally:
        if (not uncertain and prior and freebuff.api.foreground() == freebuff.handle
                and foreground != freebuff.handle):
            try:
                pid, title = prior
                if (freebuff.pid(foreground) != pid or freebuff.api.title_of(foreground) != title
                        or not activate_exact(foreground, freebuff.api.foreground)
                        or freebuff.api.foreground() != foreground):
                    raise RuntimeError("the exact original foreground could not be restored")
                audit.append("verification", step_id="foreground-restored", hwnd=foreground, pid=pid)
            except (OSError, RuntimeError) as error:
                audit.append("escalation", step_id="foreground-restore", reason=str(error))
                if state == "verified running":
                    state = f"parked after verified send: {error}"
        if windows:
            try:
                after = capture_set(output, "after", windows, audit)
                for label in before.keys() & after.keys():
                    if label != "freebuff":
                        audit.append("verification", step_id="bystander-comparison",
                                     target=label, same_pixels=same_pixels(
                                         output / f"before-{label}.png", output / f"after-{label}.png"))
            except (OSError, RuntimeError) as error:
                audit.append("escalation", step_id="after", reason=str(error))
        if (output / "foreign-staged-send-only.json").is_file() and state == "verified running":
            state = "verified running (send-only; foreign staged draft preserved)"
        audit.append("verification", step_id="result", state=state)
        note = ""
        try:
            links = publish(output, number)
        except (RuntimeError, OSError) as error:
            # An evidence-upload failure must never silence the verdict.
            audit.append("escalation", step_id="publish", reason=str(error))
            links = []
            note = f" Evidence upload failed: {error}"
        completed_at = _utc_iso_now()
        latency_note = _pickup_latency_note(filed_at, claimed_at, completed_at)
        prefix = (
            f"Vision standing restart log (Rule 7183684276) / `{mission['thread']}`: {state}."
            if mission.get("skip_pre_ack")
            else f"Vision restart result #{dispatch_id} / `{mission['thread']}`: {state}."
        )
        api(ISSUE, method="POST", body={"body": (
            f"{prefix} Evidence: "
            + " ".join(f"[{index}]({url})" for index, url in enumerate(links, start=1)) + note + latency_note)})
    print(state)
    if uncertain:
        raise uncertain
    return int(not state.startswith("verified running"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--since", help="UTC GitHub comment timestamp to watch from")
    source.add_argument("--oversight-demo", action="store_true", help="execute comment 7091945084 once")
    source.add_argument("--reconcile-demo", action="store_true", help="verify recorded evidence with no desktop input")
    source.add_argument("--resume-before-input", action="store_true",
                        help="resume the one-shot demo after a verified pre-input refusal")
    source.add_argument("--resume-selection-cure", action="store_true",
                        help="resume the one-shot demo after the recorded selection refusal")
    source.add_argument("--resume-highlight-cure", action="store_true",
                        help="resume after the recorded inside-view refusal")
    source.add_argument("--resume-cache-cure", action="store_true",
                        help="resume after the recorded recent-cache refusal")
    source.add_argument("--resume-placeholder-cure", action="store_true",
                        help="resume after the plain empty composer was not classified")
    source.add_argument("--resume-keyboard-cure", action="store_true",
                        help="resume after the scoped composer rejected character input")
    parser.add_argument("--wait", type=int, default=120)
    parser.add_argument("--bystander-title", action="append", default=[])
    args = parser.parse_args()
    if args.reconcile_demo:
        return reconcile_demo(args.state / f"{DEMO_COMMENT}-keyboard-cure")
    args.state.mkdir(parents=True, exist_ok=True)
    if (args.oversight_demo or args.resume_before_input or args.resume_selection_cure
            or args.resume_highlight_cure or args.resume_cache_cure or args.resume_placeholder_cure
            or args.resume_keyboard_cure):
        mission, digest = one_shot_dispatch()
        execution = args.state / str(DEMO_COMMENT)
        if (args.resume_highlight_cure or args.resume_cache_cure or args.resume_placeholder_cure
                or args.resume_keyboard_cure):
            if args.resume_keyboard_cure:
                previous_stage, current_stage = "placeholder-cure", "keyboard-cure"
                reason = "read-exact-draft-retry: exact OCR label"
            elif args.resume_placeholder_cure:
                previous_stage, current_stage = "cache-cure", "placeholder-cure"
                reason = "composer-route: Jev choice 'stop' confidence was 0.63"
            elif args.resume_cache_cure:
                previous_stage, current_stage = "highlight-cure", "cache-cure"
                reason = "Lane 1 UUID absent from recent FreeBuff local state"
            else:
                previous_stage, current_stage = "selection-cure", "highlight-cure"
                reason = "verify-lane1: Jev target confidence was 0.34"
            previous = args.state / f"{DEMO_COMMENT}-{previous_stage}"
            prepared = previous / "prepare" / "driver.jsonl"
            if ((previous / "send").exists() or not prepared.is_file()
                    or not AuditLog(prepared).verify().ok
                    or reason not in prepared.read_text(encoding="utf-8")):
                parser.error("no verified inside-view refusal to resume")
            actions = [record["step_id"] for line in prepared.read_text(encoding="utf-8").splitlines()
                       if (record := json.loads(line))["kind"] == "action"]
            expected = ["focus-verified-composer", "type-continuation"] if args.resume_keyboard_cure else []
            if actions != expected:
                parser.error("unexpected actions in the previous attempt")
            execution = args.state / f"{DEMO_COMMENT}-{current_stage}"
            try:
                execution.mkdir()
            except FileExistsError:
                parser.error("this highlight cure was already claimed")
            mission["resume_inside"] = True
            return execute(execution, f"{DEMO_COMMENT}-{current_stage}", mission, digest,
                           args.bystander_title)
        if args.resume_selection_cure:
            previous = args.state / f"{DEMO_COMMENT}-pre-input-retry"
            traces = sorted(previous.glob("**/driver.jsonl"))
            runner_trace = previous / "runner.jsonl"
            if (not runner_trace.is_file() or not AuditLog(runner_trace).verify().ok
                    or {trace.parent.name for trace in traces} != {"search", "query", "select"}
                    or any(not AuditLog(trace).verify().ok for trace in traces)
                    or any(json.loads(line)["kind"] == "action" for trace in traces
                           if trace.parent.name == "select"
                           for line in trace.read_text(encoding="utf-8").splitlines())
                    or "verify-existing-search-result: Jev target confidence was 0.88"
                    not in runner_trace.read_text(encoding="utf-8")):
                parser.error("no verified selection refusal to resume")
            execution = args.state / f"{DEMO_COMMENT}-selection-cure"
            try:
                execution.mkdir()
            except FileExistsError:
                parser.error("this selection cure was already claimed")
            return execute(execution, f"{DEMO_COMMENT}-selection-cure", mission, digest, args.bystander_title)
        if args.resume_before_input:
            traces = sorted(execution.glob("**/driver.jsonl"))
            if (len(traces) != 1 or traces[0].parent.name != "search"
                    or not AuditLog(traces[0]).verify().ok
                    or any(json.loads(line)["kind"] == "action"
                           for line in traces[0].read_text(encoding="utf-8").splitlines())):
                parser.error("no verified pre-input refusal to resume")
            execution = args.state / f"{DEMO_COMMENT}-pre-input-retry"
            try:
                execution.mkdir()
            except FileExistsError:
                parser.error("the bounded pre-input retry was already claimed")
            return execute(execution, f"{DEMO_COMMENT}-retry", mission, digest, args.bystander_title)
        try:
            (args.state / f"blob-{digest}").mkdir()
            execution.mkdir()
        except FileExistsError:
            parser.error("this oversight demo was already claimed")
        return execute(execution, DEMO_COMMENT, mission, digest, args.bystander_title)
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
