## #569 landing evidence - the held-write block says what is held and what to do

#569 reported three defects in one block: it printed the gate's internal state
token at the operator, it said "Review the planned changes above" when no change
was ever shown, and it offered no actionable next step. All three are cured on
`main` today. This filing names where, proves it from primary sources, and fixes
the register row that still read `OPEN | none`.

The issue carried **zero comments** before this one, so the cure had no evidence
path even though it shipped. That is the gap this filing closes.

### What the cure is

`harness/lifecycle_guards.py` on `main` (`b35cab9d`):

- `_GATE_REASON_TEXT` maps the four recognized gate reasons to
  `(what is held, what to do next)` in operator language - so
  `no_evidence_cited` now reads "the plan cites no evidence for the change it
  wants to make" and "Name the file and line the change is grounded in ... then
  send the request again."
- `_CONSENT_REASON_MARKERS` recognises the consent-hold shape structurally, so the
  long resumable-stage-runner sentence in the report becomes "the consent recorded
  for this assignment no longer covers it, because the assignment changed after
  consent was given" with "Renew consent for this assignment, then send the request
  again."
- `_operator_reason` returns `(sentence, next_step, support_code)`; the raw token
  survives only as a `Support code:` line for an unrecognised reason, so the report
  stays diagnosable without making the operator read machine state.
- `render_gate_guard(reason, has_write, *, planned=None, paths=None)` emits
  **What is held**, **What would change** (the named paths, or an honest "no file
  was named by the plan, so there is no change list to show"), and
  **What to do next**. The old "Review the planned changes above" sentence is gone.

Blocking behaviour is unchanged: `has_write=False` still returns `""`, so a
read-only run never sees a file-write block.

### The call site actually passes the change surface

The report's third complaint was that the instruction pointed at changes that were
never shown. One production caller exists, and it now hands the block the surface
it has in hand - `harness/execution_stages.py`, the refused-edit path:

- `surface` is built from `target_files`, then from every
  `node["target_files"]` / `node["targets"]` in `plan["dag"]["nodes"]`, deduped;
- `render_gate_guard(reason, has_write_surface(target_files, plan.get("dag")), paths=surface)`;
- one `dedupe_notices` pass, so the response carries exactly one guard block.

`tests/test_lifecycle_guards_204_205_206.py::RefusedEditIntegrationTests` drives
that path through `_refused_edit` and asserts the DAG target appears in
**What would change**.

### Where it landed

PR #644, merge commit `a4dd345e` ("fix(flush): wire the campaign trace writer at
the product entry (#469)"). The #569 cure rode in with that PR rather than one
named for the issue - which is why the issue looked untouched while `main` was
already carrying the fix. Read at `main` `b35cab9d`:
`git show treystu/main:harness/lifecycle_guards.py` contains `_GATE_REASON_TEXT`,
`_operator_reason` and the three-part `render_gate_guard`.

### What was run at this head

- `tests/test_lifecycle_guards_204_205_206.py` plus `tests/test_agent.py`:
  **188 passed, 2 subtests passed** (12.29 s).
- The guards module's own coverage of the reported shapes: internal token absent
  from the operator text, "Review the planned changes above" absent, held paths
  listed, no-change-named case says so, consent hold translated without the raw
  reason, unknown reason kept only as a support code, identical blocks deduped.

### Register

`docs/jev-roadmap.md` W7 listed #569 as `OPEN | none`. PR #717 now records the
landing with its SHA, module and test, alongside the same correction for #568
(PR #613, merge `6d13eb9`) and #474 (record-and-close, 2026-11-20). The rows stay
`OPEN`: per the standing rule the owner closes issues, and this filing takes no
close.

### What this filing does not claim

- It does not claim a live agent session reproduced the operator-visible block.
  The evidence is the rendered function, its one production call site, and the
  tests over both.
- It does not claim the cure is complete for reasons outside the four mapped
  entries and the consent shape: an unrecognised future gate reason still renders
  the generic sentence plus a support code. That is the deliberate fallback, not a
  measured cure for those tokens.
