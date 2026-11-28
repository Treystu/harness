# Propagate unknown provider usage instead of treating it as an outage

Part of #683, finding 88 (P2). Verified against `main` `8fc28a0e` on
2026-11-25: still present.

## Method

Code read of the named path at `8fc28a0e`: `harness/research_plan.py` and the code it calls,
on 2026-11-25. No repository code changed in that act, so this is a read
of the shipped path, not a run and not a test.

## Result

harness/research_plan.py:686-697 wraps the plan evaluation in `except Exception`, re-raising only `ToolCancelled`, and records `state="unavailable"` with `reason=f"reviewer_error: {type(exc).__name__}"` while `record["cost"]` stays 0.0. `JevPolicy.evaluate_research_plan` (harness/jev_policy.py:2172-2174) re-raises `ProviderUsageUnknown` precisely so the known spend and unresolved liability are not discarded, so this handler converts billed-unknown usage into an ordinary outage and lets the lane continue.

## The finding

When plan evaluation raises `ProviderUsageUnknown`, this new broad handler converts it into an ordinary unavailable-review record with `cost: 0.0` and lets the request continue to answer generation. `JevPolicy.evaluate_research_plan` explicitly re-raises this exception because it carries known spend and unresolved billing liability; swallowing it discards those amounts and allows the hourglass lane, which previously propagated the exception, to continue spending and potentially finish successfully despite an unknown provider charge. Re-raise `ProviderUsageUnknown` alongside `ToolCancelled` rather than handling it as a recoverable reviewer outage.

## Scope of this issue

Re-raise `ProviderUsageUnknown` beside `ToolCancelled` instead of converting it into a zero-cost unavailable record, so the known spend and unresolved liability reach the lifecycle. An ordinary reviewer failure keeps the recoverable outage path; a billed-unknown outcome does not.

## Not claimed

- Not claimed: that every exception must propagate; a refusal or transport error stays a recoverable outage with retrieval closed.
- Not claimed: any change to how the lane records an outage.
- Not claimed: that the lane must fail; it must account for the unknown charge before it continues.

## Acceptance

- `decide_research_plan` propagates `ProviderUsageUnknown` rather than returning an unavailable record.
- The known spend and unknown liability from that call reach the governor and the request lifecycle.
- A hermetic test raises `ProviderUsageUnknown` from the plan evaluation and asserts it escapes.

Provenance: https://github.com/Treystu/harness/pull/675#discussion_r4659935859

