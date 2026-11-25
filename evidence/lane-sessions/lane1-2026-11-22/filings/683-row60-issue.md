# Record paid BYOK attempts in the routing trace

Part of #683, finding 60 (P2). Verified against `main`
`8fc28a0e` on 2026-11-25: still present.

## Current evidence

harness/apply_policy.py:470-483 the paid-BYOK branch appends `model_result` directly and rotates without calling `_record_billable`, whose call at :148 is the only `_record_attempt` site; that attempt is absent from the routing trace.

## The finding

Record paid BYOK attempts in the routing trace

When a paid candidate returns `usage.is_byok=true`, `_attempt_round` records its `model_result` directly and rotates without calling `_record_billable`. Placing the only attempt-trace hook here therefore omits that actual attempt: a reproduced primary-BYOK → fallback-success run contains two `model_result` rows but only the fallback's `routing.attempt`. Consumers reconstructing attempts from the new trace consequently treat the primary as untried and calculate incorrect per-candidate histories. Emit an attempt row on the paid-BYOK branch as well, preserving its existing billing behavior.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `harness/apply_policy.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/633#discussion_r4637191190
