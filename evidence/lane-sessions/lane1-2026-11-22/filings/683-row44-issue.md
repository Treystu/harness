# Count actual terminal failure events in the success denominator

Part of #683, finding 44 (P1). Verified against `main`
`8fc28a0e` on 2026-11-25: still present.

## Current evidence

harness/public_share.py:465-471 counts a task only for event 'complete' with status ok/failed/error, while harness/apply_gate.py:346-349 records a real terminal failure as event 'abort' reason 'verify rounds exhausted'. Failed runs keep their model_result costs but leave the task denominator.

## The finding

Count actual terminal failure events in the success denominator

For real apply runs, `ApplyGate.terminal_failure()` in `harness/apply_gate.py` records an `abort` with reason `verify rounds exhausted`, not a `complete` with status `failed` or `error`. This branch therefore excludes failed runs from the task denominator while retaining their model-call costs. An operator with both successful and failed runs can report a 100% success rate, and an operator with only failed runs cannot contribute at all. Include the existing terminal failure events, with appropriate task attribution, rather than relying on the synthetic failure shape used by the new tests.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `harness/public_share.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/619#discussion_r4621137074
