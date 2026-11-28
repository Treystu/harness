# #683 batch 4 - rows 37-48 verified against main

This is a disposition comment for the #683 tracker. It closes nothing and takes
no completion credit.

## Method

Each row was checked by reading the exact code path the finding names in
`origin/main` at `8fc28a0e`. The citations below are line numbers in that
revision, read on 2026-11-25. A row is FIXED only when the shipped code now does
what the finding asked; it is STILL PRESENT when the path the finding describes
is still reachable at the named line. No repository code changed in this act,
so no new test was run: every verdict is a code read, and the FIXED verdict for
row 48 is a read of the shipped separation, not a claim that a regression test
now pins it.

## Result: 1 FIXED, 11 STILL PRESENT, 0 NOT APPLICABLE

| Row | File | Finding | Verdict |
| --- | --- | --- | --- |
| 37 | harness/ledger.py | Prevent checkpoint appends from recursively compacting their | STILL PRESENT |
| 38 | harness/ledger.py | Refresh citation pins under synchronization before compactio | STILL PRESENT |
| 39 | harness/ledger_canary.py | Connect the canary due predicate to a production execution l | STILL PRESENT |
| 40 | harness/public_share.py | Enforce eligibility before issuing a token voucher | STILL PRESENT |
| 41 | harness/public_share.py | Keep individual reports' shares with independent holders | STILL PRESENT |
| 42 | harness/public_share.py | Apply the publication floor separately to each metric | STILL PRESENT |
| 43 | harness/public_share.py | Authenticate the evidence claim before accepting statistics | STILL PRESENT |
| 44 | harness/public_share.py | Count actual terminal failure events in the success denomina | STILL PRESENT |
| 45 | harness/public_share.py | Recheck the queued report's consent period before retrying | STILL PRESENT |
| 46 | tests/test_local_fit_optional_ci_311.py | Check tracked fixture files rather than local directory exis | STILL PRESENT |
| 47 | docs/jev-roadmap.md | Refresh the authoritative mirror instead of adding a second  | STILL PRESENT |
| 48 | driver_core/bridge_battery.py | Isolate hermetic probes from the running hand's ledger | FIXED |

## The fixed row

- **48** `driver_core/bridge_battery.py` - the requested separation is present.
  `run_battery` (:452-466) creates a scratch `TemporaryDirectory` for a live run
  and passes `hermetic_root` to probes 2-6, while probe 1 keeps the shared root.
  The hermetic probes no longer post into or poll the running hand's ledger.

## The still-present rows

- **37** `harness/ledger.py` - `append()` (:499) rotates and then calls
  `sweep_compaction()` synchronously at the end of the same call.
  `_compact_old_segment` (:417) hands `compact_segment` an
  `append_checkpoint` that is `self.append` (:423). No reentrancy guard exists,
  so a checkpoint append that rotates re-enters compaction before the outer
  `compact_segment` has replaced its source file.
- **38** `harness/ledger.py` - `citation_pins` is filled at load (:77) and by
  this instance's own `pin_citation` (:444). `_compact_old_segment` passes that
  instance-local set (:433), so a citation committed by a second open ledger
  instance is invisible and its row remains eligible for deletion.
- **39** `harness/ledger_canary.py` - `should_run_canaries` (:145) and
  `run_canaries` (:99) have no production caller. The only non-test references
  are the manual wrapper `ledger.py:453`, and `LedgerSweeper`
  (`ledger_sweep.py:97`) tick calls only `sweep_compaction` (:70). No startup
  path or service lifecycle runs the due predicate.
- **40** `harness/public_share.py` - `voucher()` (:594) HMACs any caller-supplied
  string. It checks no credential, model or round, and the token is computed
  client-side by `eligibility_token` (:600) inside `build_report` (:687), so a
  voucher for an arbitrary token verifies.
- **41** `harness/public_share.py` - `validate_submission` reconstructs the whole
  vector with `open_payload(shares)` (:776), and `PublicPublisher.accept`
  stores `payload["shares"]` under the contributor token (:834). Intake
  therefore reads each individual statistic before any publication floor.
- **42** `harness/public_share.py` - `seal` (:864-866) sums one totals dict
  across all contributions and passes `len(contributions)` as `operators`
  (:830) to `_figures`, whose per-metric denominators (:846-852) never re-count
  the contributors that recorded that observation.
- **43** `harness/public_share.py` - the only evidence check is
  `chain_verified is True` (:740), a boolean `build_report` copies from its own
  local claim (:676); `evidence_digest` is checked for hex format only (:745).
  Replacing the statistics with a recomputed commitment and `stats_digest`
  leaves no check to fail, and no bounds test stops successes exceeding tasks.
- **44** `harness/public_share.py` - a task is counted only for event
  `complete` with status ok, failed or error (:465-471).
  `harness/apply_gate.py:346-349` records a real terminal failure as event
  `abort` with reason `verify rounds exhausted`, so failed runs keep their
  model-call costs and leave the task denominator.
- **45** `harness/public_share.py` - `upload_pending` (:387-419) rechecks only
  `policy["share"]` and the transport. Unlike `handoff` (:362-366) it never
  compares the queued report's `proof.consent_period` with the current period
  before sending.
- **46** `tests/test_local_fit_optional_ci_311.py` - :246 asserts that
  `(ROOT / "audits" / "scmessenger" / "_runs").is_dir()` is false, so a
  legitimate gitignored local artifact directory fails the default suite. Only
  the keep-file check (:247-248) reads tracked state.
- **47** `docs/jev-roadmap.md` - :220 and :255 still label #311 and #407 OPEN
  inside the retired `REGISTER_MIRROR`, whose own header (:25-26) still claims
  it is the live count and order; `AGENTS.md:23-33` still generates the 60-open
  mission pointer against that mirror instead of the 2026-11-19 register.

Machine-readable: `evidence/lane-sessions/lane1-2026-11-22/683-batch4.json`,
where each row carries its verdict, evidence, finding body and discussion url.

## Running totals for #683

Rows 1-48 of 89: **13 FIXED, 35 STILL PRESENT, 0 NOT APPLICABLE**, 41 not yet
verified. The tracker is not closeable on this subset.

## Not claimed

No issue is closed here. No row is credited as complete on the strength of this
comment. Row 48's cure is asserted from the shipped code read above; a
regression test that pins it is not part of this filing, and that gap is stated
rather than hidden.
