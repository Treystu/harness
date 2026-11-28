# Read the decision signals using their returned field names

Part of #683, finding 63 (P2). Verified against `main`
`8fc28a0e` on 2026-11-25: still present.

## Current evidence

evidence/lane-sessions/sergeant-2026-11-19/gates_620.py:77-79 serializes `verdict.get("lead")`, `verdict.get("advanced")`, `verdict.get("destructive")`, but `harness/jev_packs.py:2641-2652` (returned verbatim by `harness/jev_policy.py:1730-1732`) composes `disposition_lead`, `advances_goal` and `is_destructive`. `evidence/lane-sessions/sergeant-2026-11-19/gates-620.json` records all three as null under `product_jev`.

## The finding

Read the decision signals using their returned field names

`evaluate_decision` returns the composed fields `disposition_lead`, `advances_goal` and `is_destructive` (see `harness/jev_packs.py::compose_decision_verdict`), not `lead`, `advanced` and `destructive`. These lookups therefore silently discard all three signals, which is visible as three null values in `gates-620.json` and the other new receipts. Use the actual returned keys when serializing and printing the signals; otherwise reviewers cannot inspect the probabilities and lead underlying the recorded investigate/escalate decisions without finding the separate ledger.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `evidence/lane-sessions/sergeant-2026-11-19/gates_620.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/634#discussion_r4646946218
