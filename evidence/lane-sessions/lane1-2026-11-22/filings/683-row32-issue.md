# Honor the lifecycle's resumability flag for deferred requests

Part of #683, finding 32 (P2). Verified against `main` `8fc28a0e` on
2026-11-25: still present.

## Current evidence

harness/run_recovery.py:55 keeps `deferred` in `_INTERRUPTED`, and :133 returns `resumable: bool(payload.get('stage'))`. The lifecycle persists its own `data.resumable` and sets stage `terminal` for deferred requests, so a deliberately non-resumable deferred request is still advertised as resumable.

## The finding

**

For a checkpoint with `status="deferred"`, the lifecycle persists `data.resumable` and sets `stage="terminal"`, but this branch treats any nonempty stage as resumable. Consequently, a deliberately non-resumable deferred request is advertised as resumable with instructions to resume its saved checkpoint, even though `LifecycleCoordinator.resume()` explicitly returns `None` when `data.resumable` is false. I reproduced this using a coordinator-created deferred checkpoint. Check the persisted deferred-state resumability flag rather than deriving resumability solely from the presence of a stage.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `harness/run_recovery.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/614#discussion_r4617290270
