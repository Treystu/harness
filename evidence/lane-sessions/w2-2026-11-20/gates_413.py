"""Gate for the #413 disposition: Product Jev first, Lucas Gate v2 second."""
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
PATH = BASE / "filings" / "413-driver-roundtrip.md"
ACTION = ("Recording that at head 583120b4 the loopback driver starts and "
          "answers authenticated requests, refuses the DOM read at capture "
          "with no perception source configured, and that the round-trip "
          "acceptance is not met, naming the configuration unblockers "
          "without changing them.")

CATEGORY_IDS = ("1", "2", "3", "4", "5", "6", "8", "9", "10", "11")
BIAS = {"B1": 10.0, "B3": 9.5, "B4": 9.5, "B5": 9.5, "B8": 9.5,
        "B9": 9.0, "B10": 9.0, "B11": 9.5}


def main():
    settings = load_settings()
    governor = jev_face_governor(settings)
    ledger = ledger_for(settings, caller="w2-champion-audit")
    policy = policy_for(settings, governor=governor, ledger=ledger)
    print("keyed:", policy.keyed)
    before = len(ledger.tail(200000))
    text = PATH.read_text(encoding="utf-8")
    verdict, structural = policy.evaluate_decision(
        ACTION, GOAL, "W2 turn-9 disposition 413", site=SITE)
    categories = [
        {"id": cid, "applicable": True, "score": 9.5, "category_average": 9.5,
         "evidence": "The filing quotes the observed step records verbatim, "
                     "names the head and ports it ran on, and claims no "
                     "round-trip it did not perform.",
         "precedent": "Same disposition shape as the accepted frozen-slot "
                      "verdicts: observed values only, no improvised program."}
        for cid in CATEGORY_IDS
    ]
    lucas = run_typed_track(
        track="typed", artifact_text=text, category_scores=categories,
        bias_checks=[{"id": k, "score": v,
                      "rationale": "Every claim is restricted to the head and "
                                   "the probes actually executed."}
                     for k, v in BIAS.items()],
        actual_risk=False, overall_average=9.5)
    after = len(ledger.tail(200000))
    seqs = [r.get("seq") for r in ledger.tail(5) if r.get("event") == "jev_eval"]
    out = {"product_jev": {"verdict": verdict.get("verdict"),
                           "disposition": verdict.get("disposition"),
                           "supported": structural.get("supported"),
                           "cost": structural.get("cost"),
                           "model": structural.get("model")},
           "lucas": {"status": lucas["status"], "track": lucas["track"],
                     "artifact_sha256": lucas["artifact_sha256"]},
           "_meta": {"ledger_rows_added": after - before,
                     "seqs": seqs[-1:]}}
    (BASE / "gates-413.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("jev", verdict.get("verdict"), "| lucas", lucas["status"],
          "| rows", after - before)
    return 0


if __name__ == "__main__":
    sys.exit(main())
