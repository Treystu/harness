## LANE 1 CONFIRMATION - PR #685 rail regression: failing tests named

Order item 2 of the genuine-issue burn (comment 7126399412) owed one
confirmation act: name the tests failing on PR #685's rail, and say whether
the regression touches code bound for main. Both are below. Lane 1 made no
edit to the branch - fixes stay with the standup lane under #684 census row
7126296790.

### Rail state (as dispatched, primary source still unreadable here)

CircleCI pipeline 1057 failed at head `3a3ce6db`; green bracket 1024 on
`47735e7e`, red from 1027 on `2591be98`. No CircleCI API token is available
in this lane: `repos/Treystu/harness/commits/<sha>/statuses` returns no job
detail, the job endpoint 404s, and the public API read timed out. The names
below therefore come from reproducing the hermetic leg at the exact head, not
from job logs, and are reported as reproduction rather than a log quote.

### Reproduction at the exact head

`git archive 3a3ce6db` into a scratch tree (no branch or file touched),
then the CI's own hermetic command under Python 3.11:

```
python -W error::ResourceWarning -m unittest discover -s tests
Ran 7880 tests in 603.114s
FAILED (errors=5, skipped=89)
```

### The failing tests

Deterministic - reproduced standalone in `tests/test_freebuff_watch.py`
(4 failed, 46 passed), all with the same raise:

| Test | Failure |
|---|---|
| `FreebuffWatchTests.test_missing_driver_runtime_is_refused_by_name_before_a_claim` | `assertIsNone(watch.require_driver_runtime())` raises `RuntimeError: driver runtime missing: windows_capture, PIL` |
| `FreebuffWatchTests.test_interrupted_items_skip_to_next_unclaimed_row` | `watch.run_burn(...)` raises at `windows_freebuff_watch.py:445` |
| `FreebuffWatchTests.test_poll_dynamic_dispatches_executes_unclaimed_restart_and_parks_antigravity` | `watch.poll_dynamic_dispatches(...)` raises at `windows_freebuff_watch.py:368` |
| `FreebuffWatchTests.test_scm_timeout_cure_is_admitted_after_vision_seat` | `watch.run_restoration(...)` raises at `windows_freebuff_watch.py:739` |

Order/environment-sensitive - observed only in the full discover run, passes
standalone on `main` (13 passed) and is not attributable to the fix commit:

| Test | Failure |
|---|---|
| `CommandWiringTests.test_desktop_command_opens_its_own_log` (`tests/test_serve_log_574.py`) | `AttributeError: '_Thread' object has no attribute 'is_alive'` inside `subprocess.communicate` from `serve_identity` -> `_git_describe`; suite-order interaction, reported for completeness, not named as the rail failure |

### Root cause (primary source)

Commit `1391be24` - "fix(driver): refuse by name when the driving runtime is
absent" - added `require_driver_runtime()` and calls it inside `run_burn`
(`scripts/windows_freebuff_watch.py:445`), `poll_dynamic_dispatches` (:368)
and `run_restoration` (:739). The commit added one test for the gate and did
not update the three tests that drive those entry points, so each now raises
before doing the work it asserts. Its own new test asserts the runtime is
present (`assertIsNone(...)`), which cannot hold on the Linux rail at all:
`RUNTIME_MODULES` includes `windows_capture`, a Windows-only module.

The gate itself is correct behaviour for a real dispatch; the defect is that
it is unconditional for every caller and its tests either do not stub it or
require a runtime the CI image cannot provide.

### Main relevance: yes

Both files exist only on `laptop-vision-20261122`, and both are driver-cure
code intended for `main` - the watch is the layer the owner's overnight order
makes Lane 1 responsible for once the standup lane stands down. Nothing on
`main` (51f7af64) contains the gate, so `main` is not red for this.

### Cure shape (for the branch's single editor, not applied here)

- The three existing tests stub `require_driver_runtime` the same way they
  already stub `execute`/`checkpoint`/`desktop_idle`; the gate then still
  fires in the paths that mean to test it.
- The gate's own test asserts the refusal in a runtime-absent state and
  asserts a runtime-present state only when the modules are actually
  importable (or stubs `find_spec` for both branches), so it is meaningful on
  a Linux runner.

### Gate

Decision-class filing. Receipt recorded beside this artifact; verdict and
disposition above follow it.
