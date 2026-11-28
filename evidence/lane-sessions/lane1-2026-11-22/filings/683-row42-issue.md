# Apply the publication floor separately to each metric

Part of #683, finding 42 (P1). Verified against `main`
`8fc28a0e` on 2026-11-25: still present.

## Current evidence

harness/public_share.py:864-866 seals one totals dict across all contributions and :830 passes len(contributions) as `operators` to _figures, whose per-metric denominators (:846-852) never re-count the contributors that actually recorded that observation.

## The finding

Apply the publication floor separately to each metric

When ten operators submit reports but only one has latency observations, `seal()` passes all ten contributors as `operators`, so this check publishes that single operator's mean latency and labels its cohort as ten operators. I reproduced this with nine reports lacking `latency_ms`. Count contributors with eligible observations separately for each metric, and restrict receipt totals accordingly: the current receipt includes every statistic in every published cell, so merely suppressing the latency cell would still expose its totals through the calls receipt.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `harness/public_share.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/619#discussion_r4621137052
