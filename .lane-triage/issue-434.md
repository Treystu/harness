## Triage answer

There was no overlay surface: zero hits for overlay in `harness/`, `docs/` or the README before this change. Panel + judge verification answers a different question (does a panel agree on this diff), not "does the project's own suite pass against base+change". So the ask resolved to implement it.

## What landed

`e7e4131` (surface), `dc5b4bb` (import fix), `92986a2` (test fix) on `lane/burndown`:

- **`harness/overlay.py`**: `run_overlay(base, overlay, argv, cwd=, timeout=, keep_scratch=)` copies the base tree into a scratch directory, lays the overlay over it, runs one argv command there through `osal` (no shell) and returns the evidence: `ok`, `returncode`, `timed_out`, `stdout`, `stderr`, `overlay_files`, `cwd`, plus the composed paths and the kept scratch path when asked. Composition leaves the base tree untouched by construction.
- **Refusals before any process starts**: missing or non-directory trees; a string command (a string is a shell waiting to happen); an empty command; a `cwd` that escapes the scratch; a symlinked overlay entry (a link can point outside the scratch, so a composed tree would stop being a tree); and an overlay that turns a base directory into a file.
- **`harness overlay`** CLI face (`--base`, `--overlay`, `--cwd`, `--timeout`, `--keep-scratch`, `--out`): the verdict is the command's own exit status, a red suite exits 1 as a reported result, and a refusal raises before dispatch.
- **`CONTRIBUTING.md`** module row (D10), so the surface is in the module map rather than hidden.

## Evidence

- `tests/test_overlay.py`: 13 pins, 12 pass + 1 skipped where Windows refuses symlink creation. They prove the properties that could silently rot: base alone red and the composed tree green (the overlay really is what the command sees), the base is byte-identical afterwards, a red suite is a result with exit 1, every refusal happens before a process starts, the scratch is removed unless kept, and the CLI parses and exits 0/1 correctly.
- Full suite on `92986a2` with `-W error::ResourceWarning`: `Ran 5371 tests ... OK (skipped=66)` in 370.2 s.
- `ruff check harness tests`: clean. `pyright --pythonversion 3.9` over the changed files: 0 errors.
- CI run 41643076202 on `92986a2`: **17/17 check-runs success**, audit and changed-file typecheck included.

## Regressions found by the gates and fixed in-item

Both were mine, and both were caught before this comment rather than after a landing:

1. `e7e4131` imported the runner inside `_cmd_overlay`; `tests/test_architecture` forbids deferred interface imports outside `main`, so all four Ubuntu legs and the audit's coverage battery failed while macOS/Windows passed. Fixed in `dc5b4bb`.
2. `dc5b4bb` still failed the audit's R13 because the base-untouched test read its sentinel with bare `open()` calls under `ResourceWarning`-as-error. Fixed in `92986a2`. Correction to my earlier note: that R13 failure was this defect, not the load-sensitive `test_jev_chaos` timing observation, which is a separate risk.

## Disposition

Landed on the lane, open for main. `main 5eb9c36` is red on its own run 41576644039 and landing onto a red base is not allowed; that owner-reserved act is recorded on #442. Scope note: this is the "name it or implement it" answer to the issue, not a build system -- it composes whole trees and runs one command, and does not interpret test output beyond the exit status.
