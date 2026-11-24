## Lane 1 landing - #342 lifecycle proposer and the accepted-plan retrieval gate

**PR:** #673, head `5663966b9bfb5d73e03a1a8a595a954d2d1847d9`, read fresh at
that exact head: 16/16 CircleCI contexts success, 0 pending, 0 bad, including
`audit`. Squash-merged as `0ca8ac832afa6b08e23418d52611e834740cd7a9`, read
back with `gh pr view`. Register correction in PR #674, head `b98c3c45`,
16/16 at that head, merged as `59ccb82a`.

### What landed

This is the first part of the remainder #342 named: the lifecycle proposes a
plan, and both of the lane's network paths sit behind its acceptance.

- `harness/research_plan.py` gains the proposal half of the contract:
  `propose_plan` drafts the effective goal (quoted logs, traces, fenced code
  and block quotations removed), the exact named URLs or one bounded search
  query, the capability set those actions need, freshness, evidence
  requirements and the absent-fallback policy. `goal_urls` extracts only the
  URLs the goal itself names; `plan_authorizes_url` answers whether a plan
  names one exact URL. Proposing is a heuristic and authorizes nothing:
  `validate_plan` still refuses a plan with no native accepting approval.
- `harness/hourglass_lifecycle.py` gains `_research_plan_decision`, which
  proposes, calls `JevPolicy.evaluate_research_plan` once, bands the envelope
  with `approval_from_judgment`, and revalidates. `run_hourglass_request`
  calls it before retrieval and clears `web` unless the plan is accepted; the
  gate record (`state`, `decision`, `native`, `plan_hash`, `reason`, `cost`)
  goes into the checkpoint under `research_plan_gate` and into the result as
  `research_plan`.
- Both network paths are gated: `_gather_web_context` receives
  `plan`/`approval`/`request_id` and forwards them to the single
  `gather_web_context` owner, and `render_site_evidence` runs only when
  `plan_authorizes_url` says the accepted plan names that exact URL. The
  previous site-audit path rendered from a heuristic with no plan.
- `_hourglass_request_context` validates at the seam itself, so a direct
  caller with `web=True` and no accepted plan gets zero searches, zero
  fetches and zero renders and a typed `detour` blocker naming the refusal
  code.

### Refusal outcomes, each asserted

`plan_missing`, `goal_too_short`, `policy_missing`, unkeyed/reviewer-outage
`unavailable`, native `decline`, non-native approval, and a plan bound
to another request each end with zero search, zero fetch and zero render
calls. Route choice (`web-research`), the caller's `web=True` flag and the
research/current-information heuristics are all checked as proposals that do
not open retrieval on their own.

### Verification

- `tests/test_hourglass_research_checkpoint.py` (new): the seam gate, the
  renderer URL gate (exact URL once, unlisted URL zero), the lifecycle
  proposer accepted/declined/unavailable, a caller-supplied plan validated
  rather than trusted, a foreign request binding refused, and the checkpoint
  gate plus native receipt read back out of the lifecycle `data`.
- `tests/test_research_plan.py`: proposal identity and request hash, quoted
  URL exclusion, capability declaration, proposal-is-not-approval, URL
  authorization, goal URL order/deduplication.
- Existing direct-seam tests now supply an accepted plan through
  `tests/_researchplan.py`, which is the contract they exercise; their
  assertions are unchanged.
- `pytest tests/test_hourglass_research_checkpoint.py tests/test_research_plan.py
  -q` -> 66 passed. Affected hourglass/web set -> 350 passed, 11 subtests.
  Full `tests/` -> 7673 passed, 82 skipped, with two pre-existing
  environment-bound failures: an ignored local `audits/scmessenger/_runs`
  scratch directory (0 tracked files) and a timing-sensitive driver probe that
  passes in isolation.
- `ruff check` on every touched file: clean. Local audit: D10 and D12 pass;
  R13 fails only on those same environment-bound local tests, while the
  `audit` context on CircleCI is green at the exact head.

### What is not claimed

- The chat lane's `_handle_conversation` still gathers through the legacy path
  and proposes no plan. It is named on the issue, not claimed as done.
- No CLI/MCP native accepted/declined lifecycle receipt exists; that needs a
  native Jev key and is not substituted with evaluator-only fixtures.
- A resumed hourglass turn re-proposes and re-reviews the plan rather than
  reusing the recorded acceptance (#344's remaining gap).
- #342 and #344 stay OPEN. This record claims one slice, not an issue.
