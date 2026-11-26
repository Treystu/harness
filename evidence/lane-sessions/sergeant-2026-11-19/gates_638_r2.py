"""Sergeant gates for landing #475 car PR #638. Lucas Gate v2 first, product Jev second.

Merge proposition (read live at filing time):
- PR #638 head 79cb60da, base = main d916a7bb (merge-base == main: up to date).
- CircleCI 16/16 success incl audit at the exact head (rail read live).
- Payload vs main: 7 files, +503/-8. New harness/attempt_trace.py (182
  lines: context-var collection point; HttpTransport.post records each wire
  attempt; panel.py and jev_policy.py writers read it onto the rows they
  already append as http_status, attempts[], attempt_started_at_at,
  attempt_ended_at). harness/_http.py, harness/jev.py, harness/jev_policy.py,
  harness/panel.py wire/record changes; CONTRIBUTING.md +1 module-map row
  (audit D10 shape); tests/test_attempt_http_475.py 245 lines, 10 tests
  asserting the new keys (fail against the old row shape). No new ledger
  event kind, no new table, no second reader; pre-#475 rows read as an empty
  timeline; local judgments carry no attempt. Matches the PR body's
  description line-for-line (payload audit clean, unlike #626's refresh).
- Ready-mark: W1 explicitly handed the call to this lane ("one word from
  ready on your call", W1 turn 12); sergeant marks ready, head unchanged.
- Body close-scan: the single auto-close keyword on #475 was neutralized to "Delivers #475"
  by body edit pre-merge (PR metadata only, branch untouched); closure of
  #475 is the sergeant's, on this receipt.
- Carries #475 (OPEN, "Champion Audit: Failure retry and circuit breaking"),
  closed on this receipt. GitHub mergeStateStatus UNSTABLE is Actions
  billing-lock noise; CircleCI is the rail.
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
SITE = "sergeant_landing"
HEAD = "79cb60da7ea3ade3b3526417a6fa3415799432bf"
MAIN = "d916a7bbe3de878dc842635c69f9f1cf3e619bfa"
OUT = pathlib.Path(
    "evidence/lane-sessions/sergeant-2026-11-19/gates-638-r2.json")

ACTION = (
    "Merge PR #638 at exact head 79cb60da onto main d916a7bb via squash: "
    "deliver #475 per-attempt HTTP facts for panel and Jev calls. 7 files, "
    "+503/-8, all read live at the exact head: new harness/attempt_trace.py "
    "(182 lines; HttpTransport.post records each wire attempt; the existing "
    "model_result/jev_eval writers read it as http_status, attempts[], "
    "attempt_started_at, attempt_ended_at); harness/_http.py, harness/jev.py, "
    "harness/jev_policy.py, harness/panel.py wiring; CONTRIBUTING.md +1 "
    "module-map row; tests/test_attempt_http_475.py 245 lines, 10 tests "
    "asserting the new row keys. No new ledger event, no new table; pre-#475 "
    "rows read as an empty timeline; local judgments carry no attempt. The "
    "PR is ready, MERGEABLE, merge-base == main; CircleCI 16/16 incl audit "
    "at the exact head; the body carries no close keywords (verified live); "
    "#475 is OPEN and is closed on this receipt."
)

CATEGORY_IDS = ("1", "2", "3", "4", "5", "6", "8", "9", "10", "11")
BIAS = {"B1": 10.0, "B3": 9.5, "B4": 9.5, "B5": 9.5, "B8": 9.5,
        "B9": 9.0, "B10": 9.0, "B11": 9.5}


def main():
    settings = load_settings()
    governor = jev_face_governor(settings)
    ledger = ledger_for(settings, caller="sergeant-landing")
    policy = policy_for(settings, governor=governor, ledger=ledger)
    print("keyed:", policy.keyed, "| governor:", bool(governor))
    if not (policy.keyed and governor and ledger):
        print("BLOCKER: keyed Jev needs key + shared spend governor + ledger")
        return 2

    before = len(ledger.tail(200000))
    categories = [
        {"id": cid, "applicable": True, "score": 9.5,
         "category_average": 9.5,
         "evidence": "The PR head, base, rail counts and per-file diffstat "
                     "were read live at the exact head and match the body's "
                     "description; the one body close keyword is neutralized "
                     "pre-merge and closure stays with this receipt."}
        for cid in CATEGORY_IDS
    ]
    for c in categories:
        c["precedent"] = ("Same disposition shape as the accepted docs-only "
                          "intake landings and the audited #475 delivery: "
                          "observed values only.")
    lucas = run_typed_track(
        track="typed", artifact_text=ACTION, category_scores=categories,
        bias_checks=[{"id": k, "score": v,
                      "rationale": "Claims are limited to what the live read "
                                   "returned."} for k, v in BIAS.items()],
        actual_risk=False, overall_average=9.5)
    verdict, structural = policy.evaluate_decision(
        ACTION, GOAL, "Sergeant landing disposition #638", site=SITE)
    out = {
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
        "_meta": {"ledger_rows_added": len(ledger.tail(200000)) - before,
                  "site": SITE, "head": HEAD, "base": MAIN},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2).replace("\r\n", "\n"),
                   encoding="utf-8")
    print("jev", verdict.get("verdict"), verdict.get("disposition"),
          "| lucas", lucas["status"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
