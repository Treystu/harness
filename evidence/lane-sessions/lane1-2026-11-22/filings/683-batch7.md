# #683 batch 7 - rows 73-84 verified against main

This is a disposition comment for the #683 tracker. It closes nothing and takes
no completion credit.

## Method

Each row was checked by reading the exact code path the finding names in
`origin/main` at `8fc28a0e`, on 2026-11-25. A row is FIXED only when the shipped
code now does what the finding asked; it is STILL PRESENT when the path the
finding describes is still reachable. No repository code changed in this act, so
every verdict is a code read and no new test was run. Where a finding's requested
fix was delivered by a redesign rather than a patch, the FIXED note would name
the shipped code that replaced the defective path; this batch has no such row.

## Result: 0 FIXED, 12 STILL PRESENT, 0 NOT APPLICABLE

| Row | File | Finding | Verdict |
| --- | --- | --- | --- |
| 73 | harness/citation_resolver.py | Preserve unpublished status for posted-content subtypes | STILL PRESENT |
| 74 | harness/hourglass_lifecycle.py | Invalidate provider receipts when restarting with new context | STILL PRESENT |
| 75 | harness/citation_resolver.py | Require citation assessments to cover the report's actual claims | STILL PRESENT |
| 76 | harness/jev_policy.py | Preserve billed spend and unknown liability on cancellation | STILL PRESENT |
| 77 | harness/web.py | Fail closed when reviewer initialization fails | STILL PRESENT |
| 78 | harness/web.py | Carry reviewer costs back to the request lifecycle | STILL PRESENT |
| 79 | harness/hourglass_lifecycle.py | Bind the provider-call cache key to the rerouted request | STILL PRESENT |
| 80 | harness/research_plan.py | Preserve the judgment's original plan and request binding | STILL PRESENT |
| 81 | harness/web.py | Bind the fetch policy before passing the default fetcher | STILL PRESENT |
| 82 | harness/research_plan.py | Enforce the accepted plan's aggregate source limit | STILL PRESENT |
| 83 | harness/hourglass_lifecycle.py | Invalidate the provider receipt when the plan changes | STILL PRESENT |
| 84 | harness/hourglass_lifecycle.py | Preserve the saved approval when resuming without a new one | STILL PRESENT |

## The still-present rows

- **73** `harness/citation_resolver.py:137-143` merges the two registry fields —
  `subtype = str(message.get("subtype") or message.get("type") or "").lower()` —
  and then tests that merged value against `("posted-content", "preprint")`,
  assigning `version = "published"` to everything else. A record with
  `type: "posted-content"` and `subtype: "working_paper"` therefore never matches
  the parent type and is stamped published, so a citation claiming published
  status over a working paper still verifies as supported.
- **74** `harness/hourglass_lifecycle.py:1259-1262` keys the answer receipt as
  `lifecycle_state["request_id"] + f":chat-answer:{round_no}"`, and
  `harness/lifecycle.py:403-410` returns the stored `result` for any completed
  call id before invoking. A resumed lifecycle keeps its original `request_id`
  (`harness/lifecycle.py:140-151` adopts the same state) and nothing clears
  `usage.provider_calls`, so a changed instruction that rebuilds context still
  replays the round-1 answer without invoking the answer provider.
- **75** `harness/citation_resolver.py:196-199` passes only
  `report.get("citation_claims")` into `audit_citations`, which labels the report
  from exactly the claims it was given (`harness/citation_verify.py:417-421`), and
  `harness/cli.py:486-492` publishes that label as `citation_verified`. Nothing
  compares `citation_claims` against the report's `claims`, so a claim left out
  of the audited list is never assessed and the report-level label still passes.
- **76** `harness/jev_policy.py:2022-2024` catches
  `(ToolCancelled, ProviderUsageUnknown)` in `evaluate_result_relevance` with
  `self._release(reservation)`, and `_release` is documented at `:665-667` as
  settling the reservation at zero. `_settle_cancelled` exists and is used by
  `_release_reservation` at `:582-591`, but not on this path.
- **77** `harness/web.py:798-802` handles an absent reviewer by emitting
  `web_result_review_unavailable` and returning `ordered` unchanged: no verdict,
  no withholding, and no `reviewer` evidence-block entry, which is only appended
  on the `outage` branch at `:838-845`.
  `harness/conversation_lifecycle.py:155-160` leaves `web_policy = None` when
  reviewer construction raises, so a reviewer setup outage reaches the admission
  branch rather than the withholding branch.
