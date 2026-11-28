# Connect the canary due predicate to a production execution loop

Part of #683, finding 39 (P2). Verified against `main`
`8fc28a0e` on 2026-11-25: still present.

## Current evidence

harness/ledger_canary.py:145 defines should_run_canaries (:99 run_canaries); tree-wide the only non-test references are the manual wrapper ledger.py:453 and tests, and harness/ledger_sweep.py:97 LedgerSweeper only calls sweep_compaction (:70). No startup path, scheduler or service lifecycle invokes the due predicate or the probes.

## The finding

Connect the canary due predicate to a production execution loop

On a fresh install or an idle running service, none of the advertised startup, daily, or six-hour-staleness triggers actually executes canaries. Repository-wide searches for `should_run_canaries`, `run_canaries`, and `LedgerSweeper` show only definitions, the ledger's manual wrapper, and tests; no application lifecycle or scheduler calls this predicate or runs the probes automatically. Consequently normal operation never accrues the promised health evidence. Wire the due check and probe execution into the relevant startup and periodic lifecycle.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `harness/ledger_canary.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/618#discussion_r4617725806
