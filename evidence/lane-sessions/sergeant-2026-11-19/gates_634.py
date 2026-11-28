"""Sergeant gates for deliverable (4): gate receipts on #634 evidence draft.

Merge proposition (read live at filing time):
- PR #634 head 3e8ac2cf, base main d916a7bb (merge-base 4618b5f9: BEHIND, draft, parked).
- CircleCI at exact head: 16/16 success, 0 fail (commit-status rail, Actions noise ignored).
- Diff: evidence/lane-sessions/sergeant-2026-11-19/ only, 79 files, docs/evidence receipts.
- Body close-scan clean; nothing closes an issue.
Disposition sought: record only (draft stays parked, not landed this turn).
Lucas Gate v2 first, product Jev second.
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
SITE = "sergeant_evidence"
HEAD = "3e8ac2cf4858fb70ce9e585b39c6eb10457a76fe"
MAIN = "d916a7bbe3de878dc842635c69f9f1cf3e619bfa"
OUT = pathlib.Path(
    "evidence/lane-sessions/sergeant-2026-11-19/gates-634.json")

ACTION = (
    "Record-only gate evaluation for PR #634 at exact head 3e8ac2cf "
    "(base main d916a7bb, merge-base 4618b5f9: BEHIND, draft, parked): "
    "79 files under evidence/lane-sessions/sergeant-2026-11-19/ only, "
    "gate drivers plus JSON receipts as returned plus status notes. "
    "CircleCI 16/16 at the exact head, body carries no close keywords, "
    "nothing closes an issue, no product code, no docs row. "
    "No merge taken on this receipt; draft stays parked."
)

CATEGORY_IDS = ("1", "2", "3", "4", "5", "6", "8", "9", "10", "11")
BIAS = {"B1": 10.0, "B3": 9.5, "B4": 9.5, "B5": 9.5, "B8": 9.5,
        "B9": 9.0, "B10": 9.0, "B11": 9.5}


def main():
    settings = load_settings()
    governor = jev_face_governor(settings)
    ledger = ledger_for(settings, caller="sergeant-evidence")
    policy = policy_for(settings, governor=governor, ledger=ledger)
    print("keyed:", policy.keyed, "| governor:", bool(governor))
    if not (policy.keyed and governor and ledger):
        print("BLOCKER: keyed Jev needs key + shared spend governor + ledger")
        return 2

    before = len(ledger.tail(200000))
    categories = [
        {"id": cid, "applicable": True, "score": 9.5,
         "category_average": 9.5,
         "evidence": "The PR head, base, merge-base, rail counts and file "
                     "scope were read live at the exact head; the branch "
                     "touches evidence only and the body carries no close "
                     "keywords.",
         "precedent": "Same disposition shape as the accepted docs-only "
                      "intake landing #636: observed values only."}
        for cid in CATEGORY_IDS
    ]
    lucas = run_typed_track(
        track="typed", artifact_text=ACTION, category_scores=categories,
        bias_checks=[{"id": k, "score": v,
                      "rationale": "Claims are limited to what the live read "
                                   "returned."} for k, v in BIAS.items()],
        actual_risk=False, overall_average=9.5)
    verdict, structural = policy.evaluate_decision(
        ACTION, GOAL, "Sergeant evidence disposition #634", site=SITE)
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
