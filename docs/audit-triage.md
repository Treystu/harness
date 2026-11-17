# Hermetic / audit triage runbook

This is the runbook for telling an **environment** failure from a **real**
defect, and the disposition record for audit-measurement noise landed with
[#276](https://github.com/Sovereign-Communication/harness/issues/276). It was
extended for [#290](https://github.com/Sovereign-Communication/harness/issues/290)
with the two signatures that were still tribal knowledge (bare-`python` gates
and R13's environment leak) and with a check an operator can actually run for
each entry:

```bash
python -m harness.triage               # every check
python -m harness.triage --check ruff  # one check
python -m harness.triage --json        # machine readable
```

Each probe prints `ok`, `env-broken` or `code-broken`, and the expected result
in both worlds -- so the tables below are executable, not advice. Exit status is
1 when anything is environment-broken.

**Authority:** CI is authoritative: a failure in the CI `audit` job or the
hermetic test matrix is a defect until proven otherwise. A local-only failure
can be environment sensitive, but it is never dismissed by label. Reproduce it
with a scrubbed environment before deciding.

## Environment failure or code defect?

Ask these in order:

1. Does the same test fail in the CI hermetic suite? If yes, it is a code or
   test defect, not an environment signature.
2. Does it fail with an empty home, no provider keys, and no ambient
   `HARNESS_*` overrides? If it disappears under that setup, it is
   environment-sensitive.
3. Is the failure a missing external tool, not a finding? Use the named
   remediation below; do not skip or weaken the check.

## S5 — ruff resolution

**Signature:** `No module named ruff`, `ruff: command not found`, or an S5
failure that names the interpreter instead of a lint finding.

**The check:** `python -m harness.triage --check ruff`.

| world | expected output |
|---|---|
| environment-broken | `env-broken`, `ruff unresolved: ruff not found: put ruff on PATH, install the dev extra (pip install -e '.[dev]'), or set HARNESS_RUFF` |
| code-broken | `ok`, `ruff resolves via '<path>'` -- ruff is there, so the S5 line is a real lint finding |

**Disposition (2026-10-25):** S5 is an enforced check, not a skipped one. It
resolves ruff through the one owner in `harness.tools.ruff_argv`:
`HARNESS_RUFF` first, then `ruff` on `PATH`, then `<interpreter> -m ruff`. A
missing ruff now produces one named failure beginning `S5 ruff unresolved:`.
That is an environment/setup error with a direct fix:

```bash
python -m pip install -e '.[dev]'
# or point at an existing binary:
export HARNESS_RUFF=/path/to/ruff
```

Do not add a per-PR skip and do not label a genuinely reported lint finding as
infrastructure. If ruff is present and S5 fails, it is a real lint defect.

## D12 — merge-base changed-line coverage

**The check:** `python -m harness.triage --check d12`.

| world | expected output |
|---|---|
| environment-broken | `env-broken`, `baseline names '<sha>' but HARNESS_D12_BASE is '<sha>'` -- a hand-pinned baseline older than the merge-base |
| code-broken | `ok`, `no hand-pinned baseline; D12 resolves the merge-base`, and the audit then reports a ratio below 95% |

D12 no longer trusts a stored baseline SHA. At audit time it resolves the
runtime merge-base (`HARNESS_D12_BASE` in CI, otherwise `origin/main`), then
measures added executable `harness/` lines against coverage produced for the
current tree. If the committed fast-path coverage document does not name that
merge-base, the traced battery regenerates a temporary document. A manual
baseline re-point is not a pre-merge step.

- **No base or no coverage:** CI fails closed. Locally the audit prints a
  visible `SKIP (fail-open)` so an interactive run is not silently green.
- **Below 95%:** a real coverage gap; execute the added line with a real test
  or delete the unreachable line. Never lower the bar or hand-edit coverage.
- **Reproduce locally (Bash):**

  ```bash
  HARNESS_D12_BASE="$(git merge-base HEAD origin/main)" \
    python audits/self/audit.py --dim SD
  ```

  Measured wall-clock timing (not a "2-5 minute" quick check):
  - **D12 traced unittest battery vs 4-dimensional audit:** on CircleCI
    (`cimg/python:3.11`, ~7,043 tests), the full 4-dimensional `audit.py` run
    measured **11m 55s** (`714.85s`, build `4357`) to **12m 25s** (build `4353`).
    Nearly all of that time is the **D12** subprocess running the full test
    suite under stdlib `trace` (~11-12 minutes when regenerating coverage);
    all remaining deterministic checks (`A`, `R` excluding slow inner suites,
    `SM`, and `SD` `D1..D11,D13`) finish in under a minute unless live API checks
    (`HARNESS_AUDIT_LIVE=1`) are enabled. On a local Windows workstation
    (~7,045 tests), an untraced full battery takes ~8-10 minutes and a fresh
    D12 trace takes ~10-14 minutes.
  - **Progress output and abnormal-duration bar:** both
    `audits/self/audit.py` and `audits/self/refresh_coverage_baseline.py` stream
    elapsed progress timestamps so a slow run stays visibly alive. Treat a run
    as **abnormal / stalled** when it emits no progress for >10 minutes or
    exceeds **25 minutes** total (>2x the ~12m measured baseline, matching CI's
    `no_output_timeout: 20m`).
  - To reuse a prepared document, set `HARNESS_D12_BASELINE` to a JSON file
    whose `commit` is the same merge-base.

## Local-only `test_dogfood` / `test_hourglass_end_to_end`

**Known signature:** `tests.test_dogfood` or
`tests.test_hourglass_end_to_end` fails on a developer box while the CI
hermetic suite is green.

**Disposition:** environment-sensitive until reproduced cleanly. These lanes
touch provider/config/ledger seams that can inherit a developer's ambient
keys or files. Run:

```bash
python -m unittest tests.test_dogfood tests.test_hourglass_end_to_end -v
```

under an empty home and without provider keys. If the failure follows that
environment, record it here rather than weakening the test. If it also fails
in CI, treat it as a real defect and fix the cause.

## Bare-`python` gate failures (#278)

**Signature:** every gate in a task aborts with the same `no such file or
directory: python` / `FileNotFoundError: 'python'` shape, or a task ends
`gate_broken` on a machine where Python is plainly installed. The `python` alias
is absent (normal on several Linux distributions, and on a Windows box where only
`py` is on PATH) and a gate shelled out to the bare name, so every task fails
identically and nothing about the task is being measured.

**The check:** `python -m harness.triage --check python`.

| world | expected output |
|---|---|
| environment-broken | `env-broken`, `resolved '<path>' but no `python` on PATH` -- the resolver works, the alias does not |
| environment-broken (no interpreter at all) | `env-broken`, `no interpreter resolved (...)` |
| code-broken | `ok`, `resolved '<path>'; bare alias present` -- so a gate that still fails bypassed the resolver |

**Fix:** gates resolve through `harness.tools.resolve_python()` (`HARNESS_PYTHON`,
then the running interpreter, then a PATH name) and `resolve_gate_argv` rewrites
only a bare interpreter token, leaving an explicit path alone. If a gate still
shells out to a bare `python`, that call site is the defect: fix the call site,
do not add a `python` shim to the machine.

## R13 — the environment reaching a hermetic run

**Signature:** the audit's hermetic suite fails locally while CI's is green, the
failure moves between runs, or it names a model id / provider / routing lane.
Two independent leaks produce it: the operator's key and routing variables (a
live key un-skips the opt-in catalog check, so the audit fails on upstream drift;
routing knobs change which lane a test takes, so a local green is not the green CI
sees), and the operator's home directory, where a key is also resolved from files
-- on Windows `USERPROFILE` overrides a cleared `HOME`.

**The check:** `python -m harness.triage --check hermetic`.

R13 drops ten variables; a local run must show none of them:

```
HARNESS_USE_FREE HARNESS_ALLOW_ESCALATION HARNESS_MAX_COST HARNESS_TASK_MAX_COST
HARNESS_MIN_CONFIDENCE HARNESS_JEV_KEY TYPESAFE_API_KEY JEV_API_KEY
OPENROUTER_API_KEY OPENROUTER_API_KEY_FILE
```

| world | expected output |
|---|---|
| environment-broken | `env-broken`, `N ambient variable(s) reach the run: ...` |
| code-broken | `ok`, `no key or routing variable from the drop list` -- and the failure persists |

**Fix:** run the suite through the wrapper, which scrubs those variables *and*
points `HOME`/`USERPROFILE`/`APPDATA`/`XDG_CONFIG_HOME` at an empty directory:

```bash
scripts/hermetic-env.sh "$(git rev-parse --show-toplevel)" -- python -m unittest tests.test_dogfood -v
```

A local-only failure is never dismissed by label: reproduce it under that
wrapper, and a failure that survives it is a real defect.

## Real-defect signs

- The same assertion fails in the hermetic CI matrix.
- S5 fails while `python -m harness.triage --check ruff` says `ok`.
- A gate fails while `--check python` says `ok` (the gate bypassed the resolver).
- D12 reports a real ratio below 95% while `--check d12` says `ok`.
- Ambient variables are clean (`--check hermetic` says `ok`) and the failure
  persists under `scripts/hermetic-env.sh`.
- A local failure survives a clean-home, no-key reproduction.

For those, file the defect against the owning module; do not relabel it as
audit infrastructure.
