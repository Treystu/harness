Landing record for this issue. One of the two named remainders is built; the
other is a dependency gap that is named rather than invented.

**DONE - saved native-route reuse across a changed request** (PR #667, merged as
`baf65628a61f9b61b5ac634276ea4c5f6b1bbc92` at head `0ba0a65`, 16/16 CircleCI at
the exact head, `audit` included).

The defect was real and in the route, not the context: `run_hourglass_request`
chose its route with `request_preflight or checkpoint["route_preflight"]` before
any request check, so a resumed checkpoint handed its saved routing judgment to
a changed request. A saved native `web-research` choice made the new turn
retrieve; a saved `answer` choice made it skip retrieval the new request earned.
The context predicate from #648/#661 could not catch it, because it runs after
the route is fixed.

`_saved_route_decision_reusable(checkpoint, prompt)` now binds the saved
`route_preflight` - the routing receipt, which records the choice, whether it
was native, and now the request it was judged for - to the current request's
identity. A changed request returns `request-changed` and the route is decided
again; an unchanged continuation reuses it and does not pay for a second review.
Checkpoints written before `route_request_prompt` existed fall back to `prompt`
(their recorded request) and are bound just as strictly; a missing or blank
identity fails closed as `route-request-unknown`. Every decided route persists
`route_request_prompt` and `route_recorded_at` beside `route_preflight`, and
`ChatResumePayload` types both. The reuse decision is emitted as `chat_route`
with `reused` and the reason, so the run record says which branch ran.

Controls through the public adapter (`run_hourglass_request`), not only the
predicate: a changed request routes again - the fresh Jev review is called once,
the answer runs without the inherited web routing, and the persisted record names
the new request and the fresh decision - and an unchanged request keeps the saved
route with no second review and no context rebuild.

**NOT BUILT - approved-plan/receipt binding, and why.** The issue addendum asks
the checkpoint identity to include the accepted ResearchPlan hash and the native
Jev approval receipt. No `ResearchPlan` exists in this repository:
`grep -rn ResearchPlan harness tests` returns no matches, and #342 is the open
issue that builds that lifecycle. A plan hash cannot be computed from a type
that does not exist, and this lane does not invent another issue's deliverable to
close a sentence here. What is bound today is the routing receipt that does
exist, at the point where the routing judgment is consumed. When #342 lands, the
plan hash and its Jev receipt join the same predicate as additional compared
fields; the reason vocabulary already distinguishes a mismatch, and no schema
change is needed beyond the fields #342 introduces.

Verification at the merge head: `pytest tests/test_route_reuse_binding.py
tests/test_checkpoint_context_binding.py tests/test_shared_lifecycle.py
tests/test_hourglass_end_to_end.py -q` -> 57 passed, 2 subtests; the wider
affected set (`test_agent`, `test_jev_answer_lifecycle`,
`test_never_defer_changed_lines`, `test_cancellation_lanes_cover`, hourglass
stage/surface/jev/brief) -> 383 passed, 21 subtests; `ruff check` over the CI
scope -> clean; `compileall` -> clean. Changed-line execution was measured with
`coverage run --branch` on the touched module: every return of the new predicate
and both call-site branches execute; the uncovered ranges are
`_hourglass_context_matches`, untouched here.

Register: the row was updated in a follow-up PR (#668, head `4c5c00a`, 16/16 at
that head, merged as `900029a7e97a017a2e027ad947d11416b8b8b560`). The issue stays
OPEN: one named remainder is a dependency on #342, and closure is the operator's
call.
