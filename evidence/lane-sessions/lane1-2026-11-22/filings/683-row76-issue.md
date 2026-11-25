# Preserve billed spend and unknown liability on cancellation

Part of #683, finding 76 (P1). Verified against `main` `8fc28a0e` on
2026-11-25: still present.

## Method

Code read of the named path at `8fc28a0e`: `harness/jev_policy.py` and the code it calls,
on 2026-11-25. No repository code changed in that act, so this is a read
of the shipped path, not a run and not a test.

## Result

harness/jev_policy.py:2022-2024 catches `(ToolCancelled, ProviderUsageUnknown)` in `evaluate_result_relevance` with `self._release(reservation)`, and `_release` is documented at :665-667 as settling the reservation at zero. `_settle_cancelled` exists and is used by `_release_reservation` at :582-591, but not on this path, so a known charge is dropped and unknown liability is not retained.

## The finding

If the reviewer raises `ProviderUsageUnknown` or a post-dispatch `ToolCancelled`, `_release()` reconciles its reservation at zero, losing any `known_cost` and releasing money that may already have been billed. Reproducing either exception leaves the governor with zero spent, outstanding, and unknown liability, allowing subsequent calls to reuse that budget. Use `_settle_cancelled(reservation, exc)`, as the other evaluation methods do, to book known charges and retain unknown liability.

## Scope of this issue

Use `_settle_cancelled(reservation, exc)` on the reviewer cancellation path, as the other evaluation methods do, so a known charge is booked and unknown liability is retained. No other path in `evaluate_result_relevance` changes.

## Not claimed

- Not claimed: that the reviewer outage handling changes; a cancellation still propagates to the caller.
- Not claimed: that unknown liability blocks later calls forever; it is retained, subject to the existing reconciliation.
- Not claimed: any behaviour for the spend-limit path, which already routes through `_release_after_provider_limit`.

## Acceptance

- `evaluate_result_relevance` books known cost and retains unknown liability when it raises ProviderUsageUnknown or a post-dispatch ToolCancelled.
- The governor spent, outstanding and unknown figures reflect that liability after the raise.
- A hermetic test drives each exception through the reviewer and asserts the governor figures.

Provenance: https://github.com/Treystu/harness/pull/665#discussion_r4658103557

