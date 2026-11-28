# Preserve the configured pool before capability ordering

Part of #683, finding 59 (P2). Verified against `main`
`8fc28a0e` on 2026-11-25: still present.

## Current evidence

harness/apply.py:175 sets `ordered, profiles = ordered_pool(...)`, so `req.ordered` is already the ranked output. harness/apply_policy.py:369 passes it as `pool_order` and :79-84 records it as `configured_pool`, which therefore cannot show which candidates capability ordering removed.

## The finding

Preserve the configured pool before capability ordering

When capability-informed routing is active, `_candidate_models` passes `req.ordered` as `pool_order`, but `_prepare` has already populated that value through `_route_pool` and `ordered_pool`, which reorder candidates and remove catalog-stale IDs. Consequently, `configured_pool` records the ranked output rather than the original input, and `dropped` cannot report candidates removed during capability ordering. This loses the denominator needed to compare routing policies on the informed-routing path. Preserve the original request/configured pool before calling the ordering mechanism and use that snapshot here.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `harness/apply_policy.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/633#discussion_r4637191185
