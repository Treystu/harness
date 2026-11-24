## Lane 1 check-in - 2026-11-22, pass 13 (LD-002: #308 planning evidence owner landed)

**Base read at start:** `main` `764c1a94a8eb058129869079aa8fb1cb55bd141a`, zero
open PRs, 40 open issues (live count).
**Head at the end of this pass:** `main` `0706f93ce4981752145c674df812cb3df133ed0e`
(PR #679, then register PR #680). Zero open PRs, 40 open issues (live count),
tracked tree clean.

Comm lock: #295 read at turn start and re-read before this filing; no new
Treystu directive and no STOP. Oversight tick 830 recorded the lane as stalled
and routed an in-place restart; this pass continues the filed order, whose NEXT
was the next unworked W1 item. #660 was re-read first and both of its
acceptance lines are already built (PR #663 `75fe2a8a`, PR #665 `d6dec51f`), so
the next unworked W1 item is #308.

### DONE

1. **#308 planning evidence owner landed** - PR #679, head `ef6e2bc`, 16/16 at
   that exact head including `audit`, squash-merged as `4ce7a691`. The waist
   still owned the planning loop's evidence side. `harness/plan_evidence.py`
   now owns the brief that fits a round's allowance, the brief's own
   omitted/conflict admissions, the bounded evidence request, the one
   sufficiency judgment, and the plan node bound. `run_planning` and
   `PlanningOutcome` stay in the waist - the ladder loop consumes those
   answers - and the moved names are re-exported so existing call sites and
   patches on `harness.waist.*` resolve unchanged. `waist.py` 1906 -> 1795
   lines.
2. **The first rail's `audit` failure was fixed at its cause, not routed
   around** - head `e5091f2` came back 15/16 with `audit` red on the module-map
   rule (`SD/D10`): every public harness module needs a row in
   `CONTRIBUTING.md`. The row landed in `ef6e2bc`; `sd_contributing` reads 1.0
   pass directly, and the full rail at the new head is 16/16.
3. **Register record landed** - PR #680, head `09197d6`, 16/16, merged as
   `0706f93c`. The #308 row names the merge SHA, what moved, what the waist
   keeps, and the two concerns still in the waist, so the row does not read as
   a finished split.
4. **Verify-then-skip on #660** - both acceptance lines were already built and
   filed on the issue by earlier passes; no duplicate work was started.

### Verification

- `tests/test_plan_lane_owners_308.py` gains a `harness.plan_evidence` owner
  entry and a control asserting `waist.<name> is plan_evidence.<name>` for
  every moved name: the loop calls the owner's objects, not a copy.
- Focused modules: 143 passed / 28 subtests and 201 passed / 27 subtests across
  the plan-owner, waist, planning-budget, execution-budget, composed-ceiling,
  stage-composition, brief and Jev-integration files.
- Full `tests/` on this branch: 7672 passed, 82 skipped, 1274 subtests, 0
  failed, 584.76 s (the environment-bound `test_local_fit_optional_ci_311`
  deselected locally; CI runs it and `audit` is green at the exact head).
- `ruff check harness tests/test_plan_lane_owners_308.py`: clean.
- Local 4-dimensional audit was started on the branch but had not finished
  `SD/D12` when this filing was written; it is not used as evidence, and the
  CircleCI `audit` at `ef6e2bc` is the authoritative read.

### NEXT

1. #308 remaining, named not built: the composed budget envelope
   (`composed_worst_case` / `_refuse_composed_ceiling`) and the tier-0 chunker
   (`chunk_oversized_nodes`) still live in the waist.
2. Then the next unworked W1 item in register order: #309 (separate domain
   evaluators from shared policy dispatch), whose #342 dependency has landed
   through PR #673/#675/#677.

### BLOCKERS

- #342's CLI/MCP native accepted/declined lifecycle receipt still needs a
  native Jev key; it is not substituted with fixtures.
- #344's resume-without-a-supplied-plan path cannot reuse its route decision:
  the checkpoint stores the plan hash and not the plan body (named schema gap).
- RSI #649-#652 remain parked by ruling; W469's window is externally clocked.

### WAIT-STATE

idle: none
