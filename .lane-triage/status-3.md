## Lane status - 2026-11-03 (v7 session 1, #447)

**DONE**

- **#447 - a Muse-only run is now Muse-transport-only.** `chat()` had no Meta dispatch: it floored the id and posted to OpenRouter, so the panel, apply and verify lanes carried Muse ids to OpenRouter under the preset. `cbbfc31` dispatches a committed Muse id before flooring or payload shaping, through the same `_chat_meta` path `governed_completion` and `chat_for_route` already use. Key precedence: explicit `meta_key`, then the threaded `api_key` (the preset's `governor_for` returns the Meta key), then `resolve_meta_key()`; no key refuses instead of falling back.
- **Tests were written first and fail on the previous head** (`1b3869b`), with the defect printed in the assertion: all three lanes observed posting `muse-spark-1.3:floor` to `https://openrouter.ai/api/v1/chat/completions`. The three pins drive real lane entries - `panel_judge`, `ApplyEngine.apply_edit`, `service.run_verify` - and assert the transport, key and wire model, not a config value. On `cbbfc31`: `tests/test_meta_lane.py` 36 passed.
- **Evidence** - head `cbbfc31`: run 41635922005, **17/17 check-runs success** (six hermetic legs, audit, changed-file typecheck, UI smoke, both hygiene legs, package + three installed-package legs). Full suite `Ran 5358 tests ... OK (skipped=65)` in 496.6 s - exactly the three new pins more than `1b3869b`, no failures. `ruff check harness tests` clean; `pyright --pythonversion 3.9` 0 errors on the changed files.
- **Regression window, recorded:** the first audit attempt on `cbbfc31` failed `R13` on `test_jev_chaos.ChaosTests.test_roomy_budget` - a wall-clock assertion (two chaos runs under 20 s). The same test takes 9.48 s locally, the six dedicated hermetic legs ran the identical suite green on the same commit, and the audit job's rerun on the same tree is green. This is a pre-existing load-sensitive flake that can red any head, not a functional failure of this change; it is recorded rather than waived, and it is a candidate for its own issue (an absolute 20 s budget is a runner-speed assertion).
- **#447 evidence comment posted** with the failure text, the three lane pins and the rerun history.
- SHA chain: `1b3869b` (previous head) -> `cbbfc31` (this item).

**WIP**

- Nothing unpushed; tree clean apart from the untracked scratch named in earlier statuses (`.lane-triage/`, `.suite-run.log`, `.tools/`, `claude-config-archive/`, `site/worker/.wrangler/`).

**NEXT**

- #443 - cover declared Python 3.14 support in the hermetic matrix (already a green leg here; the issue is about the declared support surface).
- Then #440 - the approved driving-hygiene CI job is not on main.

**BLOCKERS**

- Unchanged: base `main 5eb9c36` is red on its own run 41576644039, and landing onto a red base is not allowed. The cures now sitting on the lane - #446 (writer, test determinism, advisory), #445 (typing baseline), #444's D10 `meta` row, and #447 - are what main is missing, so base green requires this work to reach main: an owner-reserved merge or exception, recorded with evidence rather than worked around.
- Non-blocking observation: `R13`'s wall-clock budget is load-sensitive (see above); it can red a green tree.

**DIRECTIVES**

- No new Treystu steering: the newest comments on #442 and #295 are still this session's own statuses (12:23), checked immediately before posting this. No STOP. Continuing in issue order.

**METERING - TIME: 3 blocks** (session ~2.9 h wall clock, charged in whole FreeBuff paid-hour blocks).
