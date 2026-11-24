## Lane 1 landing - #342 chat-lane plan proposal and retrieval gate

**PR:** #675, head `a809f73`, read fresh at that exact head: 16/16 CircleCI
contexts success, 0 pending, 0 bad, including `audit`. Squash-merged as
`f369bc15550f37596ea5b3ce7a473e48cf63bbe2`, read back with `gh pr view`.
Register correction in PR #676, head `2e192c3`, 16/16 at that head, merged as
`7d243ebf1c5157f1352667f50d1dae4563949c00`.

### What landed

This is the second part of the remainder #342 named: every request entrypoint
now proposes a plan before it can retrieve.

- `harness/research_plan.py` gains `decide_research_plan`: one function owning
  the proposal, the single native judgment, and the `validate_plan` band. A
  missing reviewer, an unkeyed one, a decline, an invalid answer or a reviewer
  that raises all return no approval. A reviewer exception is caught and
  recorded as `unavailable` (`reviewer_error: <type>`) instead of unwinding the
  turn; cancellation still propagates.
- `HourglassLifecycleMixin._research_plan_decision` is now a one-line delegate
  to that owner, so the two lanes cannot drift.
- `_handle_conversation` proposes the plan for its own prompt, has native Jev
  judge it once, and gathers only when the approval is accepted. The accepted
  plan, its approval and the request id are forwarded to `_gather_web_context`.
  The request id is the lifecycle's `request_id` when one exists and a
  per-turn `chat:<session>:<uuid4>` otherwise; either way it is what
  `validate_plan` and the approval are bound to.
- A refusal is disclosed as a refusal: the system prompt carries a
  `WEB RETRIEVAL WITHHELD` note with the typed reason, not the old
  "no internet access" text, which was false when the tools existed and only
  the plan was missing. The gate record (state, decision, native, plan hash,
  request hash, reason, cost) is returned as `research_plan` on the result.

### Refusal outcomes, each asserted

`policy_missing` (no plan reviewer on the policy), `reviewer_error` (the
reviewer raises), and native `decline` each end with zero search calls and zero
fetch calls, the withheld disclosure in the system prompt, and the typed state
on the result. An accepted plan sends exactly its own query string once.

### Contract change, named

A URL-only request's accepted plan names that fetch and nothing else, so a dead
fetch now ends with honest insufficient evidence instead of a prompt-wide
derived search. Two chat tests pinned the older fallback; they now assert the
contract (`test_a_failed_fetch_ends_insufficient_instead_of_a_derived_search`,
`test_web_fetch_failure_is_disclosed`: failure disclosed, zero searches, no
`web_source`). Recovering that fallback needs an approved search query or a
fallback field in the plan schema; the schema has neither, so neither is
invented here. This is named as a gap on the issue and in the register.

### Verification

- `tests/test_conversation_research_gate.py` (new, hermetic): accepted plan
  sends exactly its own query; declined plan, unkeyed reviewer and raising
  reviewer each keep zero searches and zero fetches, disclose the withheld
  retrieval and record the typed state; the plan binds to the lifecycle
  request id. Reviewer and network seams are patched; the proposal, the gate
  and `validate_plan` are the production ones.
- `tests/test_result_reviewer.py` and the chat-lane doubles now supply an
  accepting reviewer through `tests/_researchplan.py::AcceptingPlanPolicy`,
  because retrieval without native acceptance is no longer reachable by design.
- `pytest` on the five directly affected modules -> 212 passed; on the wider
  affected set (edge coverage, cancellation, answer lifecycle, web, run
  limits, D12 coverage, hourglass end-to-end and surface parity, docs
  contracts) -> 339 passed, 3 skipped.
- Full `tests/` -> 7683 passed, 82 skipped, 1264 subtests, with one pre-existing
  environment-bound failure: an ignored local `audits/scmessenger/_runs` scratch
  directory (0 tracked files) that `test_local_fit_optional_ci_311` refuses. The
  same test passes on the CI checkout, and CircleCI `audit` is green at the
  exact head.
- `ruff check` on every touched file: clean.

### What is not claimed

- No CLI/MCP native accepted or declined lifecycle receipt exists for #342;
  that needs a native Jev key and is not substituted with fixtures.
- A resumed hourglass turn re-proposes and re-reviews the plan rather than
  reusing the recorded acceptance (#344's remaining gap).
- The lost derived-search fallback is named as a schema gap, not restored.
- #342 and #344 stay OPEN. This record claims one slice, not an issue.