- **78** `harness/web.py:798-801` keeps only `structural.get("results")` (read at
  `:812`); `structural["cost"]` is never returned, and the function's only result
  is the filtered source list. Its caller,
  `harness/conversation_lifecycle.py:588-589`, returns that list alone, so a
  billed relevance review never reaches conversation result cost or the hourglass
  `total_cost` and checkpoint `known_cost`.
- **79** `harness/hourglass_lifecycle.py:939-945` calls `provider_call` with the
  key `lifecycle_state["request_id"] + ":chat-route-review"`, and
  `harness/lifecycle.py:403-410` returns the cached completed result for that id
  before invoking. The reuse predicate at `:572-606` does reject a changed
  request, but rejecting it does not change the call id, so a persisted lifecycle
  that already holds a completed route receipt returns the old decision;
  `route_request_prompt` is then overwritten at `:969` with the new prompt.
- **80** `harness/research_plan.py:521-526` builds the `PlanApproval` from the
  supplied plan (`plan.hash()`, `plan.request_hash`, `plan.revision`) and never
  reads the binding the judgment carries, although
  `harness/jev_policy.py:2128-2130` and `:2162-2165` do emit `plan_hash`,
  `request_hash` and `revision` in the structural envelope. A judgment made for
  one plan can be restamped onto another, and `validate_plan` (`:405-444`) then
  accepts the new binding.
- **81** `harness/web.py:867-875` hands `fetch_url` (or the injected
  `fetch_url_fn`) straight to `execute_plan` as the plan's `fetch_fn`, while
  `fetch_url` at `:616-617` requires `allowed_hosts` and the legacy branch at
  `:900-905` passes it explicitly. `harness/research_plan.py:798-803` then calls
  `fetch_fn(url)` with one positional argument, and `_fetch_source` catches only
  `HarnessError`, so the `TypeError` escapes an accepted URL plan.
- **82** `harness/research_plan.py:771-781` appends every search's `max_results`
  sources and one source per fetch, and never reads `plan.max_sources`; the field
  is validated at `:354-355` as a plan property only. A two-query plan with
  `max_results=3` and `max_sources=1` still returns six sources, past the budget
  the reviewed plan carried.
- **83** `harness/hourglass_lifecycle.py:939-945` keys the route review as
  `lifecycle_state["request_id"] + ":chat-route-review"`, which carries no plan
  binding, and `harness/lifecycle.py:403-410` returns the completed receipt.
  `_saved_route_plan_reusable` at `:610-660` rejects a changed plan, but the
  rejection only stops reuse: the subsequent `provider_call` replays the cached
  decision, which `:969` then records under the new plan's hash. This is the same
  cache-key defect row 79 reports for a changed request, so it gets one
  sub-issue (row 79's) rather than a duplicate; the plan half is named in that
  issue's acceptance.
- **84** `harness/hourglass_lifecycle.py:1061-1066` writes
  `checkpoint["plan_approval"]` from `plan_approval` alone, falling back to
  `{"decision": "", "native": False, "plan_hash": "", "request_hash": "",
  "revision": 0, "consent_id": ""}` when the caller supplied none. A resume that
  re-supplies the identical plan without a replacement approval leaves
  `plan_approval` as `None` whenever `saved_plan_approval` declines to rebuild it,
  so the recorded receipt is replaced by the empty non-native dict and the next
  continuation fails `plan-receipt-not-native` at `:638-642`.

Machine-readable: `evidence/lane-sessions/lane1-2026-11-22/683-batch7.json`,
where each row carries its verdict, evidence, finding body and discussion url.

## Not claimed

- Not claimed: these severities. They are the census's, not re-derived here.
- Not claimed: any runtime reproduction. Every verdict is a read of the named
  path at `8fc28a0e`; the four P1 rows deserve a reproducer when they are fixed.
- Not claimed: that rows 79 and 83 need one code change. The shared defect is the
  unbound route-review call key; whether one repair reaches both cases is for the
  fix to show.

## Running totals for #683

Rows 1-84 of 89: **22 FIXED, 62 STILL PRESENT, 0 NOT APPLICABLE**, 5 not yet
verified. The tracker is not closeable on this subset.

## Next for this issue

Sub-issues for the eleven distinct still-present rows in this batch (73, 74, 75,
76, 77, 78, 79 with 83, 80, 81, 82, 84), each gated like #749-#774. Then rows
85-89, which complete the census, and the reviewed-PR queue (#649, #650, #651,
#652, then #703).
