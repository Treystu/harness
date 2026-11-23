"""One scheduled checkpoint for the staged oversight cutover."""

import base64
import json
from datetime import datetime, timezone

from .windows_freebuff_runner import BRANCH, ISSUE, LEDGER, OWNER_ID, api

CUTOVER = 7093801996
CENSUS = 7093745521
BURNDOWN = 7093818060
AMENDMENT = 7093866656
SINCE = "2026-11-23T06:55:00Z"
ROOT = f"{LEDGER}/contents/dispatch/laptop-driver/watch/{CUTOVER}"
RECEIPTS = {
    CUTOVER: "OVERSIGHT CUTOVER - RUNNER IS THE STANDING DISPATCH CHANNEL",
    CENSUS: "OVERSIGHT FOLLOW-UP DISPATCH - T4 ENUMERATION + T5 COMPLETION",
    BURNDOWN: "OVERSIGHT DISPATCH - TONIGHT'S BURNDOWN",
    AMENDMENT: "OVERSIGHT AMENDMENT TO BURNDOWN DISPATCH 7093818060",
}


def issue_comment(message):
    return api(ISSUE, method="POST", body={"body": message})


def owner(comment):
    return comment.get("user", {}).get("id") == OWNER_ID


def validate_receipts():
    for number, heading in RECEIPTS.items():
        receipt = api(f"repos/Treystu/harness/issues/comments/{number}")
        if (not owner(receipt) or not receipt["body"].startswith(heading)
                or not receipt["issue_url"].casefold().endswith("/treystu/harness/issues/684")):
            raise RuntimeError(f"oversight receipt {number} did not match")


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


def main():
    known = checkpoints()
    if "paused.json" in known:
        return
    pause = pause_requested()
    if pause:
        checkpoint("paused.json", {"dispatch": pause, "state": "owner-paused"})
        issue_comment(f"Vision watch ack {pause}. Paused before desktop input.")
        return
    validate_receipts()
    if "armed.json" not in known:
        checkpoint("armed.json", {"dispatch": CUTOVER, "state": "staged", "next": CENSUS})
        issue_comment(f"Vision watch ack {CUTOVER}. Scheduled runner staged itself and checkpointed its state. "
                      f"Next admission is {CENSUS}.")
        return
    # No restart adapter may run before the census has a clean filed verdict.
    # An incomplete adapter must stop the watch without spending a dispatch.
    checkpoint("paused.json", {"dispatch": CENSUS, "state": "adapter-unavailable", "executed": []})
    issue_comment(f"Vision watch {CENSUS} self-pause. Full project chat enumeration and separate running-lane "
                  f"capture adapters are unavailable. No desktop input or dispatch execution. "
                  f"{BURNDOWN} (amended by {AMENDMENT}) remains queued.")


if __name__ == "__main__":
    main()
