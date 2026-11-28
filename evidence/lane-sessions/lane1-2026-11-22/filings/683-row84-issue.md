# Preserve the saved approval when resuming without a new one

Part of #683, finding 84 (P2). Verified against `main` `8fc28a0e` on
2026-11-25: still present.

## Method

Code read of the named path at `8fc28a0e`: `harness/hourglass_lifecycle.py` and the code it calls,
on 2026-11-25. No repository code changed in that act, so this is a read
of the shipped path, not a run and not a test.

## Result

harness/hourglass_lifecycle.py:1061-1066 writes `checkpoint["plan_approval"]` from `plan_approval` alone, falling back to `{"decision": "", "native": False, ...}` when the caller supplied none. A resume that re-supplies the identical plan without a replacement approval leaves `plan_approval` as `None` whenever `saved_plan_approval` declines to rebuild it, so the recorded receipt is replaced by the empty non-native dict and the next continuation fails `plan-receipt-not-native` at :638-642.

## The finding

When a caller resumes with the same `research_plan` and omits the optional `plan_approval`, the reuse predicate correctly accepts the saved native receipt, but this assignment then replaces it with empty fields and `native=False`. The next continuation consequently rejects the unchanged plan with `plan-receipt-not-native`, losing the approval evidence that justified reuse. Preserve the existing receipt when reusing the same plan without a replacement approval instead of serializing `None` over it.

## Scope of this issue

When the live request carries the identical plan and no replacement approval, keep the receipt the checkpoint already holds instead of serializing an empty non-native one. A receipt the predicate rejected is not preserved as approval evidence.

## Not claimed

- Not claimed: that a rejection should be preserved as if it were an acceptance; only a receipt that already justified reuse survives.
- Not claimed: that `saved_plan_approval` gets looser; its strict rebuild is what keeps adoption honest.
- Not claimed: any behaviour for a non-resume call, which has no saved receipt to preserve.

## Acceptance

- Resuming with the same plan and no plan approval leaves the recorded receipt intact.
- The next continuation of that unchanged plan still passes the route binding instead of failing plan-receipt-not-native.
- A hermetic test resumes twice and asserts the second continuation reuses the original receipt.

Provenance: https://github.com/Treystu/harness/pull/671#discussion_r4659204094

