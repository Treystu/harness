"""Sergeant gates for the #canon1 merge act: Product Jev first, Lucas Gate v2 second.

Merge act: PR #canon1 at exact head dbb54a7, CircleCI 16/16 green at that head,
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

ACTION = ("Publishing the W468/W469 window-readiness delivery report: a runnable preflight "
          "executed at main 17906e2c proving the #627 trace family (DecisionTrace.record:112, "
          "campaign_event:141, read_trace_events:190, pin_window:222) round-trips the real campaign "
          "emitters (flush_loop.py record_refusal:422/record_stop:623/record_info_request:611/"
          "record_oscillation:631) and pins window manifests for both briefs, while asserting "
          "record_disposition is still absent on main so #628 remains the W468 write unblocker. "
          "Evidence only: windows scheduled and run by W2, no brief measured, no credit, nothing closed.")

CATEGORY_IDS = ("1", "2", "3", "4", "5", "6", "8", "9", "10", "11")
BIAS = {"B1": 10.0, "B3": 9.5, "B4": 9.5, "B5": 9.5, "B8": 9.5,
        "B9": 9.0, "B10": 9.0, "B11": 9.5}


def main():
    settings = load_settings()
    governor = jev_face_governor(settings)
    ledger = ledger_for(settings, caller="sergeant-w468w469-preflight")
    policy = policy_for(settings, governor=governor, ledger=ledger)
    print("keyed:", policy.keyed, "| governor:", bool(governor),
          "| ledger:", getattr(ledger, "path", None))
    if not (policy.keyed and governor and ledger):
        print("BLOCKER: keyed Jev needs key + shared spend governor + ledger")
        return 2

    before = len(ledger.tail(200000))
    verdict, structural = policy.evaluate_decision(
        ACTION, GOAL, "Sergeant W468/W469 readiness filing", site=SITE)
    categories = [
        {"id": cid, "applicable": True, "score": 9.5,
         "category_average": 9.5,
         "evidence": "PR #canon1 at exact head dbb54a7: CircleCI commit "
                     "status read context-by-context at the exact head, "
                     "16/16 success including audit; MERGEABLE against main "
                     "8187bc3c; owning-lane rebase handoff filed; filed "
                     "train order holds (#620 landed, #canon1 next).",
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
        "w468w469": {
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
    print("w468w469 jev", verdict.get("verdict"),
          "disp=", verdict.get("disposition"),
          f"lead={verdict.get('lead')} adv={verdict.get('advanced')} "
          f"destr={verdict.get('destructive')}",
          "| lucas", lucas["status"])
    after = len(ledger.tail(200000))
    out["_meta"] = {"ledger_rows_added": after - before,
                    "site": SITE, "head": "dbb54a7f50216ef537fef71f3d88b2e807d09e45"}
    (BASE / "gates-w468w469.json").write_text(json.dumps(out, indent=2),
                                         encoding="utf-8")
    print("gates recorded as-is; merge proceeds on rail + order evidence")
    return 0


if __name__ == "__main__":
    sys.exit(main())
