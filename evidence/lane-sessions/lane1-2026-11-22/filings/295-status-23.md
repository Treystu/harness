## Lane 1 check-in - 2026-11-23, pass 14 (LD-002: #308 composed budget owner landed)

**Base read at start:** `main` `0706f93ce4981752145c674df812cb3df133ed0e`, zero
open PRs, 40 open issues (live count).
**Head at the end of this pass:** `main` `10ad3e54c0ec0290e72e6539ff82f96311182a4a`
(PR #681, then register PR #682). Zero open PRs, 40 open issues (live count),
tracked tree clean.

Comm lock: #295 read at turn start and re-read before this filing; no new
Treystu directive and no STOP. The newest comment is oversight tick 836, which
records the lane as silent for two ticks; this pass continues the filed order
from pass 13's NEXT rather than re-deriving it.

### DONE

1. **#308 composed budget envelope owner landed** - PR #681, head `f9ed95fd`,
   16/16 at that exact head including `audit`, squash-merged as `070071f3`.
   `harness/plan_budget.py` now owns the one worst-case number the plan lane
   checks before execute spend (node ceilings plus every unincurred stage
   against `governor.remaining()`), the plan-ceiling comparison, the
   fail-closed refusal envelope, and `DECOMPOSE_MAX_TOKENS`. `compose_plan`
   stays in the waist and still decides when to ask and what a refusal means;
   the owner's names are re-exported, so `harness.waist.composed_worst_case`
   patches resolve unchanged. The ladders stay in the waist (lanes patch them
   there) and the owner resolves them at call time, so those patches still
   reach the numbers. `waist.py` 1795 -> 1647 lines.
2. **The first rail's `audit` failure was fixed at its cause** - head
   `06ac01f2` came back 15/16 with `audit` red on `SD/D12` changed-line
   coverage: the new owner measured 80% (the 95% bar is unchanged) because its
   degradation branches were untested. `BudgetOwnerDegradationTests` exercises
   the unpriceable-call, malformed-ceiling, unreachable-ladder and unreadable
   governor-limit branches, each of which must price at $0.0 rather than
   inventing a number, taking the owner to 88/88 statements. The rail at the
   new head is 16/16. No check was weakened or skipped.
3. **Register record landed** - PR #682, head `10ad3e54`, 16/16, merged as
   `10ad3e54`. The #308 row names both merge SHAs, what moved, why the ladders
   stayed, the D12 failure and its fix, and the one concern still in the waist,
   so the row does not read as a finished split.
4. **Stale local audit side effect cleaned** - the local 4-dimensional audit
   from pass 13 finished at `AUDIT_EXIT=1` (R13 on the two environment-bound
   tests, D12 skipped locally as a platform gap) and rewrote the tracked
   `audits/self/round2_scores.json`; that write was reverted, and the tracked
   tree is clean. It is not used as evidence.

### Verification

- `tests/test_plan_lane_owners_308.py` gains a `harness.plan_budget` owner
  entry plus a control asserting the waist holds the owner's objects
  (`composed_worst_case`, `_refuse_composed_ceiling`, `DECOMPOSE_MAX_TOKENS`)
  rather than copies.
- Focused modules (plan owners, composed ceiling, extra coverage, stage
  composition, end-to-end, consensus, reserve/call parity): 101 passed, 39
  subtests, 0 failed; the new degradation cases bring `plan_budget.py` to 88/88
  statements under coverage.
- Full `tests/` on the code at the final head: 7673 passed, 82 skipped, 1280
  subtests, 0 failed, 570.87 s (the environment-bound
  `test_local_fit_optional_ci_311` deselected locally; CI runs it and `audit`
  is green at the exact head).
- `ruff check harness/ tests/test_plan_lane_owners_308.py`: clean.
- CircleCI at `f9ed95fd`: 16/16, 0 pending, 0 bad; at `10ad3e54`: 16/16.

### NEXT

1. #308 remaining, named not built: the tier-0 chunker (`chunk_oversized_nodes`
   with its split/reserve helpers) still lives in the waist.
2. Then the next unworked W1 item in register order: #309 (separate domain
   evaluators from shared policy dispatch in `harness/jev_policy.py`), whose
   #342 dependency has landed through PR #673/#675/#677.

### BLOCKERS

- #342's CLI/MCP native accepted/declined lifecycle receipt still needs a
  native Jev key; it is not substituted with fixtures.
- #344's resume-without-a-supplied-plan path cannot reuse its route decision:
  the checkpoint stores the plan hash and not the plan body (named schema gap).
- RSI #649-#652 remain parked by ruling; W469's window is externally clocked.

### WAIT-STATE

idle: none
