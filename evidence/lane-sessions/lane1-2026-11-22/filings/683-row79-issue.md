# Bind the provider-call cache key to the rerouted request

Part of #683, finding 79 (P1). Verified against `main` `8fc28a0e` on
2026-11-25: still present. This issue also covers finding 83, the
same unbound route-review key under a changed plan.

## Method

Code read of the named path at `8fc28a0e`: `harness/hourglass_lifecycle.py` and the code it calls,
on 2026-11-25. No repository code changed in that act, so this is a read
of the shipped path, not a run and not a test.

## Result

harness/hourglass_lifecycle.py:939-945 calls `provider_call` with the key `lifecycle_state["request_id"] + ":chat-route-review"`, and harness/lifecycle.py:403-410 returns the cached completed result for that id before invoking. The reuse predicate at :572-606 does reject a changed request, but rejecting it does not change the call id, so a persisted lifecycle that already holds a completed route receipt returns the old decision; `route_request_prompt` is then overwritten at :969 with the new prompt.

## The finding

When a real interrupted lifecycle contains a completed `:chat-route-review` provider receipt, rejecting `route_preflight` here still does not trigger a fresh review: the subsequent `self.lifecycle.provider_call` uses the unchanged request ID and call key, and `LifecycleCoordinator.provider_call` returns that receipt's cached result without invoking `evaluate_route_once`. I reproduced a changed bicycle-explanation request retaining the old native web-research route with zero fresh route evaluations; this change then records the new prompt in `route_request_prompt`, incorrectly certifying the stale decision as belonging to it. Use a request-bound provider-call key when rerouting, and cover a persisted lifecycle containing the completed route receipt rather than only the synthetic payload used by the new tests.

## Scope of this issue

Bind the route-review provider-call identity to the binding the judgment was made under: the request generation and, when a plan is in play, the plan hash. A rejected reuse predicate must produce a fresh review, not the cached decision. The plan half is the same defect the census files separately as row 83, so this issue owns both and no second issue is filed for it.

## Not claimed

- Not claimed: that an unchanged continuation must pay for a second review; reuse for an identical request and plan stays.
- Not claimed: that `evaluate_request_workflow` changes.
- Not claimed: any behaviour for a checkpoint with no completed route receipt, which already reviews fresh.

## Acceptance

- A changed request against a persisted lifecycle containing a completed route-review receipt runs a fresh route evaluation.
- A changed plan does the same, and the saved route preflight is recorded under the plan that was actually judged.
- A hermetic test persists a lifecycle with a completed route receipt and resumes with a different request, asserting two evaluations.

Provenance: https://github.com/Treystu/harness/pull/667#discussion_r4658634827

