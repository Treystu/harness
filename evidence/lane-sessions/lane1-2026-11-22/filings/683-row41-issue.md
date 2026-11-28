# Keep individual reports' shares out of single-intake reach

Part of #683, finding 41 (P1). Verified against `main` `8fc28a0e` on
2026-11-25: still present.

This filing asks for the smallest containment change, not a new protocol. The
larger question of whether shares should be held by independent operators is
an owner architecture decision and is named below as out of scope, so a lane
does not decide it by accident.

## Current evidence

harness/public_share.py:776 validate_submission reconstructs the full vector with open_payload(shares), and :834 PublicPublisher.accept stores payload['shares'] under the contributor token, so the receiving service reads each individual statistic before any publication floor.

One payload therefore carries every share needed to open that contributor's
cost, usage and outcome totals, and the publisher keeps them per token.

## What this issue asks for

Intake must not persist material from which one contributor's statistics can
be opened. Keep the wire protocol and the voucher checks unchanged. At accept
time, record the contributor token, the commitment and the model, and either
discard the share vector or hold only an undecryptable fragment. Reconstruct a
cohort aggregate only at seal time, and only for a cell that clears the floor.

## Not decided here

Whether shares are delivered to independent holders instead of one intake is a
design change for the owner. This issue does not implement that design and does
not claim the protocol is secure aggregation until the owner rules on it.

## Acceptance

- A hermetic test submits one report and asserts the accepted record cannot
  open that report's statistics.
- A hermetic test seals a cohort at or above the floor and gets the same
  published figures and receipts as today.
- A hermetic test asserts a below-floor cohort's values are not reconstructed.

Provenance: https://github.com/Treystu/harness/pull/619#discussion_r4621137043
