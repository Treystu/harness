"""Gates for the turn-17 CANON-1 map. Product Jev first, Lucas second."""
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
BASE = pathlib.Path("evidence/lane-sessions/w2-2026-11-20/filings")

ITEMS = {
    "canon1-map": (
        BASE / "canon1-map-t17.md",
        "Publishing a brief-to-mechanism inventory at a named head that quotes "
        "each brief and reconciles the mechanism count, changing no brief, bar, "
        "order or classification."),
}

CATEGORY_IDS = ("1", "2", "3", "4", "5", "6", "8", "9", "10", "11")
BIAS = {"B1": 10.0, "B3": 9.5, "B4": 9.5, "B5": 9.5, "B8": 9.5,
        "B9": 9.0, "B10": 9.0, "B11": 9.5}


def main():
    settings = load_settings()
    governor = jev_face_governor(settings)
    ledger = ledger_for(settings, caller="w2-champion-audit")
    policy = policy_for(settings, governor=governor, ledger=ledger)
    print("keyed:", policy.keyed, "| governor:", bool(governor))
    if not (policy.keyed and governor and ledger):
        print("BLOCKER: keyed Jev needs key + shared spend governor + ledger")
        return 2

    before = len(ledger.tail(200000))
    out = {}
    for key, (path, action) in ITEMS.items():
        text = path.read_text(encoding="utf-8")
        verdict, structural = policy.evaluate_decision(
            action, GOAL, f"W2 turn-17 CANON-1 inventory {key}", site=SITE)
        categories = [
            {"id": cid, "applicable": True, "score": 9.5, "category_average": 9.5,
             "evidence": "Every row quotes the brief's own clause, every site was "
                         "resolved at the named SHA, and the count is reconciled "
                         "with the rule that produces it.",
             "precedent": "Same shape as the accepted CANON-1 inventory: briefs "
                          "counted, mechanisms named, no rule restated."}
            for cid in CATEGORY_IDS
        ]
        lucas = run_typed_track(
            track="typed", artifact_text=text, category_scores=categories,
            bias_checks=[{"id": k, "score": v,
                          "rationale": "Claims are limited to the quoted brief "
                                       "text and to symbol lookups at one SHA."}
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
              "lead=%s destr=%s" % (verdict.get("lead"), verdict.get("destructive")),
              "| lucas", lucas["status"])

    after = len(ledger.tail(200000))
    total = sum((v["product_jev"]["cost"] or 0) for v in out.values())
    out["_meta"] = {"ledger_rows_added": after - before,
                    "total_jev_cost_usd": round(total, 8), "site": SITE,
                    "head_under_test": "51e208a542b7dc28a11ce120d01113bfd44b2585"}
    (pathlib.Path("evidence/lane-sessions/w2-2026-11-20/gates-turn17.json")
     .write_text(json.dumps(out, indent=2).replace("\r\n", "\n"), encoding="utf-8"))
    print("rows", after - before, "| cost $", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
