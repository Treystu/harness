## Lane 1 landing - #308 planning evidence owner

**PR:** #679, head `ef6e2bc6148bf1ea8975f7cfae7f6c50454d96bb`, read fresh at
that exact head: 16/16 CircleCI contexts success, 0 pending, 0 bad, including
`audit`. Squash-merged as `4ce7a69168c3f86ac4db19564a7d87caf9636732`, read back
with `gh pr view`. Register record in PR #680, head
`09197d69cfab1d62658c828d5e696088fa6313c9`, also 16/16 with 0 pending and 0
bad, merged as `0706f93ce4981752145c674df812cb3df133ed0e`.

### What landed

#308 owns splitting `harness/waist.py` by planning responsibility. The
earlier split gave decomposition (`plan_decompose`), consensus/confirmation
(`plan_consensus`), context intake (`plan_context`), stage composition
(`plan_stages`) and the vocabulary (`plan_contracts`) their own owners and kept
orchestration in the waist. The planning loop's **evidence** concern was still
inside the waist; this landing extracts it.

- `harness/plan_evidence.py` owns `_curated_brief` (the largest brief whose
  measured token estimate fits a round's allowance), `_unrepresented` /
  `_conflicts` (what the brief itself admits it could not represent, and where
  it declares a conflict), `_evidence_request` (the bounded request built from
  those admissions), `_jev_sufficiency` (the one sufficiency judgment, asked
  through its declared dimension and never promoted from a fallback),
  `_validated_plan` and the `DEFAULT_MAX_PLAN_NODES` bound it enforces.
- The waist keeps `run_planning` and `PlanningOutcome` - the loop that walks
  the allowance ladder consumes those answers and does not re-derive them -
  and re-exports the moved names, so call sites and the existing patches on
  `harness.waist.*` resolve unchanged.
- The new module imports nothing from the waist, at module scope or
  otherwise; the owner-split test's own control asserts that.
- `waist.py`: 1906 -> 1795 lines.

### The first rail failed, and why

The first head (`e5091f2`) came back 15/16 with `audit` red. The failing rule
was the audit's module map (`sd_contributing` / `SD/D10`): every public harness
module must carry a row in `CONTRIBUTING.md`, so an extraction cannot merge
without its one-line owner entry. `CONTRIBUTING.md` gained that row in
`ef6e2bc`; `sd_contributing` was then read directly (1.0, pass) and the full
rail at `ef6e2bc` is 16/16. No check was weakened or skipped.

### Outcomes, each asserted

- `tests/test_plan_lane_owners_308.py` gains a `harness.plan_evidence` owner
  entry, so the existing controls now enforce that the waist does not redefine
  an owned concern and that the owner imports without the waist.
- A new control asserts `waist.<name> is plan_evidence.<name>` for every moved
  name and for `DEFAULT_MAX_PLAN_NODES`: the loop calls the owner's objects,
  not a copy.

### Verification

- `tests/test_plan_lane_owners_308.py`, `test_hourglass_planning_budget.py`,
  `test_hg_composed_ceiling.py`, `test_hourglass_stage_composition.py`,
  `test_hourglass_brief.py` -> 143 passed, 28 subtests.
- `test_waist.py`, `test_hourglass_end_to_end.py`,
  `test_hourglass_execution_budget.py`, `test_hourglass_jev_integrations.py`,
  `test_hourglass_planning_budget.py`, `test_plan_lane_owners_308.py` -> 201
  passed, 27 subtests.
- Full `tests/` -> 7672 passed, 82 skipped, 1274 subtests, 0 failed, with the
  environment-bound `tests/test_local_fit_optional_ci_311.py` deselected (it
  reads an ignored local `audits/scmessenger/_runs` scratch directory); the CI
  checkout runs it and CircleCI `audit` is green at the exact head.
- `ruff check harness tests/test_plan_lane_owners_308.py`: clean.

### What is not claimed

- #308 stays OPEN. Two planning concerns remain in the waist and are named on
  the issue and in the register row rather than silently counted as done: the
  composed budget envelope (`composed_worst_case` / `_refuse_composed_ceiling`)
  and the tier-0 chunker (`chunk_oversized_nodes`).
- #346's behaviour repair is not re-verified here beyond its existing tests
  running green; this landing moved code, it did not change the accounting.
- The local 4-dimensional audit was not used as evidence. It was started
  against this branch and had not finished `SD/D12` when this filing was
  written; the CircleCI `audit` at the exact head is the authoritative read.
