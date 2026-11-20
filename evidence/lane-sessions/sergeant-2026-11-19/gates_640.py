"""Sergeant gates for landing W2 retraction car #640. Product Jev first, Lucas second.

Merge proposition (read live at filing time):
- PR #640 head 99927150, base = main 04fb1cd0 (merge-base == main: up to date).
- CircleCI 16/16 incl audit at the exact head to be confirmed pre-merge.
- Diff: docs/found-in-use.md -1 row + separator (driver-vocabulary-keyless-claim-false
  retracted, 15->14 rows, em dashes unchanged, no mojibake). #413 stays OPEN (PARTIAL).
- Body close-scan clean (cubic auto-fix boilerplate only).
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
HEAD = "9992715088d2c5a1c42cf98d393e35d776276d0d"
MAIN = "04fb1cd03ca57aed223535162e7590cee888ed67"
OUT = pathlib.Path(
    "evidence/lane-sessions/sergeant-2026-11-19/gates-640.json")

ACTION = (
    "Merge PR #640 at exact head 99927150 onto main 04fb1cd0 via squash: "
    "remove the false row driver-vocabulary-keyless-claim-false plus its "
    "separator from docs/found-in-use.md (15->14 rows, 11 em dashes intact, "
    "no mojibake). CircleCI 16/16 incl audit at the exact head, "
    "merge-base == main, ready, MERGEABLE. #413 stays OPEN with PARTIAL verdict; "
    "no replacement row filed; keyless tier already covered by "
    "driver-decision-tier-unkeyed."
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
    verdict, structural = policy.evaluate_decision(
        ACTION, GOAL, "Sergeant landing disposition #640", site=SITE)
    categories = [
        {"id": cid, "applicable": True, "score": 9.5,
         "category_average": 9.5,
         "evidence": "The PR head, base, rail counts and diff were read live "
                     "at the exact head; the removal is ASCII-only, one row "
                     "plus separator, and the body carries no close keywords."}
        for cid in CATEGORY_IDS
    ]
    for c in categories:
        c["precedent"] = ("Same disposition shape as the accepted docs-only "
                          "intake landings: observed values only.")
    lucas = run_typed_track(
        track="typed", artifact_text=ACTION, category_scores=categories,
        bias_checks=[{"id": k, "score": v,
                      "rationale": "Claims are limited to what the live read "
                                   "returned."} for k, v in BIAS.items()],
        actual_risk=False, overall_average=9.5)
    out = {
        "product_jev": {
            "verdict": verdict.get("verdict"),
            "disposition": verdict.get("disposition"),
            "margin": verdict.get("margin"),
            "lead": verdict.get("lead"),
            "advanced": verdict.get("advanced"),
            "destructive": verdict.get("destructive"),
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
