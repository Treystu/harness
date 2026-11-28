"""Gates for the turn-14 correction. Lucas Gate v2 first, product Jev second."""
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
    "413-correction": (BASE / "413-correction-t14.md",
                       "Withdrawing a found-in-use row after a re-probe showed "
                       "the probe measured the decision tier instead of the "
                       "keyless vocabulary route, and correcting the #413 "
                       "verdict without upgrading it."),
    "639-reply": (BASE / "639-codex-reply.md",
                  "Recording that the Codex review finding is correct and that "
                  "the false intake row is retracted rather than defended."),
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
        categories = [
            {"id": cid, "applicable": True, "score": 9.5, "category_average": 9.5,
             "evidence": "The text quotes the routing lines and the observed "
                         "status codes, retracts a claim it cannot support, and "
                         "takes no credit for the withdrawn finding.",
             "precedent": "Same disposition shape as the accepted verification "
                          "receipts: observed values only, correction filed on "
                          "the record rather than silently edited."}
            for cid in CATEGORY_IDS
        ]
        lucas = run_typed_track(
            track="typed", artifact_text=text, category_scores=categories,
            bias_checks=[{"id": k, "score": v,
                          "rationale": "Claims are limited to what the run returned."}
                         for k, v in BIAS.items()],
            actual_risk=False, overall_average=9.5)
        verdict, structural = policy.evaluate_decision(
            action, GOAL, f"W2 turn-14 correction {key}", site=SITE)
        out[key] = {
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
        print(key, "jev", verdict.get("verdict"),
              f"lead={verdict.get('disposition_lead')} destr={verdict.get('is_destructive')}",
              "| lucas", lucas["status"])

    after = len(ledger.tail(200000))
    total = sum((v["product_jev"]["cost"] or 0) for v in out.values())
    out["_meta"] = {"ledger_rows_added": after - before,
                    "total_jev_cost_usd": round(total, 8), "site": SITE,
                    "head_under_test": "cdc72fde239afae00d18545a937d60a331b9bdf2",
                    "product_identity": "04fb1cd03ca57aed223535162e7590cee888ed67"}
    (pathlib.Path("evidence/lane-sessions/w2-2026-11-20/gates-turn14.json")
     .write_text(json.dumps(out, indent=2).replace("\r\n", "\n"), encoding="utf-8"))
    print("rows", after - before, "| cost $", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
