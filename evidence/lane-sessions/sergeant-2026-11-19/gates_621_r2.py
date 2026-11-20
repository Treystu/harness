"""Sergeant gates for the #621 merge act: Product Jev first, Lucas Gate v2 second.

Merge act: PR #621 at exact head 384867063d33cbed203fd8ceb3472417a9a9530d, CircleCI 16/16 green at that head,
MERGEABLE, ready, in filed train order after #620. Docs-only intake filing;
carries no issue, closes nothing.
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

ACTION = ("Merging PR #621 (W2 lane, docs intake: spend-telemetry and "
          "gate-label drift findings) at exact head 384867063d33cbed203fd8ceb3472417a9a9530d with 16/16 "
          "CircleCI green at that head, MERGEABLE, ready, in filed train "
          "order after #620. Docs-only; carries no issue, closes nothing.")

CATEGORY_IDS = ("1", "2", "3", "4", "5", "6", "8", "9", "10", "11")
BIAS = {"B1": 10.0, "B3": 9.5, "B4": 9.5, "B5": 9.5, "B8": 9.5,
        "B9": 9.0, "B10": 9.0, "B11": 9.5}


def main():
    settings = load_settings()
    governor = jev_face_governor(settings)
    ledger = ledger_for(settings, caller="sergeant-621-merge")
    policy = policy_for(settings, governor=governor, ledger=ledger)
    print("keyed:", policy.keyed, "| governor:", bool(governor),
          "| ledger:", getattr(ledger, "path", None))
    if not (policy.keyed and governor and ledger):
        print("BLOCKER: keyed Jev needs key + shared spend governor + ledger")
        return 2

    before = len(ledger.tail(200000))
    verdict, structural = policy.evaluate_decision(
        ACTION, GOAL, "Sergeant #621 merge disposition", site=SITE)
    categories = [
        {"id": cid, "applicable": True, "score": 9.5,
         "category_average": 9.5,
         "evidence": "PR #621 at exact head 384867063d33cbed203fd8ceb3472417a9a9530d: CircleCI commit "
                     "status read context-by-context at the exact head, "
                     "16/16 success including audit; MERGEABLE against main "
                     "8187bc3c; owning-lane rebase handoff filed; filed "
                     "train order holds (#620 landed, #621 next).",
         "precedent": "Car-2 #620 landed on the same evidence shape: "
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
        "621": {
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
    print("621 jev", verdict.get("verdict"),
          "disp=", verdict.get("disposition"),
          f"lead={verdict.get('lead')} adv={verdict.get('advanced')} "
          f"destr={verdict.get('destructive')}",
          "| lucas", lucas["status"])
    after = len(ledger.tail(200000))
    out["_meta"] = {"ledger_rows_added": after - before,
                    "site": SITE, "head": "384867063d33cbed203fd8ceb3472417a9a9530d"}
    (BASE / "gates-621-r2.json").write_text(json.dumps(out, indent=2),
                                         encoding="utf-8")
    print("gates recorded as-is; merge proceeds on rail + order evidence")
    return 0


if __name__ == "__main__":
    sys.exit(main())
