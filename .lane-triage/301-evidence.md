#301 — CI scope widened to `driver_core` (evidence)

Lane head `6ff9a6b5658025475af68e0641147799155c79d1` on PR #484 (`lane/burndown-2026-11-09`).

**What changed:** the CircleCI lint step now runs `python -m ruff check harness tests examples/oc_handoff driver_core`. The Actions step already had the package (`.github/workflows/ci.yml:200`); the CircleCI port dropped it, so the rail that actually publishes statuses could not see `driver_core` at all.

**State of the original finding:** the F401 at `osal.py:52` is already gone from the tree — `PNG_SIGNATURE` is now defined in `osal.py` itself rather than imported unused from `.png`. So the durable half of the issue (the scope) is the whole remaining delta; the dead import is not re-fixed because it is not there.

**Evidence (local):**
- `python -m ruff check harness tests examples/oc_handoff driver_core` → `All checks passed!`
- Full driver_core suite on the same head: 502 passed, 2 skipped.
- The new lint scope is on the same commit as the #480 BR1 slice, whose own files are ruff-clean.

**Acceptance status:** the two code criteria are met locally; the third (`CI lint step includes driver_core`, full suite + audit green) is decided by the CircleCI pipeline on `6ff9a6b`. The `test` job's lint step is where the widened scope executes. Left open until that job reads green on this exact head — then it closes with the job URL, not with this comment.
