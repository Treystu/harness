# Preserve the judgment's original plan and request binding

Part of #683, finding 80 (P1). Verified against `main` `8fc28a0e` on
2026-11-25: still present.

## Method

Code read of the named path at `8fc28a0e`: `harness/research_plan.py` and the code it calls,
on 2026-11-25. No repository code changed in that act, so this is a read
of the shipped path, not a run and not a test.

## Result

harness/research_plan.py:521-526 builds the `PlanApproval` from the supplied plan (`plan.hash()`, `plan.request_hash`, `plan.revision`) and never reads the binding fields the judgment carries; harness/jev_policy.py:2128-2130 and :2162-2165 do emit `plan_hash`, `request_hash` and `revision` in the structural envelope. A judgment made for one plan can therefore be restamped onto another, and `validate_plan` (:405-444) then accepts the new binding.

## The finding

When a native judgment for one plan is passed alongside a revised plan, this helper replaces the judgment's `plan_hash`, `request_hash`, and `revision` with those of the supplied plan. Consequently, an acceptance for query A can authorize an entirely different query B: `validate_plan` accepts the newly stamped receipt and `execute_plan` sends B without native review. Preserve and verify the binding fields from the judgment rather than assigning a new binding during receipt construction.

## Scope of this issue

Build the receipt from the binding fields the judgment carries and verify them against the plan, instead of restamping the supplied plan. A judgment that does not name the plan it judged cannot become an accepting approval.

## Not claimed

- Not claimed: that `validate_plan` needs a second gate; it already compares the receipt to the plan. The gap is that the receipt was manufactured from the plan in the first place.
- Not claimed: any change to the question pack or the bands.
- Not claimed: that a judgment carrying no binding fields must still be usable; unavailable is the honest result.

## Acceptance

- `approval_from_judgment` cannot produce an accepting approval whose binding differs from the judgment.
- An acceptance for one plan no longer authorizes a different plan execution.
- A hermetic test passes a judgment for plan A with plan B and asserts a declining or unavailable approval.

Provenance: https://github.com/Treystu/harness/pull/669#discussion_r4658925845

