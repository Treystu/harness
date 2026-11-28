# Record paid attempts that exceed the actual task budget

Part of #683, finding 58 (P2). Verified against `main`
`8fc28a0e` on 2026-11-25: still present.

## Current evidence

harness/escalation.py:389-394 calls `governor.record_actual` and then raises `HarnessError` when actual spend exceeds `task_max_cost`; no `_record_attempt` call happens before the raise, so an over-budget paid rung leaves no attempt trace.

## The finding

Record paid attempts that exceed the actual task budget

When a rung's reported cost pushes spending over `task_max_cost`, the check at lines 391–394 raises before any `_record_attempt` call. Unlike a preflight refusal, this rung has already called the provider and incurred cost, but it disappears from the new attempt history. Reproducing with a $0.10 task budget and a $0.20 response produces zero trace writes. This leaves the replay/audit population missing budget-overrun attempts and their costs; record a non-passing attempt before propagating that budget error.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `harness/escalation.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/630#discussion_r4629702101
