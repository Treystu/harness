# Check receipt expiry when the caller omits now

Part of #683, finding 89 (P2). Verified against `main` `8fc28a0e` on
2026-11-25: still present.

## Method

Code read of the named path at `8fc28a0e`: `harness/research_plan.py` and the code it calls,
on 2026-11-25. No repository code changed in that act, so this is a read
of the shipped path, not a run and not a test.

## Result

harness/research_plan.py:656-658 validates a saved receipt with `now=now`, and `decide_research_plan` defaults `now` to `None` (:616-619). `_approval_check` enforces expiry only when `now is not None` (:449-451), so a matching receipt with `expires_at=1` is accepted with `reused=True` and the reviewer is never called.

## The finding

When `decide_research_plan` receives `saved_plan` without an explicit `now`, it passes the default `None` into `validate_plan`, and `_approval_check` skips expiry enforcement when `now is None`. Consequently, an otherwise matching receipt with `expires_at=1` is returned as accepted with `reused=True`, without calling the reviewer. The hourglass caller supplies a timestamp, but the newly exposed helper API does not enforce this itself. Resolve the current time when `now` is omitted before validating a saved receipt so expired consent falls through to a fresh judgment.

## Scope of this issue

Resolve the current time when the caller omits `now`, before validating a saved receipt, so an expired consent falls through to a fresh judgment instead of being adopted. A caller that supplies `now` keeps its value.

## Not claimed

- Not claimed: that `validate_plan` should invent a clock for every caller; the default resolution belongs at the decision entry that adopts saved receipts.
- Not claimed: any change to the expiry window or the consent lifetime.
- Not claimed: that a fresh judgment must be refused when consent expired; it is simply asked again.

## Acceptance

- A saved receipt whose `expires_at` has passed is not adopted, even when the caller omits `now`.
- The expired case reports `consent_stale` and proceeds to a fresh evaluation.
- A hermetic test passes a saved receipt with `expires_at=1` and no `now` and asserts the reviewer is called.

Provenance: https://github.com/Treystu/harness/pull/677#discussion_r4660171273

