"""One scheduled checkpoint for the staged oversight cutover."""

import base64
import ctypes
import hashlib
import json
import os
import subprocess
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
from pathlib import Path

from driver_core.audit import AuditLog

from .windows_freebuff_dispatch import BURN_SESSIONS, SCM_THREAD, THREAD, VISION_THREAD
from .windows_freebuff_runner import BRANCH, ISSUE, LEDGER, OWNER_ID, UncertainDriverExit, api, execute

CUTOVER = 7093801996
CENSUS = 7093745521
BURNDOWN = 7093818060
AMENDMENT = 7093866656
BURN_QUEUE = 7093946738
UNBLOCK = 7094012443
TRANSITION = 7094050344
FILL = 7094198934
STANDUP = 7111294374
LANE_RESTART = 7100931819
SCM_RESTART = 7097835295
SINCE = "2026-11-23T06:55:00Z"
ROOT = f"{LEDGER}/contents/dispatch/laptop-driver/watch/{CUTOVER}"
WORKTREE = Path(__file__).resolve().parents[1]
RECEIPTS = {
    CUTOVER: "OVERSIGHT CUTOVER - RUNNER IS THE STANDING DISPATCH CHANNEL",
    CENSUS: "OVERSIGHT FOLLOW-UP DISPATCH - T4 ENUMERATION + T5 COMPLETION",
    BURNDOWN: "OVERSIGHT DISPATCH - TONIGHT'S BURNDOWN",
    AMENDMENT: "OVERSIGHT AMENDMENT TO BURNDOWN DISPATCH 7093818060",
    BURN_QUEUE: "OVERSIGHT DISPATCH - BURN QUEUE, NEXT 3 HOURS",
    UNBLOCK: "OVERSIGHT RULING - QUEUE UNBLOCK",
    TRANSITION: "OVERSIGHT DISPATCH - TRANSITION COMPLETION",
    FILL: "OVERSIGHT DISPATCH - MAX-VELOCITY FILL RULE",
    STANDUP: "VISION STANDUP REQUEST 2026-11-23",
    LANE_RESTART: "LANE CONTINUATION WATCH RESTART DISPATCH",
    SCM_RESTART: "LANE CONTINUATION WATCH",
}


def issue_comment(message):
    return api(ISSUE, method="POST", body={"body": message})


def owner(comment):
    return comment.get("user", {}).get("id") == OWNER_ID


def validate_receipts():
    receipts = {}
    for number, heading in RECEIPTS.items():
        receipt = api(f"repos/Treystu/harness/issues/comments/{number}")
        if (not owner(receipt) or not receipt["body"].startswith(heading)
                or not receipt["issue_url"].casefold().endswith("/treystu/harness/issues/684")):
            raise RuntimeError(f"oversight receipt {number} did not match")
        receipts[number] = receipt
    return receipts


def pause_requested():
    page = 1
    while True:
        comments = api(f"{ISSUE}?since={SINCE}&per_page=100&page={page}")
        for comment in comments:
            lines = comment["body"].strip().splitlines()
            if owner(comment) and lines and lines[0].strip() in {"PAUSE", "VISION-DISPATCH PAUSE"}:
                return comment["id"]
        if len(comments) < 100:
            return None
        page += 1


def checkpoints():
    return {entry["name"] for entry in api(f"{ROOT}?ref={BRANCH}")}


def checkpoint(name, event):
    event["at"] = datetime.now(timezone.utc).isoformat()
    content = base64.b64encode((json.dumps(event) + "\n").encode()).decode()
    api(f"{ROOT}/{name}", method="PUT", body={
        "branch": BRANCH, "message": f"Checkpoint vision watch {name}", "content": content,
    })


def read_checkpoint(name):
    response = api(f"{ROOT}/{name}?ref={BRANCH}")
    return json.loads(base64.b64decode(response["content"]))


def guard_approval():
    pause = pause_requested()
    if pause:
        raise RuntimeError(f"oversight PAUSE {pause} revoked pending desktop actions")
    expected = os.environ.get("HARNESS_VISION_HEAD")
    if expected and worktree_head() != expected:
        raise RuntimeError("the published driver changed during the dispatch")


def worktree_head():
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "scripts"],
                      cwd=WORKTREE, timeout=5, check=False).returncode:
        return None
    result = subprocess.run(["git", "rev-parse", "HEAD", "@{upstream}"], cwd=WORKTREE,
                            capture_output=True, text=True, timeout=5, check=False)
    heads = result.stdout.splitlines()
    return heads[0] if result.returncode == 0 and len(heads) == 2 and heads[0] == heads[1] else None


def desktop_idle():
    class LastInput(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    status = LastInput(ctypes.sizeof(LastInput))
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(status)):
        raise RuntimeError("Windows last-input state is unavailable")
    elapsed = (ctypes.windll.kernel32.GetTickCount() - status.dwTime) & 0xffffffff
    return elapsed >= 60_000


