# Hermetic / audit triage runbook

This is the disposition record for audit-measurement noise landed with
[#276](https://github.com/Sovereign-Communication/harness/issues/276), extended
to [#290](https://github.com/Sovereign-Communication/harness/issues/290)'s full
scope: a local failure that presents as a real one, triaged through the
interpreter, ruff (S5), merge-base coverage (D12), and the hermetic suite
(R13).

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

## Bare `python` — a gate that shells out to an alias the host lacks

**Signature:** a gate or audit step dies with `'python' is not recognized`,
`python: command not found`, or `[Errno 2] No such file or directory:
'python'` before any test runs. Python 3-only hosts (most macOS and Linux
distributions, and any image that installs only `python3`) have no `python`
alias, so a command written literally as `python check.py` never starts.

**Distinguishing check:** compare the resolved names on the host.

```bash
command -v python   # empty on a python3-only host
command -v python3  # resolves
```

- **Environment-broken:** `python` is empty, `python3` resolves, and the
  failing step's first line is the interpreter error rather than an
  assertion. Nothing about the tree is wrong.
- **Code-broken:** the interpreter resolves and the gate's own assertion
  fails afterwards. That is a real defect; do not relabel it.

The one owner is `harness.tools.resolve_python`: `HARNESS_PYTHON` when set,
then the running interpreter (`sys.executable`), then `python`, `python3`,
`py` on `PATH`. It raises one named error, `no Python interpreter found: ...`,
when every rung is missing. Point it at an interpreter instead of adding an
alias that only exists on your machine:

```bash
export HARNESS_PYTHON="$(command -v python3)"
```

A gate that names an absolute interpreter is left alone by
`resolve_gate_argv`, so a venv path or a pinned `C:\\...\\python.exe` keeps
working.

## S5 — ruff resolution

**Signature:** `No module named ruff`, `ruff: command not found`, or an S5
failure that names the interpreter instead of a lint finding.

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

  The traced battery is the slow part (roughly two to five minutes). To reuse
  a prepared document, set `HARNESS_D12_BASELINE` to a JSON file whose
  `commit` is the same merge-base.

## R13 — full suite green hermetically

**Signature:** the local audit's R13 row fails, or a suite is not green, while
the CI hermetic matrix is green for the same commit. The common cause is not a
defect: the audit's suite child inherited the operator's routing and key
environment, so it ran a different check than CI ran.

R13 scrubs two leaks, and only the first is visible in `os.environ`:

- **Environment.** Routing knobs are dropped before the child starts
  (`HARNESS_USE_FREE`, `HARNESS_ALLOW_ESCALATION`, `HARNESS_MAX_COST`,
  `HARNESS_TASK_MAX_COST`, `HARNESS_MIN_CONFIDENCE`) along with the key
  variables (`HARNESS_JEV_KEY`, `TYPESAFE_API_KEY`, `JEV_API_KEY`,
  `OPENROUTER_API_KEY`, `OPENROUTER_API_KEY_FILE`). A key left in place turns
  the opt-in live-catalog check on, so the audit can fail on upstream drift (a
delisted model id) that has nothing to do with this tree.
- **The user's home.** A key is also resolved from files under `~`
  (`.config/scmorc/openrouter_fusion.env`, `.config/scmorc/openrouter.env`,
  `.config/harness/openrouter.env`, `.config/harness/jev.env`), and
  `harness.config.CONFIG_DIR` itself is derived from `~`. No environment scrub
  can reach those, so the child gets a fresh empty home (`HOME`,
  `USERPROFILE`, `APPDATA`, `XDG_CONFIG_HOME`).

**Distinguishing check:** the row self-verifies its classifier (R14), so a
failing R13 with a passing R14 means the child's output was classified
correctly and the suite really is not hermetic on this machine. `--dim` takes
only the registered dimensions (`A`, `R`, `SD`, `SM`); R13 and R14 both live
under `R`.

```bash
python audits/self/audit.py --dim R
```

- **Environment-sensitive:** `Ran N tests` / `OK` with a leak signature in the
  captured stderr (`ResourceWarning`, `unclosed file`), or a live-catalog
  failure naming an upstream model id. Reproduce with an empty home and no
  provider keys; if it clears, record the environmental cause here.
- **Real defect:** the assertion fails in the CI hermetic matrix too, or the
  leak signature survives the scrub. Fix the leak; never drop the signature
  scan or add a skip.

`HARNESS_LEDGER` is deliberately not scrubbed: the suite pins its own
temporary ledger in `tests/__init__.py`, and a caller that set a private one
is already isolated.

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

## Real-defect signs

- The same assertion fails in the hermetic CI matrix.
- A gate fails on a bare `python` even though `resolve_python` resolves an
  interpreter (the named `no Python interpreter found` error is the only
  environment signature there).
- S5 fails while ruff is resolvable.
- D12 reports a real ratio below 95% on current-tree coverage.
- R13 is not green after the environment and home scrub.
- A local failure survives a clean-home, no-key reproduction.

For those, file the defect against the owning module; do not relabel it as
audit infrastructure.
