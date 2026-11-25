# Handle an unrecorded trace before accessing its event ID

Part of #683, finding 54 (P2). Verified against `main`
`8fc28a0e` on 2026-11-25: still present.

## Current evidence

harness/decision_trace.py:128-134 returns `{"unrecorded": True}` with no `event_id` when the append fails and `audit_enabled` is false. `harness/cli.py:2151` reads `entry["event_id"]` outside its try block, and `record_disposition` is called without `audit_enabled`, so a failed append still raises `KeyError` instead of the JSON error and exit 2.

## The finding

Handle an unrecorded trace before accessing its event ID

When the ledger append fails, for example because the disk is full or the append lock cannot be acquired, `DecisionTrace.record()` defaults to returning an `unrecorded` result without an `event_id`. This CLI call leaves `audit_enabled=False` and then unconditionally accesses that missing field, producing an uncaught `KeyError` instead of the JSON error and exit code 2 handled above. Reproduced by making `AutonomyLedger._persist` raise `OSError`. Enable fail-closed recording for this explicitly requested write, or handle the `unrecorded` result before constructing the report.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `harness/cli.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/628#discussion_r4637150538
