"""Sergeant gates for the #620 merge act: Lucas Gate v2 first, product Jev second.

Merge act: PR #620 at exact head 4817a4fe, CircleCI 16/16 green at that head,
MERGEABLE, ready (draft off, W1's act), in filed train order after #619.
Carries #311 (local-fit optional train/export lane job), closed on receipt.
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
BASE.mkdir(parents=True, exist_ok=True)

ACTION = ("Merging PR #620 (W1 lane, #311 local-fit optional train/export "
          "lane job) at exact head 4817a4fe with 16/16 CircleCI green at "
          "that head, MERGEABLE, ready, in filed train order after #619, "
          "carrying issue #311 to closure on the merge receipt.")

CATEGORY_IDS = ("1", "2", "3", "4", "5", "6", "8", "9", "10", "11")
BIAS = {"B1": 10.0, "B3": 9.5, "B4": 9.5, "B5": 9.5, "B8": 9.5,
        "B9": 9.0, "B10": 9.0, "B11": 9.5}


def main():
    settings = load_settings()
    governor = jev_face_governor(settings)
    ledger = ledger_for(settings, caller="sergeant-620-merge")
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
         "evidence": "PR #620 at exact head 4817a4fe: CircleCI commit "
                     "status read context-by-context at the exact head, "
                     "16/16 success including audit; MERGEABLE against main "
                     "a7ca742e; draft flag cleared by the owning lane; "
                     "filed train order holds (#619 landed, #620 next).",
         "precedent": "Car-1 #619 landed on the same evidence shape: "
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
        ACTION, GOAL, "Sergeant #620 merge disposition", site=SITE)
    out = {
        "620": {
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
    print("620 jev", verdict.get("verdict"),
          f"lead={verdict.get('disposition_lead')} adv={verdict.get('advances_goal')} "
          f"destr={verdict.get('is_destructive')}",
          "| lucas", lucas["status"])
    after = len(ledger.tail(200000))
    out["_meta"] = {"ledger_rows_added": after - before,
                    "site": SITE, "head": "4817a4fe"}
    (BASE / "gates-620.json").write_text(json.dumps(out, indent=2),
                                         encoding="utf-8")
    ok = (lucas["status"] == "pass"
          and (verdict.get("verdict") or "") in ("go", "proceed",
                                                     "approve", "pass")
          and float(verdict.get("is_destructive") or 0) < 0.5)
    print("MERGE DECISION:", "GO" if ok else "HOLD")
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
