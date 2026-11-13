## Lane status - 2026-11-03 (v7 session 1, #434)

**DONE**

- **Issue-backlog triage, three items already cured on the lane.** Live state beat the plan text, so the drift is recorded on each item with evidence rather than reimplemented:
  - **#443** (3.14 hermetic leg): present since `959f0a9`; `hermetic suite (ubuntu-latest, py3.14)` green on every lane run today, `pyproject.toml` classifier consistent. `main` still has no 3.14 entry.
  - **#440** (driving-hygiene job): present since `4422355`; `Driving hygiene (deterministic)` runs on `pull_request` with `contents: read`, seven fixture tests including the seeded-violation-then-removal pair, no secrets, no model calls. `main` has only `checkout-hygiene`.
  - **#439** (read-only probe): present since `a241176`; `run_probe` is registered in `build_read_only_registry` and `tests/test_issue439_read_only_probe.py` passes 12/12 on the lane head.
- **#434 - overlay verification implemented**, since it was genuinely absent. Three commits: `e7e4131` (`harness/overlay.py`, the `harness overlay` CLI face, 13 tests, CONTRIBUTING module row), `dc5b4bb` (module-level import - the architecture rule the Ubuntu legs enforced), `92986a2` (closed reads in the test - the audit's ResourceWarning battery).
- **Evidence** - head `92986a2`: run 41643076202, **17/17 check-runs success** (all six hermetic legs, audit, changed-file typecheck, UI smoke, both hygiene legs, package and three installed-package legs). Full suite with `-W error::ResourceWarning`: `Ran 5371 tests ... OK (skipped=66)` in 370.2 s. `ruff check harness tests` clean; `pyright --pythonversion 3.9` 0 errors on the changed files. Secret scan on each commit: 0 credential, 0 close-keyword findings.
- **Two self-inflicted regressions were caught by the gates and fixed in-item**, both recorded on #434: the deferred interface import (`e7e4131` -> `dc5b4bb`) and the unclosed sentinel reads (`dc5b4bb` -> `92986a2`). Correction to the previous status: the `dc5b4bb` R13 failure was the ResourceWarning defect, not the `test_jev_chaos` load-sensitive timing risk, which remains a separate, unfixed observation.

**WIP**

- Nothing unpushed; tree clean apart from the untracked scratch named in earlier statuses (`.lane-triage/`, `.suite-run.log`, `.tools/`, `claude-config-archive/`, `site/worker/.wrangler/`).

**NEXT**

- #438 - headless key provisioning for driver_core verification: docs plus health output, then a keyed end-to-end observe/verify step. The first half is implementable without live keys; the keyed end-to-end proof may be owner-gated, and that split gets recorded on the item rather than guessed.
- Then #433 (Lucas Gate v2 runner) and #432 (voice proposal, deferral decision pending).

**BLOCKERS**

- Unchanged: base `main 5eb9c36` is red on its own run 41576644039, so landing is an owner-reserved act. The lane now carries the cures for that red (#446, #445, #447, #443, #440, #439, #444's `meta` row) plus #434, all green on `92986a2`. Nothing else is blocked.
- Observation, not a lane blocker: the audit's R13 runs the whole suite under trace on a shared runner; load-sensitive tests (for example `test_jev_chaos.test_roomy_budget`, a 20 s wall-clock assertion that takes 9.5 s here) can red a green tree. Worth its own issue if it recurs after this correction.

**DIRECTIVES**

- No new Treystu steering: the newest comments on #442 and #295 remain this session's own statuses (12:52), checked immediately before posting. No STOP. Continuing in issue order.

**METERING - TIME: 5 blocks** (session ~4.5 h wall clock, charged in whole FreeBuff paid-hour blocks).
