## Lane 1 landing - #344 approved-plan and receipt binding

**PR:** #671, head `f1d98edd15b600336eac2cfa8e87aa5434517f8c`, read fresh at
that exact head: 16/16 CircleCI contexts success, 0 pending, 0 bad, including
`audit`. Squash-merged as `a70662013dcc9193c81b94ac5957a6b9e396bfd6`, read
back with `gh pr view`.

### What landed

This is the second of the two remainders #344 named. The route binding landed
earlier (PR #667, `baf65628`); this PR binds the saved decision to the accepted
research plan and its native receipt.

- `ChatResumePayload` now carries `approved_plan_hash` and `plan_approval`.
- `run_hourglass_request` accepts `research_plan` and `plan_approval`, and
  records both beside `route_preflight`, `route_request_prompt` and
  `route_recorded_at`.
- `_saved_route_plan_reusable` reuses a saved decision only when the live
  `ResearchPlan.hash()` equals the recorded hash, the recorded receipt exists,
  is native, is an `accept`, and names that same plan; a live approval, when
  supplied, must name it too.
- Each refusal has its own reason: `plan-changed`, `plan-unknown`,
  `plan-unrecorded`, `plan-receipt-missing`, `plan-receipt-not-native`,
  `plan-receipt-declined`, `plan-receipt-mismatch`, `plan-approval-mismatch`.
- A checkpoint written before plan binding has no plan field and keeps its
  existing request-only binding, so an older save does not lose reuse for a
  field it never had.

### Verification

- 10 new tests in `tests/test_route_reuse_binding.py`: eight predicate
  outcomes plus two adapter controls - the plan and its receipt are persisted
  through `run_hourglass_request` (read back out of the lifecycle `data`), and
  a changed plan routes again instead of inheriting the saved decision.
- `pytest tests/test_route_reuse_binding.py tests/test_hourglass_end_to_end.py
  tests/test_shared_lifecycle.py tests/test_request_lifecycle.py
  tests/test_conversation_context.py tests/test_research_plan.py -q` ->
  219 passed, 31 subtests.
- Changed-line coverage on the touched `harness/` files, measured with the
  audit's own statement rule: 31/31 = 100%. `ruff check` and `compileall`:
  clean.
- Register correction in PR #672, its own 16/16 at `c49e280e`.

### What is not claimed

- No lifecycle path proposes a plan yet, which is #342's next slice. Live
  turns therefore pass no plan and keep today's behavior; the binding is
  enforced for any caller that supplies one.
- #344 stays OPEN. This record claims one compared field, not the issue.
