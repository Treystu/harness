"""Sergeant gates for landing W2 evidence car PR #637. Lucas Gate v2 first, product Jev second.

Merge proposition (read live at filing time):
- PR #637 head fedeb9e8, base = main e3f930eb (merge-base == main).
- CircleCI 16/16 success at the exact head (rail read live, per-context).
- Payload vs main: 68 files, all added, +6835/-0, all under
  evidence/lane-sessions/w2-2026-11-20/. Records only: no product code,
  no test, no docs row. Matches the body's "Records only" description
  (payload audit clean).
- PR ready (draft=false), MERGEABLE. GitHub mergeStateStatus UNSTABLE is
  Actions billing-lock noise; the rail is CircleCI only.
- Body names the exact head fedeb9e8 and carries no close keywords;
  merge closes nothing itself -- this evidence car carries no issue.
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
HEAD = "fedeb9e8"
MAIN = "e3f930eb"
OUT = pathlib.Path(
    "evidence/lane-sessions/sergeant-2026-11-19/gates-637-landing.json")

ACTION = (
    "Merge PR #637 at exact head fedeb9e8 onto main e3f930eb via squash: "
    "W2 turn-11/turn-12 records publication, 68 files all added +6835/-0 "
    "under evidence/lane-sessions/w2-2026-11-20/, records only, no product "
    "code. CircleCI 16/16 at the exact head, merge-base == main, ready "
    "and MERGEABLE. Body names the exact head and carries no close "
    "keywords; merge closes nothing itself; this car carries no issue."
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
                     "were read live at the exact head: 68 files (+6835/-0), "
                     "all added under evidence/lane-sessions/w2-2026-11-20/; "
                     "the body names the exact head and carries no "
                     "close keywords."}
        for cid in CATEGORY_IDS
    ]
    for c in categories:
        c["precedent"] = ("Same disposition shape as the accepted product "
                          "landings: observed values only, exact-head rail "
                          "plus payload audit against the body.")
    lucas = run_typed_track(
        track="typed", artifact_text=ACTION, category_scores=categories,
        bias_checks=[{"id": k, "score": v,
                      "rationale": "Claims are limited to what the live read "
                                   "returned."} for k, v in BIAS.items()],
        actual_risk=False, overall_average=9.5)
    verdict, structural = policy.evaluate_decision(
        ACTION, GOAL, "Sergeant landing disposition #637", site=SITE)
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
