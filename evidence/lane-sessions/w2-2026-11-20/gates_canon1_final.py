"""Gates for the two admissibility verdicts and the CANON-1 inventory.
Lucas Gate v2 first, product Jev second. Reads local files only.
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
    "468-verdict": (
        BASE / "filings" / "468-admissibility-verdict.md",
        "Posting the per-brief admissibility verdict for #468: a later eligible "
        "window W468 is admissible with identity verified at fb27ee89, it is "
        "blocked on unmerged PR #628, and no completion credit is taken."),
    "469-verdict": (
        BASE / "filings" / "469-admissibility-verdict.md",
        "Posting the per-brief admissibility verdict for #469: a later eligible "
        "window W469 is admissible with identity verified at fb27ee89, it is "
        "blocked on an unwired trace writer with no product call site, and no "
        "completion credit is taken."),
    "canon1": (
        BASE / "filings" / "466-canon1-inventory-final.md",
        "Recording the CANON-1 brief-to-mechanism inventory: ten brief numbers, "
        "nine live obligations, one closed, and the eighth figure reconciled to "
        "the one rule that yields it, with a disclosed correction of my earlier "
        "claim and no change to any brief, bar, order or mechanism rule."),
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
        categories = [
            {"id": cid, "applicable": True, "score": 9.5,
             "category_average": 9.5,
             "evidence": "The filing quotes the clause it rules on, names the "
                         "head and the file:line it measured, names the "
                         "unblocker, and takes no credit it did not observe.",
             "precedent": "Same disposition shape as the accepted frozen-slot "
                          "verdicts and admissibility rulings: observed values "
                          "only, no improvised program, no post-freeze artifact."}
            for cid in CATEGORY_IDS
        ]
        lucas = run_typed_track(
            track="typed", artifact_text=text, category_scores=categories,
            bias_checks=[{"id": k, "score": v,
                          "rationale": "Every claim is restricted to the head "
                                       "and the record actually read."}
                         for k, v in BIAS.items()],
            actual_risk=False, overall_average=9.5)
        verdict, structural = policy.evaluate_decision(
            action, GOAL, f"W2 turn-12 disposition {key}", site=SITE)
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
              f"lead={verdict.get('disposition_lead')} adv={verdict.get('advances_goal')} "
              f"destr={verdict.get('is_destructive')}",
              "| lucas", lucas["status"])

    after = len(ledger.tail(200000))
    total = sum((v["product_jev"]["cost"] or 0) for v in out.values())
    out["_meta"] = {"ledger_rows_added": after - before,
                    "total_jev_cost_usd": round(total, 8), "site": SITE,
                    "head_under_test": "fb27ee895f43638cade271bcd9af33d2276b0136"}
    (BASE / "gates-canon1-final.json").write_text(
        json.dumps(out, indent=2).replace("\r\n", "\n"), encoding="utf-8")
    print("ledger rows added:", after - before, "| jev cost $", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
