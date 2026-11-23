"""One scheduled checkpoint for the staged oversight cutover."""

import base64
import ctypes
import hashlib
import json
import os
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .windows_freebuff_dispatch import BURN_SESSIONS
from .windows_freebuff_runner import BRANCH, ISSUE, LEDGER, OWNER_ID, api, execute

CUTOVER = 7093801996
CENSUS = 7093745521
BURNDOWN = 7093818060
AMENDMENT = 7093866656
BURN_QUEUE = 7093946738
UNBLOCK = 7094012443
TRANSITION = 7094050344
SINCE = "2026-11-23T06:55:00Z"
ROOT = f"{LEDGER}/contents/dispatch/laptop-driver/watch/{CUTOVER}"
RECEIPTS = {
    CUTOVER: "OVERSIGHT CUTOVER - RUNNER IS THE STANDING DISPATCH CHANNEL",
    CENSUS: "OVERSIGHT FOLLOW-UP DISPATCH - T4 ENUMERATION + T5 COMPLETION",
    BURNDOWN: "OVERSIGHT DISPATCH - TONIGHT'S BURNDOWN",
    AMENDMENT: "OVERSIGHT AMENDMENT TO BURNDOWN DISPATCH 7093818060",
    BURN_QUEUE: "OVERSIGHT DISPATCH - BURN QUEUE, NEXT 3 HOURS",
    UNBLOCK: "OVERSIGHT RULING - QUEUE UNBLOCK",
    TRANSITION: "OVERSIGHT DISPATCH - TRANSITION COMPLETION",
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


def run_burn(receipts, known):
    source = receipts[BURN_QUEUE]
    end = datetime.fromisoformat(source["created_at"]) + timedelta(hours=3)
    if datetime.now(timezone.utc) >= end:
        heartbeat(known, "burn authorization expired; no more restarts")
        return
    digest = hashlib.sha256(source["body"].encode()).hexdigest()
    for thread in BURN_SESSIONS:
        dispatch_id = BURN_QUEUE if thread == "918dad1a" else BURNDOWN
        item = f"{dispatch_id}-{thread}"
        claim = f"claim-{item}.json"
        if claim in known:
            continue
        guard_approval()
        if not desktop_idle():
            heartbeat(known, "waiting for owner desktop idle")
            return
        # A create-only remote claim is the at-most-once boundary, including crashes.
        checkpoint(claim, {"dispatch": dispatch_id, "queue": BURN_QUEUE, "thread": thread, "sha256": digest})
        out = Path(os.environ["LOCALAPPDATA"]) / "harness-freebuff-runner" / item
        try:
            out.mkdir(parents=True)
            mission = {"thread": thread, "dispatch": dispatch_id, "standing": True}
            status = "parked" if execute(out, item, mission, digest, ()) else "verified running"
        except (OSError, RuntimeError) as error:
            status = "parked after claim"
            issue_comment(f"Vision watch #{dispatch_id} / `{thread}` {status}. {error}")
        checkpoint(f"result-{item}.json", {"dispatch": dispatch_id, "thread": thread, "state": status})
        return
    heartbeat(known, "no unclaimed burn rows; parked rows stay isolated")


def main():
    known = checkpoints()
    if "owner-paused.json" in known:
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
    run_burn(receipts, known)


if __name__ == "__main__":
    main()
