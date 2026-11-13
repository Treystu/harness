# HAR-CORE digest · 6ff9a6b · 2026-11-09

Lane: HAR-CORE (harness burndown). Coordination surface: Treystu/harness issue #295. Lane branch: `lane/burndown-2026-11-09` → standing draft PR #484.

**Head before:** `90862bd5` (origin/main, pulled clean; local main was `b4b341a`).
**Head after:** `6ff9a6b5658025475af68e0641147799155c79d1` (pushed; no lane work left local-only).

## Worked items

1. **Item zero — main red (filing 6733006016).** `ui-playwright-smoke` on main `90862bd5` died at "Install Chromium and system dependencies" (apt: no installation candidate, exit 100, no test ran). Cure: refresh the apt index before Playwright's `--with-deps`. Verified A/B on the lane head: circleci job #770 (ui-playwright-smoke) = success on `ac01648`; the same job is the one red failure on main.
2. **#480 BR1 — OSAL capture/describe backend registration.** `CAPTURE_KINDS`, frozen backend record, `capture_backend()`, `register_capture_backend()`, `disable_capture_backend()`, `capture_backends()`, `native_capture_backend()`, `register_native_capture_backend()`. `capture_screen()`/`describe_screen()` resolve a registered backend first and fall back to the native readers otherwise, so `ScreenSource` resolves through the registry with no adapter change. Plugin failure = named refusal; backend `OsalError` re-raised unchanged; capture-only backend refuses to describe by name. Evidence filed on #480. Not in slice: BR2 (hand/bus), BR3 (envelope/freshness), BR5 (grants).
3. **#301 — driver_core returned to the ruff scope.** The Actions lint step covered `driver_core`; the CircleCI port dropped it. Scope is clean today (`ruff check harness tests examples/oc_handoff driver_core` → All checks passed), so the rail now sees that package.
4. **Queue reconciliation — settled items not reopened.** H-OSAL-WIN-INPUT-REGISTRATION landed via PR #477 (`16d077d`, merge `90862bd5`). The #453 D12 cure landed via PR #478 → `166a4656`, with the F9 live dogfood filed on #461 at 03:43Z on `9050fb73`. PR #461 and PR #449 merges left untouched (owner acts per this mission's fences).

## Pushes

`687d092` (CI apt cure) → `a43f52e` (+#480 BR1) → `ac01648` (+describe OsalError test) → `6ff9a6b` (+#301 scope), all on `origin/lane/burndown-2026-11-09`.

## Gates run (receipts)

- `tests/test_driver_core/test_osal_capture_backend.py` → 25 passed.
- `tests/test_driver_core` → 502 passed, 2 skipped.
- stdlib `trace` over every added statement in `osal.py` → all executed; the one gap found (describe-side `OsalError` re-raise) was closed by `ac01648`.
- `ruff check` on both changed files and on the widened scope → clean.
- pyright `driver_core/osal.py` → 9 errors, all the #445 baseline, unchanged by this diff.
- Lucas Gate v2 typed track → `pass`, head-bound `ac01648`, artifact_sha256 `5fdac743dd8e5b2dc3970fe0569acb98da38b7d81170c10f8de90700184cb1fe` (receipt on PR #484).
- CircleCI on `ac01648`: ui-playwright-smoke success (#770), package/installed-package/driving-hygiene/Checkout hygiene success; audit (#771) and several hermetic legs still pending at last read.

## Blockers filed

None. Note: `oversight/session-digests/harness/` did not exist in this ledger before this file; created with it.

## Exact next action

Read the CircleCI `audit` job and the remaining hermetic legs on `6ff9a6b`. If green, close #301 with its evidence and start #480 BR2 (interactive-session hand + bus consumer registering through the new capture surface). PR #484 stays draft pending its audit job; PR #461 / #449 merges remain owner acts.
