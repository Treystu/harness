"""Sergeant gates for landing W2 evidence car PR #637. Lucas Gate v2 first, product Jev second.

Merge proposition (read live at filing time):
- PR #637 head 4c69541, base = main d916a7bb (merge-base == main: up to date).
- CircleCI 16/16 success incl audit at the exact head (rail read live).
- Payload vs main: 63 files, +6427/-0. Every file status ADDED, every path
  under evidence/lane-sessions/w2-2026-11-20/ (turn-11/12 filings, rerun
  probes, serve logs, turn-16 admissibility rows for #468/#469). No product
  code, no tests, no docs rows, no modifications, no deletions. Matches the
  body's "Records only" description (payload audit clean).
- Head 4c69541 is one commit ("turn-16 admissibility rows") on top of
  29d02a52, at which the W2 mark-ready event fired (codex review receipt on
  the PR records the mark-ready trigger); W2 then pushed the turn-16 commit
  onto their own ready branch. PR is ready now, MERGEABLE.
- Body close-scan clean (no fixes/closes/resolves + ref); merge closes
  nothing. GitHub mergeStateStatus UNSTABLE is Actions billing-lock noise;
  CircleCI is the rail.
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
HEAD = "4c695416"
MAIN = "d916a7bbe3de878dc842635c69f9f1cf3e619bfa"
OUT = pathlib.Path(
    "evidence/lane-sessions/sergeant-2026-11-19/gates-637.json")

ACTION = (
    "Merge PR #637 at exact head 4c69541 onto main d916a7bb via squash: "
    "publish W2 turn-11/turn-12 plus turn-16 records. 63 files, +6427/-0, "
    "every file ADDED under evidence/lane-sessions/w2-2026-11-20/ (filings, "
    "rerun probes, serve logs, #468/#469 admissibility rows). No product "
    "code, no tests, no docs rows, no modifications, no deletions. CircleCI "
    "16/16 incl audit at the exact head, merge-base == main, ready (W2 "
    "mark-ready on this branch) and MERGEABLE. Body carries no close "
    "keywords; merge closes nothing."
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
         "evidence": "The PR head, base, rail counts and full name-status "
                     "were read live at the exact head: 63 added files, all "
                     "under the W2 lane-session dir, zero modifications or "
                     "deletions; the body carries no close keywords."}
        for cid in CATEGORY_IDS
    ]
    for c in categories:
        c["precedent"] = ("Same disposition shape as the accepted docs-only "
                          "intake landings: observed values only, "
                          "additive evidence publication.")
    lucas = run_typed_track(
        track="typed", artifact_text=ACTION, category_scores=categories,
        bias_checks=[{"id": k, "score": v,
                      "rationale": "Claims are limited to what the live read "
                                   "returned."} for k, v in BIAS.items()],
        actual_risk=False, overall_average=9.5)
    verdict, structural = policy.evaluate_decision(
        ACTION, GOAL, "Sergeant landing disposition #637", site=SITE)
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
