#480 BR1 — registration + resolution half landed on the lane (evidence)

Head `ac0164845db6a7c9ce54aee40356a2f9991ed45d` on PR #484 (`lane/burndown-2026-11-09`), based on main `90862bd5`.

**What exists now**
- `driver_core.osal` gains the capture-side mirror of `register_input_backend`: `CAPTURE_KINDS` (`capture`, `describe`), a frozen backend record built by `capture_backend()`, `register_capture_backend()`, `disable_capture_backend()`, `capture_backends()`.
- `capture_screen()` and `describe_screen()` resolve a registered backend first, and fall back to the declared native readers otherwise. `ScreenSource` already calls those two functions, so it resolves through the registry without an adapter change and the perception-tier invariant (adapters reach screens only via osal) is unchanged.
- A registered backend cannot crash a driver step: a plugin exception becomes a named refusal; a backend's own `OsalError` re-raises unchanged. A capture-only backend refuses to describe by name.
- `native_capture_backend()` / `register_native_capture_backend()` name the in-repo readers through the same registry, resolving the module reader at call time.

**Evidence (local, hermetic)**
- `tests/test_driver_core/test_osal_capture_backend.py`: 25 tests pass.
- `tests/test_driver_core`: 502 passed, 2 skipped.
- stdlib `trace` over the new block: every added statement executes; the one gap the trace found (describe-side `OsalError` re-raise) was closed with a test in commit `ac01648`.
- `ruff check` clean; pyright's 9 `osal.py` errors are the #445 baseline, unchanged.

**Not in this slice (named, not implied)**
- BR2 (interactive-session hand + bus consumer), BR3 (frame envelope, `captured_at` freshness, fingerprint dedupe), BR5 (capture grants/consent ledger). This is the registration and resolution surface only; none of the acceptance battery (capture, stale-frame, locked, wrong-token, fingerprint stability, negative content) can run until BR2 exists.

Next action on this issue: BR1 acceptance needs a real backend to register. BR2 is the next slice; this PR unblocks it by giving the hand something to register against.
