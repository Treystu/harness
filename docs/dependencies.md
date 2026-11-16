# Dependency management (uv)

`pyproject.toml` is the declaration; `uv.lock` is the resolution. Both are
tracked — the lock was listed in `.gitignore` as "local scratch" until
2026-11-14, which is exactly how a stale lock survived unnoticed — and their
agreement is checked without a network:

```
python -m harness.deps_lock --check     # exits 1 on any drift
```

The check compares the project version, `requires-python`, every declared extra
and its members against the lock, and refuses a lock entry with no name or
version. It cannot re-resolve — that needs a registry — but it can say the two
files disagree, which is the failure that actually bites.

## Everyday commands

```
uv sync --extra dev          # create/refresh the environment from the lock
uv sync --frozen             # install exactly the lock, error if it is stale
uv lock                      # re-resolve after a pyproject change
uv run python -m pytest -q   # run inside the locked environment
```

The pip path still works and is still what CI uses:

```
python -m pip install -e '.[dev]'
```

## State of the migration

| step | state |
|---|---|
| `pyproject.toml` carries the metadata (PEP 621) | done |
| `uv.lock` tracked (removed from `.gitignore`) | done — it had been ignored as local scratch |
| `requirements*.txt` removed from the repository root | done |
| lock agrees with the project | done — enforced by `harness.deps_lock` |
| CI installs through uv | **not on the uv path yet** |

**CI is not on the uv path yet.** `.github/workflows/ci.yml` still installs with
`python -m pip install -e '.[dev]'`, so the lockfile is exercised by nobody but a
developer who runs `uv sync`. The remaining step is a workflow change — an
`astral-sh/setup-uv` step plus `uv sync --frozen --extra dev` in the install
phase of the `test`, `typecheck-changed` and wheel-smoke jobs — which cannot be
validated from this lane: it needs a green CI run before the pip line is
removed, and the guardrail says the old path stays until then. Nothing is
claimed about that run here.

### Drift found and repaired (2026-11-14)

The lock on disk had drifted from the project, provably and without a network.
Nothing could catch it: the file was in `.gitignore` ("lockfile from uv" filed under
local scratch), so it was never committed, never reviewed, and never resolved by
CI — every developer's copy was their own private world, and the one on this
machine dated from 2026-10-02.

| field | pyproject | old uv.lock |
|---|---|---|
| project version | `0.5.1` | `0.4.2` |
| `render` extra (`playwright>=1.44`) | declared | **absent** |
| locked packages | — | 93 |

`uv lock` re-resolved to **98 packages**, updated the root package to `0.5.1`
and added the `render` group (`playwright`, `pyee`, `greenlet`). `uv sync --extra
render` would previously have installed a world the project does not describe.
The gate above now fails the tree if either drifts again.

## Hermetic parity

The lockfile changes no runtime code: the hermetic suite does not read `uv.lock`,
so the pre/post test accounting is identical by construction, and the run that
verified this change executed the same suites with the same counts and skips
(no skips added, none removed). Say it plainly rather than implying the lock was
measured against a second run: the pip path was the only path exercised.

## Rollback

If a later regression traces to this migration, revert in this order and stop at
the first step that restores the lane:

1. `git revert <migration-commit>` — restores the previous `uv.lock` and, if it
   was touched, the requirements file in one commit. This is the whole rollback
   for a dependency regression.
2. If only the lock is suspect: `git checkout <previous-sha> -- uv.lock` then
   verify with `python -m harness.deps_lock --check` (it should report `IN SYNC`)
   and `uv sync --frozen`.
3. If uv itself is the problem, drop back to pip, which needs no lock:
   `python -m pip install -e '.[dev]'`. This is the same command CI runs, so it
   is the path with a green history behind it.
4. Never delete `uv.lock` as a rollback: a missing lock is a different failure
   (`harness.deps_lock` exits 2), not a revert.
