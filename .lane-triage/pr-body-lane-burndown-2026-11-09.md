Standing draft PR for the 2026-11-09 HAR-CORE burndown hour. Three commits, both scoped, both hermetic.

## 1. main-red cure (oversight item zero, #295 filing 6733006016)

`main` 90862bd5 had `ui-playwright-smoke` red at job 716: every browser dependency reported "no installation candidate" (exit 100) and no test ran. Playwright's `--with-deps` installs through apt, and this image's index was stale. The step now refreshes the package index before installing. The job itself is the verification on this head.

## 2. #480 BR1 — OSAL capture/describe backend registration

The perception bridge needs the input-side registration surface on the observation side: a non-desktop driver observes the owner display through a backend outside `driver_core`, and `ScreenSource` has to resolve through it so the tier invariant holds.

- `CAPTURE_KINDS`, frozen backend record, `capture_backend()` / `register_capture_backend()` / `disable_capture_backend()` / `capture_backends()`, mirroring `register_input_backend`.
- Registered backend wins; the native reader answers unchanged where none is registered (capture already works on a stock machine, so registration is not a precondition).
- Plugin failures arrive as named refusals; a backend's own `OsalError` re-raises unchanged.
- Pixels and words are separate capabilities: a capture-only backend refuses to describe by name.
- `native_capture_backend` / `register_native_capture_backend` name the in-repo readers through the registry, resolving the module reader at call time.

Scope note, stated rather than implied: this is BR1's registration + resolution half. The bus-backed consumer and the interactive-session hand (BR2), envelope/freshness (BR3) and grants (BR5) are not in this PR.

## Evidence (local)

- `tests/test_driver_core/test_osal_capture_backend.py`: 25 tests, all pass.
- `tests/test_driver_core`: 502 passed, 2 skipped.
- stdlib `trace` over the new block: every added statement executes (remaining diff lines are comments/blank/docstrings). The one uncovered statement the trace found (describe-side `OsalError` re-raise) got its own test in commit 3.
- `ruff check` clean on both files.
- pyright: osal.py's 9 errors are the #445 baseline, unchanged by this diff.
- No screen, display server or platform image tool touched.

## Gates

Lucas Gate v2 receipt is filed in the PR conversation, head-bound.
