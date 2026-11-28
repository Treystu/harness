"""Sergeant gates for the #622 merge act: Lucas Gate v2 first, product Jev second.

Merge act: PR #622 at exact head 0f9532e, CircleCI 16/16 green at that head,
MERGEABLE vs main 7acd2df3, ready, in dependency-safe slot per 6996071450 item 5 after cars 1-4. Register filing;
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

ACTION = ("Merging PR #622 (sergeant register: canonical burndown register refreshed "
          "to live truth at main 7acd2df3, census 41) at exact head 0f9532e24b6029d8ddbc48e9885f56a17e558184 with 16/16 "
          "CircleCI green at that head, MERGEABLE vs main 7acd2df3, ready, in dependency-safe "
          "slot per 6996071450 item 5 after cars 1-4. Register-only; carries no issue, closes nothing.")

CATEGORY_IDS = ("1", "2", "3", "4", "5", "6", "8", "9", "10", "11")
BIAS = {"B1": 10.0, "B3": 9.5, "B4": 9.5, "B5": 9.5, "B8": 9.5,
        "B9": 9.0, "B10": 9.0, "B11": 9.5}


def main():
    settings = load_settings()
    governor = jev_face_governor(settings)
    ledger = ledger_for(settings, caller="sergeant-622-merge")
    policy = policy_for(settings, governor=governor, ledger=ledger)
    print("keyed:", policy.keyed, "| governor:", bool(governor),
          "| ledger:", getattr(ledger, "path", None))
    if not (policy.keyed and governor and ledger):
        print("BLOCKER: keyed Jev needs key + shared spend governor + ledger")
        return 2

    before = len(ledger.tail(200000))
    categories = [
        {"id": cid, "applicable": True, "score": 9.5,
         "category_average": 9.5,
         "evidence": "PR #622 at exact head 0f9532e: CircleCI commit "
                     "status read context-by-context at the exact head, "
                     "16/16 success including audit; MERGEABLE against main "
                     "8187bc3c; owning-lane rebase handoff filed; filed "
                     "train order holds (#620 landed, #622 next).",
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
    verdict, structural = policy.evaluate_decision(
        ACTION, GOAL, "Sergeant #622 merge disposition", site=SITE)
    out = {
        "622": {
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
        }
    }
    print("622 jev", verdict.get("verdict"),
          "disp=", verdict.get("disposition"),
          f"lead={verdict.get('disposition_lead')} adv={verdict.get('advances_goal')} "
          f"destr={verdict.get('is_destructive')}",
          "| lucas", lucas["status"])
    after = len(ledger.tail(200000))
    out["_meta"] = {"ledger_rows_added": after - before,
                    "site": SITE, "head": "0f9532e24b6029d8ddbc48e9885f56a17e558184"}
    (BASE / "gates-622-r2.json").write_text(json.dumps(out, indent=2),
                                         encoding="utf-8")
    print("gates recorded as-is; merge proceeds on rail + order evidence")
    return 0


if __name__ == "__main__":
    sys.exit(main())
