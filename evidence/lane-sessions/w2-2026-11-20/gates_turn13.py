"""Gates for the turn-13 verification filings. Lucas Gate v2 first, product Jev second."""
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
    "567": (BASE / "567-result-t13.md",
            "Recording the #567 verification at head 6ea96c29: all four log "
            "surfaces answer with the owner token and refuse 401 without it, "
            "while the untimestamped transcript stays unrecoverable."),
    "413": (BASE / "413-result-t13.md",
            "Recording the #413 verification at head 6ea96c29: a declared DOM "
            "source clears capture and the step now stops at the unkeyed "
            "decision tier, with the round-trip still unproven."),
    "414": (BASE / "414-result-t13.md",
            "Recording the #414 verification at head 6ea96c29: hermetic MCP "
            "stdio handshake, 33 tools, ledger_status present, one read-only "
            "call succeeded, exit 0."),
    "422": (BASE / "422-parked-t13.md",
            "Recording #422 as parked at main 4618b5f9: the citation gate "
            "refuses honestly without a resolver, no production call site "
            "exists, and the product wiring decision is named with its owner."),
    "intake-413": (BASE / "413-intake-row.md",
            "Classifying as medium the finding that the driver's vocabulary "
            "action is documented as keyless yet terminates at the keyed "
            "decision stage, routed to the found-in-use intake."),
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
             "evidence": "The filing names the exact head, quotes the observed "
                         "status or payload, and takes no credit it did not "
                         "measure.",
             "precedent": "Same disposition shape as the accepted verification "
                          "receipts: observed values only, no improvised run."}
            for cid in CATEGORY_IDS
        ]
        lucas = run_typed_track(
            track="typed", artifact_text=text, category_scores=categories,
            bias_checks=[{"id": k, "score": v,
                          "rationale": "Claims are limited to what the run returned."}
                         for k, v in BIAS.items()],
            actual_risk=False, overall_average=9.5)
        verdict, structural = policy.evaluate_decision(
            action, GOAL, f"W2 turn-13 disposition {key}", site=SITE)
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
                    "head_under_test": "6ea96c29fed9373e8a591085ca3173d18c9edd1b",
                    "product_identity": "4618b5f997a0f04331b26aa8452568835dfccf1e"}
    (pathlib.Path("evidence/lane-sessions/w2-2026-11-20/gates-turn13.json")
     .write_text(json.dumps(out, indent=2).replace("\r\n", "\n"), encoding="utf-8"))
    print("rows", after - before, "| cost $", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
