## Lane 1 landing - #308 composed budget envelope owner

**PR:** #681, first head `06ac01f20344b659749cf81c09d2d0ba044207d2` (15/16,
`audit` red on D12), final head `f9ed95fdf667a73667aadd31b12c04d5d24ecb18`,
read fresh at that exact head: 16/16 CircleCI contexts success, 0 pending, 0
bad, including `audit`. Squash-merged as
`070071f3e41a59f77e9155a42b3ab6f63864b7dd`, read back with `gh pr view`.
Register record in PR #682, head
`10ad3e54c0ec0290e72e6539ff82f96311182a4a`, also 16/16 with 0 pending and 0
bad. No check was weakened or skipped.

### What landed

The previous #308 slice gave the planning loop's evidence concern its own
owner. The **composed budget envelope** was the next concern still inside
`harness/waist.py`, and this landing extracts it.

- `harness/plan_budget.py` owns the one worst-case number the plan lane checks
  before execute spend: `composed_worst_case` sums the plan's node ceilings and
  the worst case of every stage not yet incurred (decompose, consensus, waist
  rounds) and compares that against `governor.remaining()`. The same module
  owns `_call_worst_case` (the completion-side worst case of one bounded
  plan-lane call), `_refuse_composed_ceiling` (the fail-closed envelope when
  the composition does not fit) and `DECOMPOSE_MAX_TOKENS`.
- The waist keeps the orchestration: `compose_plan` still decides when to ask
  and what a refusal means, and imports the owner's three names, so
  `harness.waist.composed_worst_case` patches and the compatibility surface
  resolve unchanged.
- The ladders stay in the waist because the lanes patch
  `harness.waist.resolve_scout_ladder` / `resolve_waist_ladder` there. The
  owner resolves them at call time rather than binding them at import, so
  those patches still reach the numbers; the owner imports nothing from the
  waist at module scope.
- `waist.py`: 1795 -> 1647 lines.

### The first rail failed, and why

The first head came back 15/16 with `audit` red on `SD/D12` (changed-line
coverage, 95% bar): the new owner measured 80% (70/88 statements `_coverage_ratio`
counted as changed), because its degradation branches were untested. The fix
was at the cause, not around it: `BudgetOwnerDegradationTests` in
`tests/test_hg_composed_ceiling.py` exercises the unpriceable-call,
malformed-ceiling, unreachable-ladder and unreadable governor-limit branches,
each of which must contribute $0.0 rather than an invented number. The owner
then measures 88/88 statements (100%) and the rail at `f9ed95f` is 16/16.

### Outcomes, each asserted

- `tests/test_plan_lane_owners_308.py` gains a `harness.plan_budget` owner
  entry, so the existing controls now also enforce that the waist does not
  redefine this concern.
- A new control asserts `waist.composed_worst_case`,
  `waist._refuse_composed_ceiling` and `waist.DECOMPOSE_MAX_TOKENS` are the
  owner's objects, not copies.
- `CONTRIBUTING.md` carries the module-map row for the new public module, the
  rule the audit enforces.

### Verification

- `tests/test_plan_lane_owners_308.py`, `test_hg_composed_ceiling.py`,
  `test_hg_extra_coverage.py`, `test_hourglass_stage_composition.py`,
  `test_hourglass_end_to_end.py`, `test_hg_plan_consensus.py`,
  `test_reserve_call_parity.py` -> 101 passed, 39 subtests, 0 failed.
- The same set plus `test_hg_plan_consensus.py` under coverage ->
  `harness/plan_budget.py` 88 statements, 0 missed.
- Full `tests/` at the final head's code -> 7673 passed, 82 skipped, 1280
  subtests, 0 failed, 570.87 s, with the environment-bound
  `tests/test_local_fit_optional_ci_311.py` deselected (it reads an ignored
  local `audits/scmessenger/_runs` scratch directory); the CI checkout runs it
  and CircleCI `audit` is green at the exact head.
- `ruff check harness/ tests/test_plan_lane_owners_308.py`: clean.

### What is not claimed

- #308 stays OPEN. One planning concern remains in the waist and is named on
  the issue and in the register row rather than counted as done: the tier-0
  chunker (`chunk_oversized_nodes` with its split/reserve helpers).
- #346's accounting behaviour is not re-verified beyond its existing tests
  running green; this landing moved code unchanged in behaviour.
- The local 4-dimensional audit run on this branch finished at `AUDIT_EXIT=1`
  with `R13` failing on the environment-bound tests above and `D12` skipping
  locally as a platform gap. It was not used as evidence, and its side effect
  on the tracked `audits/self/round2_scores.json` was reverted; the CircleCI
  `audit` at the exact head is the authoritative read.
