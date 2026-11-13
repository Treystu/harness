## Cause

`chat()` had no Meta dispatch. It floored the id and posted to OpenRouter, so every lane that calls `chat()` directly -- panel (`harness/panel.py` judge seat and vote seat), apply (`harness/apply_policy.py` attempt and escalation), and verify (through `service.run_verify` -> `panel_judge`) -- carried a Muse id to OpenRouter under the preset. `governed_completion` and `chat_for_route` already dispatched Meta ids; the direct path did not.

## Fix - `cbbfc31`

`chat()` recognises a committed Muse id before flooring or payload shaping and dispatches through `_chat_meta`, the same path the other two entry points use. Key precedence: an explicit `meta_key` wins, then the `api_key` the lane threaded (under the preset `session.governor_for` returns the Meta key), then `resolve_meta_key()`. No key at all refuses with the Meta-key message instead of falling back to another provider.

## Tests fail before, pass after

Written first and run on the previous head (`1b3869b`); all three failed with the defect in the assertion message:

```
AssertionError: verify lane left Meta: [('https://openrouter.ai/api/v1/chat/completions', 'meta-key',
  {'model': 'muse-spark-1.3:floor', ...}), ...]
3 failed, 33 deselected in 1.04s
```

The three pins drive real lane entries -- `panel_judge`, `ApplyEngine.apply_edit`, `service.run_verify` -- and read the transport: every POST must be `META_CHAT_URL`, the key must be the Meta key, and the wire model must be the committed id (not `:floor`). On `cbbfc31`: `tests/test_meta_lane.py` 36 passed.

## Evidence

- Full suite: `Ran 5358 tests ... OK (skipped=65)` in 496.6 s (three more than the previous head, unchanged otherwise).
- `ruff check harness tests`: clean. `pyright --pythonversion 3.9 harness/chat.py tests/test_meta_lane.py`: 0 errors.
- CI run 41635922005 on `cbbfc31`: 17/17 check-runs success (all six hermetic legs, audit, changed-file typecheck, UI smoke, both hygiene legs, package and three installed-package legs).
- One honest wrinkle: the first attempt of the audit job failed on `R13` with `test_jev_chaos.ChaosTests.test_roomy_budget`, which asserts two chaos runs finish under 20 s of wall clock. Locally the same test takes 9.48 s, so a loaded runner can cross the line; the six dedicated hermetic legs ran the identical suite green on the same commit, and the audit job's rerun on the same tree is green. Recorded, not waived: this is a pre-existing timing flake that can red any head, independent of this change.

## Disposition

Cured on the lane, not closed. `main` stays red until this lands (base `5eb9c36` failed its own run 41576644039; recorded on #442). One branch is not independently pinned: the no-key-at-all refusal inside `chat()` is defensive for the three lanes, which always thread a key -- worth a pin when the Meta dispatch gains another caller.
