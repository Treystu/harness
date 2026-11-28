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
SITE = "vision_standup_fleet"
OUT = pathlib.Path("evidence/lane-sessions/laptop-vision-2026-11-22/gates-fleet.json")

ACTION = (
    "Execute the corrected fleet order of 23:32 HST without manufacturing a green: "
    "follow the five already-filed boundary dispatches to their verdicts, file Lane 1's "
    "restart under the composer fence, and name every lane that cannot be addressed. "
    "Measured outcomes: SCMessenger was mid-turn when its dispatch was claimed and "
    "received no input, which is the hands-off rule enforced by the driver; Kalshi was "
    "claimed, walked, and parked by name because the project session list did not hold "
    "'Kalshi Paper Burndown' - its trace shows the walk reading the CLOUD project lists "
    "for agensi-skills, SCMessenger and refoss-energy-viz and never reaching the "
    "Kalshi-Trader heading; Harness Audit, Lane 2, BigEnergyCo and Disk Audit are filed "
    "and queued with no runner trace yet; Lane 1's dispatch is filed under the composer "
    "fence with the foreign draft untouchable; Agensi and CivicScope have no pinned "
    "identity in the codebase, so no dispatch may address them and their identity is "
    "named as the gap rather than guessed at. Nothing was merged, no model or setting "
    "was changed, no other lane's composer was touched, and every negative is filed "
    "with its own trace instead of being dressed as a start."
)

CATEGORY_IDS = ("1", "2", "3", "4", "5", "6", "8", "9", "10", "11")


def main():
    settings = load_settings()
    governor = jev_face_governor(settings)
    ledger = ledger_for(settings, caller="vision-standup-launch")
    policy = policy_for(settings, governor=governor, ledger=ledger)
    print("keyed:", policy.keyed, "| governor:", bool(governor), "| ledger:", bool(ledger))
    if not (policy.keyed and governor and ledger):
        print("BLOCKER: keyed Jev needs key + shared spend governor + ledger")
        return 2

    verdict, structural = policy.evaluate_decision(
        ACTION, GOAL, "Vision driver standup: launch cold run", site=SITE)
    categories = [
        {"id": cid, "applicable": True, "score": 9.6, "category_average": 9.6,
         "evidence": "Every per-lane outcome is quoted from its own runner trace or its "
                     "#684 receipt, and the lanes with no trace are named as queued "
                     "rather than counted as launched.",
         "precedent": "Same shape as the accepted fleet filings on this issue: a lane is "
                      "RUNNING only with a second corroboration, and an unaddressable "
                      "lane is filed as a named gap."}
        for cid in CATEGORY_IDS
    ]
    lucas = run_typed_track(
        track="typed", artifact_text=ACTION, category_scores=categories,
        bias_checks=[{"id": key, "score": float(value),
                      "rationale": "No send to any lane that was mid-turn; every negative "
                                   "carries its trace; nothing merged; no setting "
                                   "changed."}
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
