## Lane 1 check-in - 2026-11-23, pass 15 (LD-002: #308 tier-0 chunker owner landed; the split is complete)

**Base read at start:** `main` `10ad3e54c0ec0290e72e6539ff82f96311182a4a`, zero open PRs, 40 open issues (live count).
**Head at the end of this pass:** `main` `1cb0b6423b3963dbf16979e95744a91ca8f5efa5` (PR #686, then register PR #687). One open PR (#685, the laptop driver's draft, not this lane), 42 open issues (live count), tracked tree clean.

Comm lock: #295 read at turn start and re-read before this filing; newest is
the tick-846 stall nudge (`7090305725`) plus the laptop driver's filings.
No new Treystu directive and no STOP; nothing supersedes the filed order.
The stall episode is closed by this pass's activity: two merges and this
check-in.

### DONE

**1. #308 - the tier-0 chunking policy now has its own owner.**
PR #686 squash-merged to `b3b91dd6ab509d05393086a606b8a8631dd34119` at head
`be39d8d7419ef983095e584c0458ea0c4194ffce`. New
`harness/plan_chunker.py` owns `single_pass_output_tokens`, `_split_text`,
`_target_text`, `_passes_to_read`, `rung_read_budgets`, `_line_ranges`,
`chunk_oversized_nodes` and `_slice_marker`. The waist keeps
`_fit_plan_to_single_pass` (the wrapper that applies the policy to a plan
result and re-derives node details through `plan_task` when the DAG changed)
and re-exports every moved name through `_COMPAT_308`, so
`from harness.waist import chunk_oversized_nodes` and every patch on
`harness.waist.*` resolve to the owner's objects; `tests/
test_plan_lane_owners_308.py` asserts that identity, that the waist does not
redefine an owned concern, and that no concern module imports the waist at
module scope. `waist.py` 1647 -> 1395 lines; `plan_chunker.py` 293 lines.
`CONTRIBUTING.md` carries the module-map row and `docs/architecture.md` the
owner bullet. No #308 concern remains in the waist.

**2. Rail and tests for #686.**
Rail read per context at the exact head `be39d8d7`: 16 of 16 `success`,
zero pending, zero failing, `audit` last to finish. Full `tests/`:
7716 passed, 82 skipped, 1295 subtests, one failure - the known local-only
`test_local_fit_optional_ci_311` fixture check (it reads the untracked
`audits/scmessenger/_runs`); CI `audit` at the head is the authority and it
was green. Focused set (8 files incl. `test_waist`, `test_plan_chunker`,
the #308 owner test and the three hourglass suites): 252 passed, 54
subtests. Changed-line coverage of the new owner measured with the traced
recipe before the first push: `harness/plan_chunker.py` 134 statements, 0
missed (100%), which is why this head did not repeat #681's D12 failure.
`ruff` clean.

**3. Register record.**
PR #687 squash-merged to `1cb0b6423b3963dbf16979e95744a91ca8f5efa5`; the
`#308` row in `docs/jev-roadmap.md` now names the chunker owner, the moved
helpers, the compat re-export, the line counts, the coverage measurement
and the rail head, and states that the split has no remainder. Its own rail
was 16/16 at `d9f61711`.

### WIP
Nothing. No branch is in flight.

### NEXT
1. **#309** - separate the domain evaluators from the shared policy
   dispatch in `harness/jev_policy.py` (~3930 lines); its #342 dependency
   has landed. Same method: read the module, cut one concern at a time into
   its own owner, keep the compat surface, measure changed-line coverage
   before the first push.
2. Then the W1 order: #310, #337, #313, #318, #319, #280, #281, #289, #277,
   #517, #380, #381, #382, #314, #291.

### BLOCKERS
- #342's CLI/MCP native accepted/declined lifecycle receipt still needs a
  native Jev key; not substituted with fixtures.
- #344 resume without a supplied plan cannot reuse its route decision: the
  checkpoint stores the plan hash but not the plan body (named schema gap).
- RSI #649-#652 stay parked; the W469 window is externally clocked.

### WAIT-STATE
idle: none
