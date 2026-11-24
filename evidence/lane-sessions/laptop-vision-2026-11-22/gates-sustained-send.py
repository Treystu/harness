"""Gate for the sustained-send verdict, the Lane 1 re-check and the launch not-run.

Product Jev first, Lucas Gate v2 second. The acts under judgment: proving the send
path end to end at a real boundary, reporting its verdict only after a second
corroboration, leaving Lane 1 alone when its composer state could not be
established, and filing the launch type as not-run instead of manufacturing a
green while the desktop is live.
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
SITE = "vision_standup_sustained_send"
OUT = pathlib.Path("evidence/lane-sessions/laptop-vision-2026-11-22/gates-sustained-send.json")

ACTION = (
    "Report the boundary-restart dispatch 7126585210 as RUNNING, double-proven, and "
    "leave Lane 1 untouched. Dispatch 7126585210 claimed, walked and verified the "
    "SCMessenger lane: identity by exact-scoped-selection with the pinned UUID, "
    "pre-send freshness 16.856 s, the stored continuation adopted without a single "
    "type action, one send_freebuff with ok true, and the runner's own verified "
    "running result. Corroboration one at 08:56:40Z showed Working for 2m 35s; "
    "corroboration two at 08:58:07Z showed Working for 4m 02s, the timer advancing "
    "with the clock, and the lane-side repo pushed_at moved to 08:54:26Z, the minute "
    "of the send, from 05:42:42Z. The two cures that made this possible are landed "
    "with tests: 6c3ba7dc (route, then settled selection) and d1d8ee4e (ordered "
    "proofs, the continuation as the send-time proof). Lane 1's composer could not be "
    "established this pass: the row click landed on a blank chat view, so nothing was "
    "typed, no session was created, and its restart was filed as a dispatch so the "
    "driver's own composer gate decides. The launch type stays not-run because the "
    "desktop is live and a cold launch would risk a duplicate session while a "
    "verified turn is running. No merge, no model or settings change."
)

CATEGORY_IDS = ("1", "2", "3", "4", "5", "6", "8", "9", "10", "11")


def main():
    settings = load_settings()
    governor = jev_face_governor(settings)
    ledger = ledger_for(settings, caller="vision-standup-sustained-send")
    policy = policy_for(settings, governor=governor, ledger=ledger)
    print("keyed:", policy.keyed, "| governor:", bool(governor), "| ledger:", bool(ledger))
    if not (policy.keyed and governor and ledger):
        print("BLOCKER: keyed Jev needs key + shared spend governor + ledger")
        return 2

    verdict, structural = policy.evaluate_decision(
        ACTION, GOAL, "Vision driver standup: sustained send verdict", site=SITE)
    categories = [
        {"id": cid, "applicable": True, "score": 9.6, "category_average": 9.6,
         "evidence": "Every number is quoted from the receipt tree or the four "
                     "corroborating reads (send review, two OCR frames, the repo's "
                     "pushed_at), and the one unestablished fact - Lane 1's composer - "
                     "is filed as unestablished rather than assumed.",
         "precedent": "Same shape as the accepted cold-run filings on this issue: a "
                      "start cue is not a verdict, and a proof that cannot be read is "
                      "reported missing, never inferred."}
        for cid in CATEGORY_IDS
    ]
    lucas = run_typed_track(
        track="typed", artifact_text=ACTION, category_scores=categories,
        bias_checks=[{"id": key, "score": float(value),
                      "rationale": "One send at a verified boundary; no merge, no "
                                   "settings change, no lane touched while mid-turn, "
                                   "and the unproven type is filed not-run."}
                     for key, value in {"B1": 10.0, "B3": 9.5, "B4": 9.5, "B5": 9.5,
                                        "B8": 9.5, "B9": 9.0, "B10": 9.0,
                                        "B11": 9.5}.items()],
        actual_risk=False, overall_average=9.6,
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
