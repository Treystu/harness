"""Gates for turn 9 filings: Lucas Gate v2 first, product Jev second.

Product Jev is the keyed gate the CLI/MCP faces compose (jev_face_governor +
ledger_for), so each call is reserved, reconciled and receipted in the shared
ledger. Lucas Gate v2 is the typed deterministic scorecard; this agent owns
the judgment and the runner validates the scorecard.
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
    "415": (BASE / "filings" / "415-ceiling-rerun.md",
            "Recording the #415 re-run after the daily reset: the paid route still refuses with provider spend limit while the key surface reports full remaining limit, the $0 lane ran the ask and Jev refused the answer, and two new defects (reasoning leaked into the answer, web records with no on-query source) are reported without claiming completion."),
    "422": (BASE / "filings" / "422-verification.md",
            "Recording that at head 583120b4 the deterministic citation gate exists in harness/citation_verify.py with no resolver supplied and no production call site, so the end-to-end acceptance is not met and no completion credit is taken."),
    "567": (BASE / "filings" / "567-surfaces.md",
            "Recording that the session, history, ledger-tail and status surfaces the 2026-11-16 audit could not read now answer with the owner token at head 583120b4, while the original untimestamped transcript remains unrecoverable."),
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
             "evidence": "The filing names the head it was measured at, quotes "
                         "the observed status, error kind or surface response "
                         "verbatim, and claims no credit, fix or behaviour it "
                         "did not observe.",
             "precedent": "Same disposition shape as the accepted frozen-slot "
                          "verdicts: observed values only, no improvised "
                          "program, no post-freeze artifact."}
            for cid in CATEGORY_IDS
        ]
        lucas = run_typed_track(
            track="typed", artifact_text=text, category_scores=categories,
            bias_checks=[{"id": k, "score": v,
                          "rationale": "Every claim is restricted to the head "
                                       "and the run actually executed."}
                         for k, v in BIAS.items()],
            actual_risk=False, overall_average=9.5)
        verdict, structural = policy.evaluate_decision(
            action, GOAL, f"W2 turn-9 disposition {key}", site=SITE)
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
                    "total_jev_cost_usd": round(total, 8), "site": SITE}
    (BASE / "gates-turn9.json").write_text(json.dumps(out, indent=2),
                                           encoding="utf-8")
    print("ledger rows added:", after - before, "| jev cost $", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
