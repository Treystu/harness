# Include the binding scope's budget in scope-refusal events

Part of #683, finding 71 (P2). Verified against `main`
`8fc28a0e` on 2026-11-25: still present.

## Current evidence

`harness/spend.py:406-411` builds every refusal envelope from `dual_budget_envelope(self.max_cost, self.spent, self.terminal_reserve, ...)` -- the global governor -- and `:436-437` adds only `"scope": str(scope)`. `_refuse_over_scope` (`:453-458`) passes `requested=amount, scope=target.label` and nothing else, so a task-allowance refusal still records the session ceiling and balances with no scope allowance, scope spent or scope outstanding.

## The finding

Include the binding scope's budget in scope-refusal events

When a task allowance rather than the session ceiling rejects a call, only the scope label reaches `_record_refusal`; its structured envelope always contains the global governor's numbers. For example, a $0.02 reservation rejected by a $0.01 task scope under a $1 session records `requested=0.02`, `phase_ceiling=1.0`, and `phase_remaining=1.0`, with no structured scope allowance or scope balances. Consumers replaying or classifying the refusal therefore see an amount that fits the recorded envelope and must parse the rounded human-readable reason to recover the actual constraint. Include the rejecting target's allowance, spent, and outstanding balances in the event.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `harness/spend.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/642#discussion_r4636128936
