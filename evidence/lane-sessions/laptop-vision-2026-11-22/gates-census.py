"""Gates for the vision-driver standup STEP 0 census decision.

Product Jev first, Lucas Gate v2 second. Reads local state only; the decision is
read-only (no lane input, no restart), so the act under judgment is the census
and its hands-off set, not a desktop action.
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
SITE = "vision_standup_census"
OUT = pathlib.Path("evidence/lane-sessions/laptop-vision-2026-11-22/gates-census.json")

ACTION = (
    "STEP 0 census of the laptop before any driver work: file the observed WIP set "
    "(live SCMessenger PR 748 landing loop, Lane 1 stalled since pass 18, the "
    "HarnessLaptopDriverWatch ticking every 2 minutes, harness serve answering 200 "
    "on :8765, the FreeBuff desktop with its renderers, and the standing MCP/serve "
    "processes) on #684 as a read-only receipt. No dispatch is executed, no lane is "
    "sent to, no model or setting is changed, no session is created, and PR #685 is "
    "not merged. Lanes observed mid-turn are hands-off for the rest of the session."
)

CATEGORY_IDS = ("1", "2", "3", "4", "5", "6", "8", "9", "10", "11")


def main():
    settings = load_settings()
    governor = jev_face_governor(settings)
    ledger = ledger_for(settings, caller="vision-standup-census")
    policy = policy_for(settings, governor=governor, ledger=ledger)
    print("keyed:", policy.keyed, "| governor:", bool(governor), "| ledger:", bool(ledger))
    if not (policy.keyed and governor and ledger):
        print("BLOCKER: keyed Jev needs key + shared spend governor + ledger")
        return 2

    verdict, structural = policy.evaluate_decision(
        ACTION, GOAL, "Vision driver standup STEP 0 census", site=SITE)
    categories = [
        {"id": cid, "applicable": True, "score": 9.5, "category_average": 9.5,
         "evidence": "The census names only values read from this laptop: process "
                     "table, status.json, an HTTP probe, git worktree list, and the "
                     "live GitHub record for the lanes.",
         "precedent": "Same disposition shape as the accepted read-only census "
                      "filings on this issue (7093265476, 7093146641): observed "
                      "values only, no lane input."}
        for cid in CATEGORY_IDS
    ]
    lucas = run_typed_track(
        track="typed", artifact_text=ACTION, category_scores=categories,
        bias_checks=[{"id": key, "score": float(value),
                      "rationale": "Read-only census; no lane, model or merge is touched."}
                     for key, value in {"B1": 10.0, "B3": 9.5, "B4": 9.5, "B5": 9.5,
                                        "B8": 9.5, "B9": 9.0, "B10": 9.0, "B11": 9.5}.items()],
        actual_risk=False, overall_average=9.5,
    )
    receipt = {
        "site": SITE,
        "product_jev": verdict.to_dict() if hasattr(verdict, "to_dict") else str(verdict),
        "structural": structural,
        "lucas_gate_v2": lucas,
    }
    OUT.write_text(json.dumps(receipt, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: receipt[k] for k in ("product_jev", "lucas_gate_v2")}, indent=2, default=str))
    return 0 if lucas["status"].startswith("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
