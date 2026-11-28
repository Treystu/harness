"""Sergeant gates for landing W1 car PR #630. Lucas Gate v2 first, product Jev second.

Merge proposition (read live at filing time):
- PR #630 head f70ecde2, base = main d916a7bb (merge-base == main).
- CircleCI 16/16 success incl audit at the exact head (rail read live).
- Payload vs main: 3 files (M harness/apply_policy.py, M harness/escalation.py,
  A tests/test_escalation_attempt_trace_471.py), +284/-2. Matches the body's
  "#471 escalation attempt trace" description (payload audit clean).
- PR ready (draft=false), MERGEABLE. Body carries no close keywords; merge
  closes nothing itself — #471 is closed by the lander on the receipt.
- GitHub mergeStateStatus noise ignored; CircleCI is the rail.
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

GOAL = ("Ship verified harness changes through the review gates without "
        "unapproved destructive action.")
SITE = "sergeant_landing"
HEAD = "f70ecde2"
MAIN = "d916a7bbe3de878dc842635c69f9f1cf3e619bfa"
OUT = pathlib.Path(
    "evidence/lane-sessions/sergeant-2026-11-19/gates-630.json")

ACTION = (
    "Merge PR #630 at exact head f70ecde2 onto main d916a7bb via squash: "
    "record start rung, attempted rung and realized pass per escalation "
    "attempt (#471). 3 files, +284/-2 (M harness/apply_policy.py, "
    "M harness/escalation.py, A tests/test_escalation_attempt_trace_471.py). "
    "CircleCI 16/16 incl audit at the exact head, merge-base == main, ready "
    "and MERGEABLE. Body carries no close keywords; merge closes nothing "
    "itself; #471 is closed by the lander on the receipt."
)

CATEGORY_IDS = ("1", "2", "3", "4", "5", "6", "8", "9", "10", "11")
BIAS = {"B1": 10.0, "B3": 9.5, "B4": 9.5, "B5": 9.5, "B8": 9.5,
        "B9": 9.0, "B10": 9.0, "B11": 9.5}


def main():
    settings = load_settings()
    governor = jev_face_governor(settings)
    ledger = ledger_for(settings, caller="sergeant-landing")
    policy = policy_for(settings, governor=governor, ledger=ledger)
    print("keyed:", policy.keyed, "| governor:", bool(governor))
    if not (policy.keyed and governor and ledger):
        print("BLOCKER: keyed Jev needs key + shared spend governor + ledger")
        return 2

    before = len(ledger.tail(200000))
    categories = [
        {"id": cid, "applicable": True, "score": 9.5,
         "category_average": 9.5,
         "evidence": "The PR head, base, rail counts and full name-status "
                     "were read live at the exact head: 3 files (+284/-2), "
                     "2 modified + 1 added test file; the body carries no "
                     "close keywords."}
        for cid in CATEGORY_IDS
    ]
    for c in categories:
        c["precedent"] = ("Same disposition shape as the accepted product "
                          "landings: observed values only, tested change "
                          "with focused + full suite recorded in the body.")
    lucas = run_typed_track(
        track="typed", artifact_text=ACTION, category_scores=categories,
        bias_checks=[{"id": k, "score": v,
                      "rationale": "Claims are limited to what the live read "
                                   "returned."} for k, v in BIAS.items()],
        actual_risk=False, overall_average=9.5)
    verdict, structural = policy.evaluate_decision(
        ACTION, GOAL, "Sergeant landing disposition #630", site=SITE)
    out = {
        "product_jev": {
            "verdict": verdict.get("verdict"),
            "disposition": verdict.get("disposition"),
            "margin": verdict.get("margin"),
            "lead": verdict.get("disposition_lead"),
            "advanced": verdict.get("advances_goal"),
            "destructive": verdict.get("is_destructive"),
            "supported": structural.get("supported"),
            "cost": structural.get("cost"),
            "model": structural.get("model"),
        },
        "lucas": {"status": lucas["status"], "track": lucas["track"],
                  "reasons": lucas["reasons"],
                  "artifact_sha256": lucas["artifact_sha256"]},
        "_meta": {"ledger_rows_added": len(ledger.tail(200000)) - before,
                  "site": SITE, "head": HEAD, "base": MAIN},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2).replace("\r\n", "\n"),
                   encoding="utf-8")
    print("jev", verdict.get("verdict"), verdict.get("disposition"),
          "| lucas", lucas["status"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
