# Carry reviewer costs back to the request lifecycle

Part of #683, finding 78 (P2). Verified against `main` `8fc28a0e` on
2026-11-25: still present.

## Method

Code read of the named path at `8fc28a0e`: `harness/web.py` and the code it calls,
on 2026-11-25. No repository code changed in that act, so this is a read
of the shipped path, not a run and not a test.

## Result

harness/web.py:798-801 keeps only `structural.get("results")` (read at :812); `structural['cost']` is never returned, and the function's only result is the filtered source list. Its caller, harness/conversation_lifecycle.py:588-589, returns that list alone, so a billed relevance review never reaches conversation result cost or the hourglass `total_cost`/checkpoint `known_cost`.

## The finding

For a billed relevance review, the policy settles the charge in the governor, but this function discards both the evaluation result and `structural['cost']`, returning only sources. Consequently, neither conversation result costs nor the hourglass `total_cost` and checkpoint `known_cost` include this new provider call. Besides underreporting spend, an hourglass continuation reconstructs its governor from that incomplete checkpoint and regains budget already spent on retrieval review. Return and accumulate the review receipt alongside the sources, including billed outage responses.

## Scope of this issue

Return the review receipt beside the sources and accumulate it into the caller cost accounting, including billed outage responses. The sources list stays the shape every consumer already reads; the cost travels with it.

## Not claimed

- Not claimed: that the reviewer settlement changes; it already books the charge in the governor. The gap is that the request lifecycle never learns it.
- Not claimed: a schema for every retrieval result; only the review receipt cost is carried.
- Not claimed: that the hourglass continuation is the only consumer; conversation result cost is the other.

## Acceptance

- A billed relevance review contributes to conversation result cost and to the hourglass total cost and checkpoint known cost.
- An hourglass continuation reconstructing its governor from the checkpoint does not regain that spend.
- A hermetic test bills one review and asserts the recorded cost.

Provenance: https://github.com/Treystu/harness/pull/665#discussion_r4658103569

