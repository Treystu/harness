# Lane evidence — PR #547 changed-line coverage (2026-11-15)

**Item:** PR #547 — the #538-#544 never-defer bundle, head `c048c83`,
whose CircleCI `audit` context fails on rule D12 (changed-line coverage).

**Delivery state:** READY-TO-MERGE as a stacked cure. This branch is based on
the PR head, not on `main`; merging it into `freebuff/harness-assist-lane-burndown-mission`
is the intended landing, after which #547's own audit reads the tree measured
below. No pull request could be opened from this lane: the cloud environment
carries repository read/fetch/push only, and the unauthenticated REST budget
for this VM's address is exhausted (HTTP 403, `x-ratelimit-remaining: 0`), so
there is no PR body, no comment and no ledger filing. This record replaces them.

**Branch:** `lane/cloud-547-coverage`
**Measured tree:** `70a4123116d12d622e7f3544cefe442f42c87fd6` (the test commit)
**Base:** `9959b16d69be571a01c61fb2479481401223e735` (`origin/main` at census
time; identical to `git merge-base origin/main c048c83`, so the measured diff
is #547's own 432 added executable `harness/` lines and nothing from `main`).
**Branch tip:** the commit carrying this record — read it from the remote
(`git ls-remote origin refs/heads/lane/cloud-547-coverage`); a record cannot
name its own commit without going stale when it is written.

## Rail

**RAIL-UNVERIFIED.** No CircleCI status is readable from this lane, and a
combined status would not be evidence anyway. The head oversight must read is
the CircleCI `audit` job (context `audit`, job display name `audit`) on the
branch tip of `lane/cloud-547-coverage`, whose SHA is what
`git ls-remote origin refs/heads/lane/cloud-547-coverage` prints. Nothing in
this record is presented as rail evidence.

## The defect, measured

D12 diffs `harness/` against the runtime merge-base and requires every added
executable line to be executed by the traced battery. On `c048c83` it is not:

```
changed-line coverage 345/432 = 79.86% (bar 95%)
vs merge-base 9959b16d69
untested: availability.py:67,128,131,135,150,171,216,221,237,251,325,...
          chat_policy.py:142,163
          conversation_lifecycle.py:216,218
          edit_lifecycle.py:192,251,252,265,266,267,268,270,271,272,...
          hourglass_lifecycle.py:172,174,175,214,216,224
          panel.py:112,114,115,117,118,121,367,369,370,371,378,382,383,385
          simple_answer_lifecycle.py:273,276
          waist.py:605,612,613,614,616,618,620,621,624,625,626,627,629,630,631,641,1768
          workspace.py:56,57,58
```

The bundle shipped behaviour tests (`tests/test_never_defer_cluster.py`,
`tests/test_availability_routing.py`, and the panel/lifecycle additions) but
not the branch seams around that behaviour: a corrupt ledger document, a dry
judge or vote seat, a salvage that has to normalise a mapping, a detour that
gathered nothing usable, the edit lane's replay boundary, the generation
fallback, and the operation-time workspace gate.

## The cure

One new module, `tests/test_never_defer_cluster_cover.py` (29 tests), each case
a contract of the shipped code rather than a line touch:

| Area | Case |
| --- | --- |
| `availability.py` | corrupted/shapeless documents degrade to memory; a failed save keeps the verdict; an expired verdict is dropped on read; a probe for an unrecorded model is a no-op; an unclassified verdict excludes only its model; a provider-wide verdict excludes sibling paid routes but not a `:free` one; `cerebras/` routes name their provider; the `HARNESS_AVAILABILITY_OFF` switch, an unusable config dir, and a bad TTL each resolve honestly |
| `panel.py` | a dry judge seat returns `provider_unavailable` with no bill and a ledger row; a refused vote seat is recorded and the panel rotates |
| `waist.py` | empty bodies, python-literal spans, `nodes` mappings, non-literal spans, rejected node lists and rejected recovered-node cycles |
| `hourglass_lifecycle.py` | an artifact request never opens a detour; a detour whose every source returned 0 chars is aborted and recorded |
| `simple_answer_lifecycle.py` | a Jev-suggested detour on an artifact request is dropped and the build path runs with `web=False` |
| `edit_lifecycle.py` | a dry plan backend is re-derived twice and named `unservable_backends`; an unscoped request falls back to the conversation lane |
| `workspace.py` | the operation gate keeps the one desktop message; a real root resolves |
| `chat_policy.py` | an empty prompt is not an artifact request |

No audit rule was weakened: `audits/self/audit.py`, the 95% bar, the baseline
rotation and `coverage_baseline.json` are untouched, and no coverage document
is committed or hand-edited.

## Evidence on the measured tree

| Check | Result |
| --- | --- |
| Full hermetic battery, traced (`audits/self/refresh_coverage_baseline.py --ref 9959b16 --out …`) | Ran 6520 tests in 483.7s — OK (skipped=38); coverage document written |
| D12, computed by the audit's own `_coverage_ratio` over that document | `424/432 = 98.15%` (bar 95%) |
| `audits/self/audit.py --dim SD` with `HARNESS_D12_BASE`/`HARNESS_D12_BASELINE` | D1-D13 all `pass`; D12 `pass`; SD 10.00/10 |
| D12 evidence string | `changed-line coverage 424/432 = 98% (bar 95%) vs merge-base 9959b16d69 … untested: availability.py:339,352; chat_policy.py:142; conversation_lifecycle.py:216,218; edit_lifecycle.py:361,371; waist.py:1768` |
| `ruff check harness tests examples/oc_handoff driver_core` | All checks passed |
| Focused suites (`tests.test_never_defer_cluster_cover`, `tests.test_never_defer_cluster`, `tests.test_availability_routing`, `tests.test_panel_jev_primary`) | Ran 81 tests — OK |

The eight lines D12 still reports are:

- `availability.py:339,352` and `chat_policy.py:142` are `global`
  declarations, and `waist.py:1768` is `nonlocal` — compile-time statements
  that emit no trace event, so no test can ever execute them. They are
  measured lines, not untested behaviour.
- `conversation_lifecycle.py:216,218` (the availability-failure `record_error`
  call in the ladder's `except`) and `edit_lifecycle.py:361,371` (the
  cancellation re-raise and the non-availability re-raise) are live arms this
  cure did not need: the module clears the bar without them.

## Not checked

- Any CircleCI status on this head or on the PR head — RAIL-UNVERIFIED.
- The Windows and macOS legs of the matrix; only the Linux interpreter set
  (3.9/3.11/3.13 provisioned with `uv`) plus the 3.12 default exists here.
- The UI Playwright leg and the `ui-coverage.json` merge, since the audit job
  consumes them from a workspace this lane cannot produce.
- A second, non-author reviewer verdict: none is reachable from here.

## Environment note for the next lane

The traced battery aborts (and D12 therefore fails closed) on a machine where
`uv` is present but has no managed CPython 3.9/3.11/3.13: `tests/test_release_driver.py`
then fails its matrix assertion. `uv python install 3.9 3.11 3.13` is what
CircleCI's `install_tooling` step provides, and it is what made the battery
green here.
