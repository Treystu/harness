# Require receipt-write capability before executing missions

Part of #683, finding 25 (P1). Verified against `main` `8fc28a0e` on
2026-11-25: still present.

## Current evidence

driver_core/mission_executor.py: `process_next` claims and calls `self.execute(mission)` with no capability check; `write_receipts` is required only inside `MissionInbox.write_receipt` (line 276), so a read-only token executes first and the claim stays `claimed`.

## The finding

**

With a token scoped only to `read_missions`, this path executes the action before `write_receipt()` rejects the missing capability. The mission remains queued and its claim remains `claimed`, so polling again with the same owner executes the action again. This is reproducible on consecutive `run()` calls without waiting for lease expiry. Require both executor capabilities before claiming or executing any mission so a known inability to file receipts cannot leave completed actions replayable.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `driver_core/mission_executor.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/612#discussion_r4611145882