def heartbeat(known, state):
    now = datetime.now(timezone.utc)
    bucket = now.strftime("%Y%m%d-%H") + f"-{now.minute // 15}"
    name = f"heartbeat-{bucket}.json"
    if name not in known:
        checkpoint(name, {"state": state})
        issue_comment(f"Vision watch {CUTOVER} heartbeat. {state}.")


def cure_eligible(output, reasons, allowed_actions=()):
    traces = sorted(output.glob("**/driver.jsonl"))
    receipt = output / "runner.jsonl"
    if not traces or not receipt.is_file() or not AuditLog(receipt).verify().ok:
        return False
    if any(not AuditLog(trace).verify().ok for trace in traces):
        return False
    results = [json.loads(line) for line in receipt.read_text(encoding="utf-8").splitlines()]
    if not any(r["step_id"] == "result" and all(reason in r["state"] for reason in reasons)
               for r in results):
        return False
    for trace in traces:
        for line in trace.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row["kind"] != "action":
                continue
            params = row.get("consent", {}).get("params", {})
            if (row.get("action") in {"send_freebuff", "type_freebuff"}
                    or "composer" in params.get("control", "").casefold()
                    or (row.get("ok") and row["step_id"] not in allowed_actions)):
                return False
    return True


def run_burn(receipts, known):
    source = receipts[BURN_QUEUE]
    end = datetime.fromisoformat(source["created_at"]) + timedelta(hours=3)
    if datetime.now(timezone.utc) >= end:
        heartbeat(known, "burn authorization expired; no more restarts")
        return
    digest = hashlib.sha256(source["body"].encode()).hexdigest()
    queue = [(CENSUS, SCM_THREAD), *((BURN_QUEUE if thread == "918dad1a" else BURNDOWN, thread)
                                    for thread in BURN_SESSIONS if thread != "0319b9f6")]
    now = datetime.now(timezone.utc)
    if FILL in receipts:
        hawaii = timezone(timedelta(hours=-10))
        refill = datetime.fromisoformat(receipts[FILL]["created_at"]).astimezone(hawaii)
        midnight = refill.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        if now < midnight:
            queue.append((FILL, "0319b9f6"))
    work = []
    state_dir = Path(os.environ["LOCALAPPDATA"]) / "harness-freebuff-runner"
    for dispatch_id, thread in queue:
        item = f"{dispatch_id}-{thread}"
        if f"claim-{item}.json" not in known:
            work.append((dispatch_id, thread, item))
        else:
            logo = f"{item}-native-logo-cure"
            if f"result-{item}.json" in known and cure_eligible(state_dir / item, ("identify-", "requires 0.90")):
                work.append((dispatch_id, thread, logo))
            if dispatch_id == CENSUS and f"result-{logo}.json" in known and cure_eligible(
                    state_dir / logo, ("did not expose a unique bounded chat list",)):
                work.append((dispatch_id, thread, f"{item}-visual-roster-cure"))
            visual = f"{item}-visual-roster-cure"
            if dispatch_id == CENSUS and f"result-{visual}.json" in known and cure_eligible(
                    state_dir / visual, ("project-census: driver exited unsuccessfully",)):
                work.append((dispatch_id, thread, f"{item}-ocr-line-shape-cure"))
            shaped = f"{item}-ocr-line-shape-cure"
            if dispatch_id == CENSUS and f"result-{shaped}.json" in known and cure_eligible(
                    state_dir / shaped, ("search dialog state is ambiguous",),
                    ("observation-foreground", "census-foreground")):
                work.append((dispatch_id, thread, f"{item}-search-dismiss-cure"))
            if thread in {"7d4a9b14", "918dad1a"} and f"result-{item}.json" in known and cure_eligible(
                    state_dir / item, ("exact OCR label", "was not verified"),
                    ("search-foreground", "close-old-search", "open-session-search",
                     "focus-search-field", "query-session", "observation-foreground", "navigate-to-bystander")):
                work.append((dispatch_id, thread, f"{item}-full-title-cure"))
    for dispatch_id, thread, item in work:
        claim = f"claim-{item}.json"
        if claim in known:
            continue
        guard_approval()
        if not desktop_idle():
            heartbeat(known, "waiting for owner desktop idle")
            return
        # A create-only remote claim is the at-most-once boundary, including crashes.
        authorization = receipts.get(dispatch_id, source)
        claim_digest = hashlib.sha256(authorization["body"].encode()).hexdigest() if dispatch_id != BURNDOWN else digest
        checkpoint(claim, {"dispatch": dispatch_id, "queue": BURN_QUEUE, "thread": thread, "sha256": claim_digest})
        out = state_dir / item
        try:
            out.mkdir(parents=True)
            mission = {"thread": thread, "dispatch": dispatch_id, "standing": True}
            if dispatch_id == CENSUS:
                mission["phases"] = ("project-census",)
                mission["phase_timeout"] = 480
            status = "parked" if execute(out, item, mission, claim_digest, ()) else "verified running"
        except UncertainDriverExit as error:
            checkpoint("desktop-interlock.json", {"dispatch": dispatch_id, "thread": thread, "state": str(error)})
            issue_comment(f"Vision watch desktop interlock #{dispatch_id} / `{thread}`. {error}")
            status = "parked with desktop interlock"
        except (OSError, RuntimeError) as error:
            status = "parked after claim"
            issue_comment(f"Vision watch #{dispatch_id} / `{thread}` {status}. {error}")
        checkpoint(f"result-{item}.json", {"dispatch": dispatch_id, "thread": thread, "state": status})
        return
    heartbeat(known, "no unclaimed burn rows; parked rows stay isolated")


