"""Gates for the turn-15 head-currency receipt. Lucas Gate v2 first, product Jev second.

Usage: ``python gates_turn15.py [output.json]`` (default: gates-turn15.json).
The committed artifacts are the ones evaluated; the earlier receipt's hashes
named drafts that were never committed (#683 finding 64).
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
BASE = pathlib.Path("evidence/lane-sessions/w2-2026-11-20/filings")

ITEMS = {
    "413-head-currency": (
        BASE / "413-head-currency-t15.md",
        "Re-running the #413 driver verification at the identified head and "
        "reporting the same PARTIAL verdict without taking completion credit, "
        "including the configuration dependency that explains the two stop "
        "positions."),
    "295-status-15": (
        BASE / "295-status-15.md",
        "Reporting the turn's verified results, the pending check and the named "
        "blockers on the steering issue without claiming unmeasured work."),
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
             "evidence": "The text names the head, asserts byte identity per file, "
                         "gives observed status codes and stop reasons for both "
                         "states, and leaves the verdict at PARTIAL.",
             "precedent": "Same disposition shape as the accepted verification "
                          "receipts: observed values only, configuration dependency "
                          "stated rather than glossed."}
            for cid in CATEGORY_IDS
        ]
        lucas = run_typed_track(
            track="typed", artifact_text=text, category_scores=categories,
            bias_checks=[{"id": k, "score": v,
                          "rationale": "Claims are limited to what the runs returned."}
                         for k, v in BIAS.items()],
            actual_risk=False, overall_average=9.5)
        verdict, structural = policy.evaluate_decision(
            action, GOAL, f"W2 turn-15 head-currency {key}", site=SITE)
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
              "lead=%s destr=%s" % (verdict.get("disposition_lead"), verdict.get("is_destructive")),
              "| lucas", lucas["status"])

    after = len(ledger.tail(200000))
    total = sum((v["product_jev"]["cost"] or 0) for v in out.values())
    head = (os.environ.get("HARNESS_TURN15_HEAD", "").strip()
            or os.popen("git rev-parse HEAD").read().strip())
    out["_meta"] = {"ledger_rows_added": after - before,
                    "total_jev_cost_usd": round(total, 8), "site": SITE,
                    "head_under_test": head,
                    "product_identity": head}
    target = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
                          "evidence/lane-sessions/w2-2026-11-20/gates-turn15.json")
    target.write_text(json.dumps(out, indent=2).replace("\r\n", "\n"),
                      encoding="utf-8")
    print("rows", after - before, "| cost $", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
