## Lane 1 landing - #344 record and rebuild the accepted research plan on resume

**PR:** #713, head `85b4b5b93f987d532c3a4038047c51f89746fa20`, read fresh at
that exact head: 16/16 CircleCI contexts success, 0 pending, 0 bad, including
`audit`. Squash-merged as `962333d92b28aa4f46b011d46a2e1db9616c6c7e`, read back
with `gh pr view`. Register correction in PR #714.

### What landed

This is the one remainder the #344 row named after PR #677: the checkpoint
recorded the accepted plan's hash and native receipt but not the plan body, so a
resume that supplied no plan could not bind its saved route decision to the plan
that decision judged. `_saved_route_plan_reusable` returned `plan-unknown`, the
route was reviewed again (one billed native route review), and only afterwards
did the identical free proposal adopt the recorded acceptance.

- `ResearchPlan.from_payload` reads a canonical payload back strictly. A
  missing field, a wrongly typed field, a malformed query entry or any schema
  version other than `SCHEMA_VERSION` returns `None`; nothing is guessed.
- `run_hourglass_request` records `research_plan_body = plan.payload()` beside
  `approved_plan_hash` and `plan_approval`.
- On resume with no caller plan, `_recorded_plan` rebuilds that body and
  verifies it still hashes to the recorded value, and the route binding
  compares against that plan instead of `plan-unknown`. A tampered, unreadable
  or hash-mismatched body returns `None`, so the route is decided again rather
  than inherited.

### Controls, through the public adapter

`tests/test_route_reuse_binding.py`, 31 tests in the file:

- payload round-trip preserves the plan hash, its queries and capabilities;
- eight unreadable payload shapes are refused: `None`, a raw string, an empty
  dict, a wrong schema version, a payload with no `queries`, a query entry with
  no `query`/`purpose`, a string `queries`, and a non-numeric `max_results`;
- a recorded body rebuilds exactly the plan it hashed; no recorded hash or an
  unreadable body rebuilds nothing; a body for another plan is discarded and
  the binding still reports `plan-unknown`;
- resumed lifecycle with a recorded body: `evaluate_request_workflow` is not
  called, retrieval stays on, the plan gate records `reused` at cost 0.0, and
  the body is re-persisted;
- resumed lifecycle with a missing body, and with a tampered body: the route is
  reviewed exactly once and the turn still completes.

On the pre-cure tree (with `harness/` stashed to the base), 7 of these fail,
including `test_a_resumed_request_with_the_recorded_plan_is_not_reviewed_again`,
whose route-review assertion moved from `called_once` to `not_called` because
the second review no longer happens.

### Verification

- `tests/test_route_reuse_binding.py` -> 31 passed, `-W error::ResourceWarning`.
- Affected set (`test_route_reuse_binding`, `test_research_plan`,
  `test_hourglass_research_checkpoint`, `test_conversation_research_gate`,
  `test_result_reviewer`) -> 128 passed.
- `ruff check` on the three touched files -> clean.
- CircleCI `audit` green at the exact head `85b4b5b9`, which is where D12's
  changed-line bar is measured; the local D12 probe was not used as evidence.

### What is not claimed

- #344 stays OPEN; this record claims one slice, not the issue.
- No live provider call was made for this landing, and no live CLI/MCP retrieval
  lifecycle is claimed.

---

Gate receipt for the landing record above: Lucas Gate v2 `pass` (artifact sha256 `9ed5f723028919c0d6a30513e99399e74207d53c0f5caec76ba8472c03645539`); product Jev `investigate` / `proceed`, supported 0.07, margin 0.20, `jev-1.14.0`. Investigated in seat against primary sources: PR #713 read back from the API as MERGED with merge SHA `962333d92b28aa4f46b011d46a2e1db9616c6c7e`, its rail read at the exact head `85b4b5b9` (16 success, 0 pending, 0 failures, `audit` included), and the tests re-run on that head's tree (31 in `test_route_reuse_binding`, 128 across the affected modules). #344 remains OPEN; no completion credit is taken, and the register correction PR #714 is not claimed as merged here.
