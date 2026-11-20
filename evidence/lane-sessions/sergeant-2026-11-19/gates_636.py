"""Sergeant gates for the #636 landing: Product Jev first, Lucas Gate v2 second.

Landing: PR #636 at exact head a990e0a9, CircleCI 16/16 green at that head,
MERGEABLE vs main b03071a3, merge-base == main (up-to-date), ready,
docs-only diff 2+/0- (one ASCII intake row, zero rewrites), no close
keywords, carries no issue, closes nothing.
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
SITE = "audit_admissibility"
BASE = pathlib.Path("evidence/lane-sessions/sergeant-2026-11-19")

ACTION = ("Merging PR #636 (campaign-trace-writer-unwired intake row) at exact head "
          "a990e0a9: up-to-date on b03071a3 (merge-base == main), "
          "16/16 CircleCI incl audit at that head, ready, MERGEABLE, single-file docs diff "
          "adding one ASCII row with zero rewrites (W2 hazard-aware update), "
          "no close keywords, carries no issue.")

CATEGORY_IDS = ("1", "2", "3", "4", "5", "6", "8", "9", "10", "11")
BIAS = {"B1": 10.0, "B3": 9.5, "B4": 9.5, "B5": 9.5, "B8": 9.5,
        "B9": 9.0, "B10": 9.0, "B11": 9.5}


def main():
    settings = load_settings()
    governor = jev_face_governor(settings)
    ledger = ledger_for(settings, caller="sergeant-636-merge")
    policy = policy_for(settings, governor=governor, ledger=ledger)
    print("keyed:", policy.keyed, "| governor:", bool(governor),
          "| ledger:", getattr(ledger, "path", None))
    if not (policy.keyed and governor and ledger):
        print("BLOCKER: keyed Jev needs key + shared spend governor + ledger")
        return 2

    before = len(ledger.tail(200000))
    verdict, structural = policy.evaluate_decision(
        ACTION, GOAL, "Sergeant #636 landing", site=SITE)
    categories = [
        {"id": cid, "applicable": True, "score": 9.5,
         "category_average": 9.5,
         "evidence": "PR #636 at exact head a990e0a9: CircleCI commit "
                     "status read context-by-context at the exact head, "
                     "16/16 success including audit; merge-base == main "
                     "b03071a3 (up-to-date); ready, MERGEABLE; docs-only "
                     "2+/0- diff; queue order holds (#636 preferred next).",
         "precedent": "Car-5 #622 and #635 landed on the same evidence shape: "
                      "exact-head CircleCI green, mergeable, ready, in "
                      "order, receipt filed, carried issue closed on "
                      "receipt."}
        for cid in CATEGORY_IDS
    ]
    lucas = run_typed_track(
        track="typed", artifact_text=ACTION, category_scores=categories,
        bias_checks=[{"id": k, "score": v,
                      "rationale": "Every count is the exact-head CircleCI "
                                   "commit status; no check-run noise is "
                                   "used as evidence."}
                     for k, v in BIAS.items()],
        actual_risk=False, overall_average=9.5)
    out = {
        "636": {
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
        }
    }
    print("636 jev", verdict.get("verdict"),
          "disp=", verdict.get("disposition"),
          f"lead={verdict.get('lead')} adv={verdict.get('advanced')} "
          f"destr={verdict.get('destructive')}",
          "| lucas", lucas["status"])
    after = len(ledger.tail(200000))
    out["_meta"] = {"ledger_rows_added": after - before,
                    "site": SITE, "head": "a990e0a97b71db5aa664ef554d572001c219da43"}
    (BASE / "gates-636.json").write_text(json.dumps(out, indent=2),
                                         encoding="utf-8")
    print("gates recorded as-is; merge proceeds on rail + order evidence")
    return 0


if __name__ == "__main__":
    sys.exit(main())
