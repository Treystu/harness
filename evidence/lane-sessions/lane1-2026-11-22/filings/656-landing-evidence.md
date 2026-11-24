# #656 — Hourglass test isolation guard, the contamination count, and the cleanup script

Lane 1, 2026-11-24. Item from the filed order: the test-isolation defect, three
parts as the issue states them. Reverify receipt was main `280ee3d4`.

## What the reverify receipt asked for

1. A conftest-level guard pointing `HARNESS_HOME` (and any ledger path) at an
   ephemeral directory for the whole session, so a test that forgets its own
   isolation cannot write the live operator home.
2. A current contamination count from the laptop operator DB (test-run rows vs
   total), filed on the issue.
3. A cleanup script that removes identified test rows from an operator DB,
   dry-run first, with the count it removed reported.

## Part 1 — the guard

The receipt named a `conftest.py`, but this suite runs under
`python -m unittest discover -s tests` (`.circleci/config.yml:116`) with no
pytest and no `tests/conftest.py`; a conftest would never load in CI. The
suite's existing per-process isolation seam is `tests/__init__.py`, which
already pins `HARNESS_LEDGER` before any test builds a ledger (#128,
`DF-LEDGER-2`) and is imported during discovery. The guard goes there, in the
same form and for the same reason:

- `HARNESS_HOME` -> `<temp>/harness-test-home-*/home`
- `HARNESS_CONFIG_DIR` -> `<temp>/harness-test-home-*/config`

Both are deliberately *overridden* when ambient, exactly as `HARNESS_LEDGER` is:
a test run pointed at a live lane's state is the failure, not the intent.

What this closes, concretely:

- `harness/history.py:88` saves turns under `get_default_history_dir()`
  = `get_config_dir()/chat_history`, and `harness/history.py:182` calls
  `remember_turn`, which projects into
  `$HARNESS_CONFIG_DIR/chat_history/conversation_memory.json`
  (`harness/conversation_context.py:91`). That file is how the suite reached the
  operator's real memory.
- `harness/serve_log.py:38` resolves `~/.harness/logs/serve.log`, so the same
  home pin also keeps the serve log out of the operator tree.

`tests/test_home_isolation.py` pins all of it: the env values, that
`get_config_dir()`, `default_log_path()` and `get_default_history_dir()` all
land outside `~/.config/harness` and `~/.harness`, and that a single-module
subprocess run inherits the pin (so it is per process, not a side effect of
discovery order).

## Part 2 — the count, measured on the laptop operator DB

Primary source, read on 2026-11-24 from
`C:\Users\SCM\.config\harness\chat_history\conversation_memory.json`:

| Measure | Value |
|---|---|
| Facts in the durable memory document | 1163 |
| Sessions recorded | 15 |
| Facts sharing the live `default` session id | 1152 |
| **Facts identified as test-run rows (scratch/tempfile paths)** | **1117 (96.0%)** |
| Durable facts kept | 46 |

Before the guard, the file's `path` facts were dominated by `tempfile`
fixtures: `...\AppData\Local\Temp\tmp<8>\provision-host`, its
backslash-doubled escaping twin, the audit's own
`...\Harness\audits\self\_runs\tmp\tmp<8>\provision-host`, and `uv` build-cache
`.tmpXXXXXX\Scripts\python.exe` paths. The historical figure on the issue was
3766 of 5254 (71.7%); the current document is smaller and more contaminated.

Identification rule, and why it needs no per-test history: a fact value is a
test row when any path component is shaped like a `tempfile.mkdtemp` directory
(`^\.?tmp[A-Za-z0-9_]{6,}$`, e.g. `tmpqblv6fo2`, `.tmpRjtqKW`) or when the
resolved path is under an OS temp root. Scratch directories do not survive a
reboot or a cleaned cache, so they are never durable operator memory. A real
path containing a component spelled `tmp` plus six characters is the one
possible false positive, and the script's backup makes that recoverable.

## Part 3 — the cleanup script

`scripts/clean_memory_contamination.py`:

- dry run by default: prints `would remove N test-run row(s), keeping M`, writes
  nothing, leaves no file behind;
- `--apply` copies the document to `<name>.bak-<UTC stamp>` first, then rewrites
  it atomically (temp file + `os.replace`), and prints the count and the backup
  path;
- a second run removes 0 (idempotent);
- refuses a `ledger.jsonl`, because the ledger is a hash-chained evidence store
  and editing it would break the chain -- only the memory projection is
  cleanable;
- a missing document is reported, not created.

Measured on the laptop DB, dry run only (the operator's document was not
modified by this lane's work):

```
C:\Users\SCM\.config\harness\chat_history\conversation_memory.json:
would remove 1117 test-run row(s), keeping 46 durable fact(s)
dry-run: nothing written; re-run with --apply to remove them
```

## Verification

- `python -m unittest tests.test_home_isolation` -> 12 tests OK.
- `python -m unittest tests.test_ledger_isolation tests.test_serve_log_574`
  -> OK.
- Full CI-equivalent run with the guard in place,
  `python -W error::ResourceWarning -m unittest discover -s tests`:
  `Ran 7916 tests in 627.747s`, `FAILED (failures=1, errors=1, skipped=81)`.
  Both are this machine's local-only envirnoment defects and reproduce on
  unmodified `main` in this clone:
  `test_local_fit_optional_ci_311` (known local-only failure) and
  `test_serve_log_574...test_desktop_command_opens_its_own_log`
  (`AttributeError: '_Thread' object has no attribute 'is_alive'` out of
  CPython 3.14's `subprocess.communicate`; proven by restoring the unmodified
  `tests/__init__.py` and rerunning that module, which failed identically).
- The operator memory after that full run: `331511` bytes, mtime
  `1795544445`, sha256 prefix `777408f0` -- byte- and mtime-identical to the
  reading taken before it. The ledger stayed at `1790634` bytes, mtime
  `1795545343`. The leak that produced the 1117 rows no longer grows.
- `ruff check harness tests scripts` -> All checks passed.
- `harness repo-cards --check` -> cards up to date.
- PR #719 (`492c01d0`), rail read per context at that head.
