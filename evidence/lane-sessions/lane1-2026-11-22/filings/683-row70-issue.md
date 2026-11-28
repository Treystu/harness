# Distinguish post-dispatch overruns from calls refused before dispatch

Part of #683, finding 70 (P2). Verified against `main`
`8fc28a0e` on 2026-11-25: still present.

## Current evidence

`harness/spend.py:1103-1104` still calls `_record_refusal(site="record_actual", ...)` when an already-billed response pushes `spent + outstanding + actual` over the ceiling, and `_record_refusal` (`:418`) hardcodes `"outcome": REFUSAL_OUTCOME`, which `:51-53` defines as 'the refused call's outcome: it did not run'. `record_actual` also reaches `_refuse_over_scope` (`:1122-1126`), whose refusal rows carry the same outcome. Executed, billed calls are still classified as refused before dispatch.

## The finding

Distinguish post-dispatch overruns from calls refused before dispatch

When `record_actual` rejects a billed response, `_record_refusal` still writes `outcome="refused"`, which this change defines as the call not having run. These calls have already run: `tests/test_spend.py::test_unreserved_inflight_overspend_documented` exercises this case, and `JevPolicy._account` can even retain the paid result after the accounting rejection. Task-scope checks reached from `record_actual` or `reconcile` have the same problem. Distinguish accounting overruns from pre-dispatch refusals so the new trace does not classify executed, billed calls as calls prevented by the ceiling.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `harness/spend.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/642#discussion_r4636128920
