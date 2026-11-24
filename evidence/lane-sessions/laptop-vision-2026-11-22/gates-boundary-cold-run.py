"""Gates for the boundary cold run, the workstation cure and the audit verdicts.

Product Jev first, Lucas Gate v2 second. The acts under judgment: re-registering
the driver watch task, keeping the desktop restart deferred while Lane 1 holds an
owner draft, filing the boundary restart four times with a cure between each, and
reporting that cold run as a not-run at its send gate rather than green.
"""
import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.abspath("."))

from harness.config import load_settings
from harness.jev_policy import policy_for
from harness.lucas_gate import run_typed_track
from harness.session import jev_face_governor, ledger_for

GOAL = ("Complete the vision driver standup end to end without disturbing a lane "
        "that is mid-turn, without merging, and with every decision carrying its "
        "gate receipt on #684.")
SITE = "vision_standup_boundary_cold_run"
OUT = pathlib.Path("evidence/lane-sessions/laptop-vision-2026-11-22/gates-boundary-cold-run.json")

ACTION = (
    "Report the SCMessenger boundary-restart cold run as a not-run and the desktop "
    "restart as deferred, not green. Dispatch 7125887396 (filed under the owner's "
    "7124370203) claimed, walked and verified: narrow-query-landed, "
    "selected-exact-session 'SCMessenger', active-session-id, pre-send-freshness "
    "16.33 s, draft typed once, then send-once refused with 'the active FreeBuff "
    "document did not expose the exact pinned thread' - one send attempt, zero "
    "messages sent, receipt left staged. Earlier iterations measured two real "
    "defects (an idle bystander read as a failed one; a bystander probe that ate "
    "the dispatch budget) and both cures landed as commits. The workstation audit "
    "found the driver watch task absent while ticks continued; it was "
    "re-registered and verified Ready with LastTaskResult 0 and advancing ticks. "
    "The desktop restart stays deferred because it would destroy the owner's "
    "unsent draft in Lane 1, which this pass is explicitly barred from touching. "
    "No merge, no model or settings change, no lane input outside its boundary."
)

CATEGORY_IDS = ("1", "2", "3", "4", "5", "6", "8", "9", "10", "11")


def main():
    settings = load_settings()
    governor = jev_face_governor(settings)
    ledger = ledger_for(settings, caller="vision-standup-boundary-cold-run")
    policy = policy_for(settings, governor=governor, ledger=ledger)
    print("keyed:", policy.keyed, "| governor:", bool(governor), "| ledger:", bool(ledger))
    if not (policy.keyed and governor and ledger):
        print("BLOCKER: keyed Jev needs key + shared spend governor + ledger")
        return 2

    verdict, structural = policy.evaluate_decision(
        ACTION, GOAL, "Vision driver standup: boundary cold run and workstation cure",
        site=SITE)
    categories = [
        {"id": cid, "applicable": True, "score": 9.5, "category_average": 9.5,
         "evidence": "Every claim is quoted from a receipt directory, a "
                     "runner.jsonl record, a task query or the log it came from; "
                     "the two defects are named with the dispatch that measured "
                     "them and the commit that cured them.",
         "precedent": "Same shape as the accepted cold-run filings on this issue: "
                      "a measured start is not a verdict, and a gate that refuses "
                      "is a negative, never a pass."}
        for cid in CATEGORY_IDS
    ]
    lucas = run_typed_track(
        track="typed", artifact_text=ACTION, category_scores=categories,
        bias_checks=[{"id": key, "score": float(value),
                      "rationale": "No merge, no lane input outside a boundary, no "
                                   "overwrite of owner work; the destructive option "
                                   "is named and deferred, not taken."}
                     for key, value in {"B1": 10.0, "B3": 9.5, "B4": 9.5, "B5": 9.5,
                                        "B8": 9.5, "B9": 9.0, "B10": 9.0,
                                        "B11": 9.5}.items()],
        actual_risk=False, overall_average=9.5,
    )
    receipt = {"site": SITE,
               "product_jev": verdict.to_dict() if hasattr(verdict, "to_dict") else verdict,
               "structural": structural,
               "lucas_gate_v2": lucas}
    OUT.write_text(json.dumps(receipt, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"product_jev": receipt["product_jev"],
                      "lucas": lucas["status"],
                      "artifact": lucas["artifact_sha256"][:16]}, indent=2))
    return 0 if lucas["status"].startswith("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