def run_restoration(receipts, known):
    state_dir = Path(os.environ["LOCALAPPDATA"]) / "harness-freebuff-runner"
    for dispatch_id, thread in ((STANDUP, VISION_THREAD), (LANE_RESTART, THREAD), (SCM_RESTART, SCM_THREAD)):
        item = f"restore-{dispatch_id}-{thread}"
        if f"claim-{item}.json" in known:
            if dispatch_id != STANDUP or f"result-{item}.json" not in known or not cure_eligible(
                state_dir / item, ("search: driver tree termination unverified",),
                ("observation-foreground", "navigate-to-bystander", "scroll-project-sidebar",
                 "scroll-sidebar-top", "search-foreground", "close-old-search",
                 "sidebar-top-scroll-1", "sidebar-top-scroll-2", "sidebar-top-scroll-3",
                 "sidebar-top-scroll-4", "sidebar-top-scroll-5", "session-list-pick-1",
                 "prefix-scroll-1"),
            ):
                continue
            item += "-verified-process-stop-cure"
            if f"claim-{item}.json" in known:
                continue
        guard_approval()
        if not desktop_idle():
            heartbeat(known, "waiting for owner desktop idle before restoration")
            return True
        digest = hashlib.sha256(receipts[dispatch_id]["body"].encode()).hexdigest()
        checkpoint(f"claim-{item}.json", {"dispatch": dispatch_id, "thread": thread, "sha256": digest})
        output = state_dir / item
        try:
            output.mkdir(parents=True)
            mission = {"thread": thread, "dispatch": dispatch_id, "standing": True}
            mission["phase_timeout"] = 240
            state = "parked" if execute(output, item, mission, digest, (),) else "verified running"
        except UncertainDriverExit as error:
            checkpoint("desktop-interlock.json", {"dispatch": dispatch_id, "thread": thread, "state": str(error)})
            issue_comment(f"Vision watch desktop interlock #{dispatch_id} / `{thread}`. {error}")
            state = "parked with desktop interlock"
        except (OSError, RuntimeError) as error:
            state = "parked after claim"
            issue_comment(f"Vision watch #{dispatch_id} / `{thread}` {state}. {error}")
        checkpoint(f"result-{item}.json", {"dispatch": dispatch_id, "thread": thread, "state": state})
        return True
    return False


def main():
    head = worktree_head()
    if head is None:
        return
    known = checkpoints()
    if "owner-paused.json" in known:
        return
    if "desktop-interlock.json" in known:
        if "interlock-released-7111294374.json" not in known:
            return
    if "paused.json" in known and read_checkpoint("paused.json")["state"] == "owner-paused":
        return
    pause = pause_requested()
    if pause:
        checkpoint("owner-paused.json", {"dispatch": pause, "state": "owner-paused"})
        issue_comment(f"Vision watch ack {pause}. Paused before desktop input.")
        return
    receipts = validate_receipts()
    if "armed.json" not in known:
        checkpoint("armed.json", {"dispatch": CUTOVER, "state": "staged", "next": CENSUS})
        issue_comment(f"Vision watch ack {CUTOVER}. Scheduled runner staged itself and checkpointed its state. "
                      f"Next admission is {CENSUS}.")
        return
    parked = f"parked-{CENSUS}.json"
    if parked not in known:
        checkpoint(parked, {"dispatch": CENSUS, "state": "parked", "prior": 7093959152, "ruling": UNBLOCK})
        issue_comment(f"Vision watch ack {UNBLOCK} and {TRANSITION}. Item {CENSUS} stays parked alone. "
                      f"Burn queue {BURN_QUEUE} is eligible under its own gates.")
    os.environ["HARNESS_VISION_HEAD"] = head
    if run_restoration(receipts, known):
        return
    run_burn(receipts, known)


if __name__ == "__main__":
    main()
