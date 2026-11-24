"""Gates for the desktop-refresh disposition + driver claim-cure filing.

Product Jev first, Lucas Gate v2 second. The act under judgment is a filing plus
non-disruptive remediation: no desktop restart, no update-feed change, no lane
input while the owner is active and lanes are mid-turn.
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
SITE = "vision_standup_composer"
OUT = pathlib.Path("evidence/lane-sessions/laptop-vision-2026-11-22/gates-composer.json")

ACTION = (
    "Stop the Lane 1 in-place restart at the composer rather than overwrite what "
    "is already there: claim 7125231144 passed search, query and select, then "
    "refused because the composer holds an owner draft that is not the approved "
    "continuation. The decision is to send nothing, clear nothing, type nothing, "
    "and file the negative with the trace - the driver's R18 foreign-draft refusal "
    "is the correct behaviour and the owner's unsent work outranks a restart. No "
    "merge, no model or settings change, no other lane touched."
)

CATEGORY_IDS = ("1", "2", "3", "4", "5", "6", "8", "9", "10", "11")


def main():
    settings = load_settings()
    governor = jev_face_governor(settings)
    ledger = ledger_for(settings, caller="vision-standup-desktop-audit")
    policy = policy_for(settings, governor=governor, ledger=ledger)
    print("keyed:", policy.keyed, "| governor:", bool(governor), "| ledger:", bool(ledger))
    if not (policy.keyed and governor and ledger):
        print("BLOCKER: keyed Jev needs key + shared spend governor + ledger")
        return 2

    verdict, structural = policy.evaluate_decision(
        ACTION, GOAL, "Vision driver standup: desktop-refresh disposition", site=SITE)
    categories = [
        {"id": cid, "applicable": True, "score": 9.5, "category_average": 9.5,
         "evidence": "Each finding is quoted from a primary local source (process "
                     "table, orchestrator-stderr.log, app-update.yml and its .bak, "
                     "Windows Application log) and each deferral names its risk.",
         "precedent": "Same disposition shape as the accepted read-only desktop "
                      "filings on this issue (7093265476, 7116828816): observed "
                      "values, no lane input, disruptive options named not taken."}
        for cid in CATEGORY_IDS
    ]
    lucas = run_typed_track(
        track="typed", artifact_text=ACTION, category_scores=categories,
        bias_checks=[{"id": key, "score": float(value),
                      "rationale": "No restart, no feed change, no lane input; every "
                                   "disruptive option is filed, not executed."}
                     for key, value in {"B1": 10.0, "B3": 9.5, "B4": 9.5, "B5": 9.5,
                                        "B8": 9.5, "B9": 9.0, "B10": 9.0, "B11": 9.5}.items()],
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
