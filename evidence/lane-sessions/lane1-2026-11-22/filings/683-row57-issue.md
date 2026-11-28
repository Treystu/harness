# Poll the run result endpoint

Part of #683, finding 57 (P2). Verified against `main`
`8fc28a0e` on 2026-11-25: still present.

## Current evidence

evidence/lane-sessions/w2-2026-11-20/rerun_415.py:70 requests `/api/runs/` + run_id, while harness/server.py:2022 dispatches only `RUN_SUB_RE` (`result`, `events`, `cancel`); the bare run URL has no handler, so the poll cannot see a terminal status.

## The finding

Poll the run result endpoint

After a successful submission, this loop requests `/api/runs/{id}`, but the reviewed `harness/server.py` GET dispatcher only handles `/api/runs` and the `RUN_SUB_RE` subroutes (`result`, `events`, and `cancel`); the bare run URL returns 404. Since the error payload has no run status, the script polls for the full 900 seconds and records `timeout` even when the paid run has already terminated, losing the terminal error and spend evidence this rerun is intended to capture. Request `/api/runs/{id}/result`, as `rerun_415b.py` does.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `evidence/lane-sessions/w2-2026-11-20/rerun_415.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/629#discussion_r4646550842
