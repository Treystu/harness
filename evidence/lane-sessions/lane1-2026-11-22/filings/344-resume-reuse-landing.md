## Lane 1 landing - #344 reuse the recorded plan acceptance on resume

**PR:** #677, head `b155b0a`, read fresh at that exact head: 16/16 CircleCI
contexts success, 0 pending, 0 bad, including `audit`. Squash-merged as
`1de3179391f78cf028659baab5291dec4e052943`, read back with `gh pr view`.
Register correction in PR #678, head read at 16/16 with 0 pending and 0 bad,
merged as `764c1a94a8eb058129869079aa8fb1cb55bd141a`.

### What landed

This is the one remainder the #344 row named after PR #671: a resumed
hourglass turn re-proposed and re-reviewed the same research plan instead of
reusing the acceptance it had already been granted.

- `harness/research_plan.py` gains `saved_plan_approval(plan, *, plan_hash,
  receipt)`. It rebuilds the checkpoint's receipt only when the live plan is
  identical -- same plan hash, same request hash, same revision, and a native
  `accept` recorded for that hash. A changed plan, a changed request, an
  unrecorded plan, a missing receipt, a non-native one or a decline each return
  `None`. It rebuilds a recorded receipt; it never manufactures one.
- `decide_research_plan` accepts `saved_plan` and tries that rebuild before
  paying for a review. Adoption still runs `validate_plan`, so an expired
  consent is rejected with `reuse-rejected` and falls through to a fresh
  native judgment instead of riding in. On adoption the gate record carries
  `reused: true` and `cost: 0.0`.
- `run_hourglass_request` passes the checkpoint's recorded acceptance only
  while resuming, and the caller-supplied-plan branch uses the same rebuild
  instead of declining with `approval_missing`.
- The checkpoint records `plan_approval` as the full `PlanApproval.payload()`.
  The earlier hand-picked six fields dropped `query_verdicts` and
  `expires_at`, which is exactly what `_approval_check` needs, so no rebuild
  could have passed validation from the old record.

### Outcomes, each asserted

- Identical plan plus a recorded native accept: no `evaluate_research_plan`
  call, retrieval stays on, gate record `accepted`, `reused: true`,
  `cost: 0.0`.
- Expired recorded consent: `reuse-rejected`, the reviewer is called once, and
  the fresh judgment decides.
- Changed plan, changed request hash, changed revision, missing, non-native or
  declining receipt: no reuse.

### Verification

- `tests/test_route_reuse_binding.py` -> 23 passed, including five new unit
  tests on the rebuild, one resumed-lifecycle control where the identical plan
  is never re-reviewed and the saved context is still reused, and one expired
  receipt control that does review again.
- Affected modules (`test_route_reuse_binding`, `test_research_plan`,
  `test_hourglass_research_checkpoint`, `test_conversation_research_gate`,
  `test_agent`, `test_result_reviewer`) -> 235 passed.
- Full `tests/` -> 7689 passed, 82 skipped, 1264 subtests, with the one
  pre-existing environment-bound failure (`test_local_fit_optional_ci_311`
  reading an ignored local `audits/scmessenger/_runs` scratch directory). The
  same test passes on the CI checkout, and CircleCI `audit` is green at the
  exact head.
- `ruff check` on every touched file: clean.

### What is not claimed

- The checkpoint stores the plan hash, not the plan body. A resume that
  supplies no plan still re-proposes the draft and re-routes with
  `plan-unknown`, because route reuse is bound to the plan the checkpoint
  recorded and there is no live plan to compare. Only the billed judgment is
  avoided. Persisting the plan body is a schema addition this landing does not
  make; it is named here rather than invented.
- #344 stays OPEN. This record claims one slice, not an issue.
