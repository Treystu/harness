CHECKPOINT — head `6ff9a6b5658025475af68e0641147799155c79d1` (four commits)

1. `687d092` — main-red cure: refresh the apt index before Playwright's browser dependencies. **Verified**: `ui-playwright-smoke` job #770 succeeded on `ac01648`; the same job is the only red on main `90862bd5`.
2. `a43f52e` — #480 BR1: capture/describe backend registration in `driver_core.osal`, resolved before the native readers; `ScreenSource` needs no adapter change.
3. `ac01648` — test for the describe-side `OsalError` pass-through (the statement the stdlib trace found unexecuted).
4. `6ff9a6b` — #301: `driver_core` returns to the ruff scope in the CircleCI lint step.

Local gates: 25 new tests pass; `tests/test_driver_core` 502 passed / 2 skipped; widened ruff scope clean; pyright `osal.py` errors unchanged from the #445 baseline. Lucas Gate v2 receipt above is head-bound to `ac01648`; this head adds only a CI path list and its own comment.

Rail: pipeline on `6ff9a6b` running at filing. I will close this PR's status on the audit job's result rather than assert it. Nothing here is a merge; PR #461 and #449 remain untouched.
