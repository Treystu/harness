# proofs/adjudication — Tier 1 Lean verification (pilot)

Lean 4 model of `harness/adjudication.py` (adjudication contract v1, #453),
adopted 2026-11-26 under gate receipts recorded in the PR description.

Run the gate (build + frozen statements + token scan + full axiom audit):
    bash lean_ci.sh
Kernel differential vs the real Python (313 cases, `decide`-checked):
    lake env lean DiffTest.lean

Rules of this folder:
- Theorem statements are FROZEN (FROZEN.txt). Changing one is a gate/rulebook
  change — re-gate it; never edit in passing (python3 frozen.py --freeze is
  the deliberate, reviewed act).
- No Mathlib. No project `axiom`s. No `sorry`/`admit`/`sorryAx`/`native_decide`.
- COVERAGE.tsv states what is proved and what is not. Keep it truthful.

Tier 0 (every merge) lives in tools/proofgate/: a deterministic receipt
checker over commit ranges — head-bound, census-complete, evidence =
sha256 of file content at the checked head.
