## Lane 1 landing - #342 shared ResearchPlan owner and its native review

**PR:** #669, head `ef8fd8166a7b24b11d100c3aae712e487c1bcfe5`, read fresh at
that exact head: 16/16 CircleCI contexts success, 0 pending, 0 bad, including
`audit`. Squash-merged as `3a063e48cc43a8cb45bd58df8aec3c947698c658`
(2026-11-22T17:19:15Z), read back with `gh pr view`.

### What landed

`harness/research_plan.py` is now the single owner of a bounded,
request-bound research plan, which the tree did not have before this PR. At
base `900029a7` there was no plan type and no production reference:
`git grep -n "ResearchPlan" 900029a7 -- harness tests` returned exactly one
line, `tests/test_route_reuse_binding.py:8`, a test comment recording that the
type was missing. That comment names the gap; it is not an implementation.

- `ResearchPlan` / `PlanQuery` / `PlanApproval`: a versioned schema, a
  canonical payload and hash, and a binding to one request id plus the
  verbatim request hash.
- The plan carries the effective goal, exact query ids/strings/purposes,
  declared domains, freshness, evidence requirements, result/source/timeout/
  token/spend limits, its capability set, a revision index, and a policy that
  permits no silent fallback.
- Quoted logs, pasted traces, fenced code and block quotations are removed
  from the effective goal (`goal_from_prompt`), and a query or URL that
  appears only inside that region is rejected with `quoted_context`. This is
  the addendum's concrete case: a quoted trace URL and a gate phrase are not
  search intent.
- `validate_plan` returns typed codes for every refusal class: schema
  version, missing goal/freshness/evidence requirements, silent fallback,
  query id/text/purpose/duplicate, budget bands, revision ceiling, request
  id/hash mismatch, missing or undeclared capability, approval presence,
  non-native approval, declined decision, hash/revision/request mismatch,
  incomplete query verdicts, and stale consent.
- `execute_plan` sends only the accepted exact query strings and URLs. A
  rejected plan performs zero searches and zero fetches; a page that returns
  no readable text ends with `insufficient-evidence` rather than a derived
  search.
- `harness/jev_policy.evaluate_research_plan` is the only native judge:
  accept/revise/decline plus one relevance noul per exact query. Unkeyed,
  refusal, spend limit, transport error or an unusable answer reports
  `unavailable` with `native` false, so no local heuristic preview can become
  approval. An accept with an unacknowledged query, a rejected query, or a
  reported-low confidence is reported as `decline`.
- `harness/web.gather_web_context` transports a plan only through
  `execute_plan`; without a plan the existing path is unchanged.
- `CONTRIBUTING.md` carries the module-map row the audit's D10 dimension
  requires for every public module.

### Verification

- `pytest tests/test_research_plan.py -q` -> 43 passed.
- Wider affected set (research plan, result reviewer, web, Jev policy, docs
  contracts, conversation context, hourglass end-to-end/surface/jev,
  shared/request lifecycle, route reuse) -> 404 passed, 37 subtests.
- Changed-line coverage measured with the audit's own statement rule over
  that set: 294/300 = 98% of added `harness/` lines (bar 95%). The new module
  alone is 233/233 executable statements executed.
- `ruff check` on every touched Python file: clean. `compileall`: clean.
- The first rail on `eed22714` was 15/16 with `audit` red. Reproduced it
  locally: the failing dimension was D10 (`CONTRIBUTING current`, no
  module-map row), not D12. Added the row, re-ran that dimension -> pass, and
  the fresh rail on `ef8fd816` was 16/16.

### What is not claimed

- The lifecycle does not yet propose a plan in `hourglass_lifecycle.py` or
  `conversation_lifecycle.py`, so live turns still take the existing route
  path. `render_site_evidence` is not yet under the accepted-plan gate.
- No CLI/MCP native accepted or declined lifecycle receipt exists; that needs
  a native Jev key and was not substituted with evaluator-only fixtures.
- #342 therefore stays OPEN. No completion credit is taken for the issue.
