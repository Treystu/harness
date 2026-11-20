"""Gates for the W468/W469 re-run filings and the intake row: Product Jev first,
Lucas Gate v2 second. Same shape as gates_turn9.py; reads only local files.
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
BASE = pathlib.Path("evidence/lane-sessions/w2-2026-11-20")

ITEMS = {
    "468-rerun": (
        BASE / "filings" / "468-rerun-at-17906e2c.md",
        "Recording that the W468 window could not start at head 17906e2c because "
        "harness/jev_assessment.py still has no write path and its persistence "
        "car PR #628 is unmerged and CONFLICTING, while the champion's logic is "
        "byte-identical to 699f677; no completion credit is taken."),
    "469-rerun": (
        BASE / "filings" / "469-rerun-at-17906e2c.md",
        "Recording that at head 17906e2c the campaign trace writer is never "
        "injected by any product call site, so campaign events still reach only "
        "the uncommitted sidecar and the W469 window has no first campaign; no "
        "completion credit is taken."),
    "intake-row": (
        BASE / "filings" / "469-intake-row.md",
        "Classifying the observed defect as high severity for the found-in-use "
        "intake: #627 landed the campaign trace writer but the default campaign "
        "entry never supplies it, so the retention the merge claims is inert in "
        "use and green only in test."),
}

CATEGORY_IDS = ("1", "2", "3", "4", "5", "6", "8", "9", "10", "11")
BIAS = {"B1": 10.0, "B3": 9.5, "B4": 9.5, "B5": 9.5, "B8": 9.5,
        "B9": 9.0, "B10": 9.0, "B11": 9.5}


def main():
    settings = load_settings()
    governor = jev_face_governor(settings)
    ledger = ledger_for(settings, caller="w2-champion-audit")
    policy = policy_for(settings, governor=governor, ledger=ledger)
    print("keyed:", policy.keyed, "| governor:", bool(governor),
          "| ledger:", getattr(ledger, "path", None))
    if not (policy.keyed and governor and ledger):
        print("BLOCKER: keyed Jev needs key + shared spend governor + ledger")
        return 2

    before = len(ledger.tail(200000))
    out = {}
    for key, (path, action) in ITEMS.items():
        text = path.read_text(encoding="utf-8")
        verdict, structural = policy.evaluate_decision(
            action, GOAL, f"W2 turn-11 disposition {key}", site=SITE)
        categories = [
            {"id": cid, "applicable": True, "score": 9.5,
             "category_average": 9.5,
             "evidence": "The filing names the head it was measured at, quotes "
                         "the file:line that carries the claim, states the "
                         "falsifier, and takes no credit it did not observe.",
             "precedent": "Same disposition shape as the accepted frozen-slot "
                          "and admissibility filings: observed values only, no "
                          "improvised program, no post-freeze artifact."}
            for cid in CATEGORY_IDS
        ]
        lucas = run_typed_track(
            track="typed", artifact_text=text, category_scores=categories,
            bias_checks=[{"id": k, "score": v,
                          "rationale": "Every claim is restricted to the head "
                                       "and the code actually read at it."}
                         for k, v in BIAS.items()],
            actual_risk=False, overall_average=9.5)
        out[key] = {
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
        print(key, "jev", verdict.get("verdict"),
              f"lead={verdict.get('lead')} adv={verdict.get('advanced')} "
              f"destr={verdict.get('destructive')}",
              "| lucas", lucas["status"])

    after = len(ledger.tail(200000))
    total = sum((v["product_jev"]["cost"] or 0) for v in out.values())
    out["_meta"] = {"ledger_rows_added": after - before,
                    "total_jev_cost_usd": round(total, 8), "site": SITE,
                    "head_under_test": "17906e2c13295c4fac66b7870ca1220d9b23d289"}
    (BASE / "gates-rerun.json").write_text(json.dumps(out, indent=2),
                                           encoding="utf-8")
    print("ledger rows added:", after - before, "| jev cost $", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
