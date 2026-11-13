## Live state: this is already implemented on `lane/burndown`, not on `main`

Drift recorded, because the issue's premise (3.14 absent from the hermetic matrix) no longer matches the lane. `959f0a9` added the leg:

```yaml
- os: ubuntu-latest
  python-version: "3.14"
```

It sits in the same matrix job as 3.9/3.11/3.13 and runs the unchanged command from the issue (`python -W error::ResourceWarning -m unittest discover -s tests -v`), because the matrix job shares one step list.

## Acceptance check

- Same hermetic suite on a supported 3.14 runner: yes. `hermetic suite (ubuntu-latest, py3.14)` is green on the current lane head `cbbfc31` (run 41635922005), and on every lane run today; it is not a placeholder - it installs `.[dev]`, compiles, lints and runs the full suite like the other legs.
- Package metadata consistent: `pyproject.toml` keeps `requires-python = ">=3.9"` and the `Programming Language :: Python :: 3.14` classifier, which matches a matrix where 3.14 is exercised.
- Full-suite result retained in CI: yes, per-leg and in the run log.

`main`'s `ci.yml` still has no 3.14 entry (`git grep "3.14" origin/main -- .github/workflows/ci.yml` is empty), which is why this stays open: the cure is on the lane and lands with the rest of it.

## Disposition

Met on the lane, kept open for the main landing. Base `main 5eb9c36` is red on its own run 41576644039, so landing is an owner-reserved act recorded on #442 - not something this lane can do by merging a red base.
