# Recheck the queued report's consent period before retrying

Part of #683, finding 45 (P2). Verified against `main`
`8fc28a0e` on 2026-11-25: still present.

## Current evidence

harness/public_share.py:387-419 upload_pending() rechecks only policy['share'] and the transport; unlike handoff (:362-366) it never compares the queued report's proof.consent_period with the current period before sending.

## The finding

Recheck the queued report's consent period before retrying

If a report is queued and `enable()` starts a new consent period before the retry, `upload_pending()` sends the old-period report because it checks only whether sharing is currently enabled. I reproduced this by enabling, building and queueing a report, enabling again, and calling `upload_pending()`, which returned `sent: 1`. The direct `handoff()` path rejects this same report, and the documented contract explicitly refuses older-period queued work. Apply the period comparison here as well and discard mismatched reports before invoking the transport.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `harness/public_share.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/619#discussion_r4621137086
