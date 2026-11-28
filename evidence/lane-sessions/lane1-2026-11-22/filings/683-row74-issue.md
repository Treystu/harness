# Invalidate provider receipts when restarting with new context

Part of #683, finding 74 (P1). Verified against `main` `8fc28a0e` on
2026-11-25: still present.

## Method

Code read of the named path at `8fc28a0e`: `harness/hourglass_lifecycle.py` and the code it calls,
on 2026-11-25. No repository code changed in that act, so this is a read
of the shipped path, not a run and not a test.

## Result

harness/hourglass_lifecycle.py:1259-1262 keys the answer receipt as `lifecycle_state["request_id"] + f":chat-answer:{round_no}"`, and harness/lifecycle.py:403-410 returns the cached `result` for any completed call id before invoking. The resumed lifecycle keeps its original `request_id` (harness/lifecycle.py:140-151 adopts the same state), and nothing in hourglass_lifecycle.py clears `usage.provider_calls`, so a changed instruction that rebuilds context still replays the round-1 answer.

## The finding

When an answer completes but its Jev review is interrupted, resuming with a changed instruction now rebuilds context and clears the checkpoint answer, but retains the lifecycle's completed provider receipts. Restarting at round 1 then uses the same `request_id:chat-answer:1` key, so `LifecycleCoordinator.provider_call()` returns the old answer without invoking the answer provider. I reproduced this through `run_prompt()` with an apples request followed by `continue with instead explain oranges`: context was gathered twice, but the answer provider ran only once and the original answer was returned. Namespace answer/review receipts by the new context/request generation when invalidating reuse, while preserving accounting history.

## Scope of this issue

Namespace the answer and review receipts by the context/request generation that produced them when a resume invalidates the checkpoint context, so round 1 of the new generation dispatches instead of replaying. Accounting history stays: the earlier receipts remain in the lifecycle usage and in known and unknown cost.

## Not claimed

- Not claimed: that every provider call must be invalidated. Route review, Jev review and the answer each decide reuse separately; this row is the answer receipt.
- Not claimed: that the old answer cost should be released. It was billed and stays billed.
- Not claimed: a tested reproducer in this filing; the finding own `run_prompt()` sequence is the reproduction to encode.

## Acceptance

- A resume whose instruction changes the checkpoint request generation invokes the answer provider again for round 1.
- The previous generation receipts remain visible in the lifecycle accounting.
- A hermetic test runs the apples request, interrupts the review, and resumes with the changed instruction, asserting two provider invocations.

Provenance: https://github.com/Treystu/harness/pull/648#discussion_r4648680389

