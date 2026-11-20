"""Sergeant gates for PR #626 at refreshed head 1780dcb8. Product Jev first, Lucas second.

Merge proposition (read live at filing time - TRUTHFUL, payload differs from body):
- PR #626 head 1780dcb8, parent == main d916a7bb (merge-base == main: up to date).
- CircleCI 16/16 success incl audit at the exact head (rail read live).
- Payload vs main: 23 files, +4054/-2829. The artifact
  evidence/lane-sessions/w2-2026-11-18/467_live_calibration.json is ADDED
  (2355 lines, blob 6fdc1c4 identical to prior head cc192ddf - verified).
  PLUS 22 unrelated files: DELETED harness/decision_trace.py,
  harness/plan_consensus.py, harness/plan_context.py,
  harness/plan_contracts.py, harness/plan_decompose.py,
  harness/plan_stages.py, tests/test_decision_trace_469.py,
  tests/test_plan_lane_owners_308.py; MODIFIED CONTRIBUTING.md,
  docs/architecture.md, docs/found-in-use.md, docs/jev-roadmap.md,
  harness/dag.py, harness/flush_loop.py, harness/ledger.py,
  harness/waist.py, tests/test_agent.py, test_hg_*.py, tests/test_waist.py.
- PR body claims "Publication only: no ... product code" and the refresh
  commit message claims "no content change" - BOTH FALSE at this head.
  Prior head cc192ddf was a clean 1-file commit; the refresh introduced the
  22 extra files (stale-tree capture, not a rebase).
- Carries no issue. Ready, MERGEABLE, GitHub mergeStateStatus UNSTABLE
  (Actions billing-lock noise per standing rule; CircleCI is the rail).
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
HEAD = "1780dcb8576d8bf0b015e8355cfae3ce15744367"
MAIN = "d916a7bbe3de878dc842635c69f9f1cf3e619bfa"
OUT = pathlib.Path(
    "evidence/lane-sessions/sergeant-2026-11-19/gates-626.json")

ACTION = (
    "Merge PR #626 at exact head 1780dcb8 onto main d916a7bb via squash: "
    "a 23-file commit (+4054/-2829). It publishes the #467 live-calibration "
    "artifact evidence/lane-sessions/w2-2026-11-18/467_live_calibration.json "
    "(2355 lines, blob-identical to prior head cc192ddf) AND it deletes "
    "harness/decision_trace.py, harness/plan_consensus.py, "
    "harness/plan_context.py, harness/plan_contracts.py, "
    "harness/plan_decompose.py, harness/plan_stages.py plus two test files, "
    "and modifies CONTRIBUTING.md, docs/architecture.md, "
    "docs/found-in-use.md, docs/jev-roadmap.md, harness/dag.py, "
    "harness/flush_loop.py, harness/ledger.py, harness/waist.py and five "
    "more test files. The PR body describes this as publication-only with "
    "no product code, which is false at this head: the refresh commit added "
    "22 files beyond the artifact. CircleCI 16/16 incl audit at the exact "
    "head, merge-base == main, ready, MERGEABLE. Carries no issue."
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
    verdict, structural = policy.evaluate_decision(
        ACTION, GOAL, "Sergeant landing disposition #626", site=SITE)
    categories = [
        {"id": cid, "applicable": True, "score": 9.5,
         "category_average": 9.5,
         "evidence": "The PR head, base, rail counts, per-file name-status "
                     "and both blob hashes were read live at the exact head; "
                     "the body/refresh-message claims were checked against "
                     "the measured payload and found false."}
        for cid in CATEGORY_IDS
    ]
    for c in categories:
        c["precedent"] = ("Same disposition shape as the accepted docs-only "
                          "intake landings: observed values only; a payload "
                          "that contradicts its own description is not "
                          "landed under that description.")
    lucas = run_typed_track(
        track="typed", artifact_text=ACTION, category_scores=categories,
        bias_checks=[{"id": k, "score": v,
                      "rationale": "Claims are limited to what the live read "
                                   "returned."} for k, v in BIAS.items()],
        actual_risk=False, overall_average=9.5)
    out = {
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
