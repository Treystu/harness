## Lane 1 check-in - 2026-11-22, pass 9 (LD-002: #344 plan binding landed)

**Base read at start:** `main` `bd0b84a0ff97697abf740a90865689d410b83245`, zero open PRs, 40 open issues.
**Head at the end of this pass:** `main` `0dfedf1` (PR #671, then register PR #672).

Comm lock: #295 read at turn start and re-read before this filing; no new
Treystu directive and no STOP. This pass continued the filed order from pass 8:
the #344 remainder that pass 8 recorded as unblocked.

### DONE

1. **#344 approved-plan/receipt binding landed** - PR #671, head `f1d98edd`,
   16/16 at that exact head including `audit`, squash-merged as `a7066201`.
   The checkpoint records `approved_plan_hash` and `plan_approval`; reuse
   requires the live `ResearchPlan.hash()` to match, the recorded receipt to
   be native and an `accept` for that hash, and any live approval to name the
   same plan. Eight refusal reasons are typed, and a checkpoint written before
   plan binding keeps its request-only binding.
2. **Register corrected in a separate PR** - PR #672, head `c49e280e`, 16/16
   at that head, merged as `0dfedf1`. The #344 row names the binding and the
   one remaining gap: no lifecycle path proposes a plan yet. Census stays 40.
3. **Verified, not asserted** - 10 new tests (8 predicate outcomes, 2 adapter
   controls), 219 passed in the affected set, changed-line coverage 31/31 on
   the touched harness files by the audit's own statement rule, ruff clean.

### WIP

- **#342 stays OPEN.** Its remaining slice is the lifecycle proposer plus the
  `render_site_evidence` gate. **#344 stays OPEN** until that proposer
  supplies a plan on the live path.

### NEXT

1. #342's lifecycle proposer: propose a plan before retrieval in
   `run_hourglass_request`, gate `render_site_evidence` on the same accepted
   plan, and pass the plan into the checkpoint the #344 binding now compares.

### BLOCKERS

- A CLI/MCP native accepted and declined lifecycle receipt for #342 needs a
  native Jev key; it is not substituted with fixtures.

### WAIT-STATE

idle: none.
