# Handle unreadable mission payloads inside the refusal path

Part of #683, finding 26 (P2). Verified against `main` `8fc28a0e` on
2026-11-25: still present.

## Current evidence

driver_core/mission_executor.py:508 `payload = self.inbox.read(filename)` runs before the `try` that catches `MissionRefused`, so malformed, oversized or non-mapping payloads abort `process_next` without a receipt or park.

## The finding

**

When the oldest `.json` mission contains malformed JSON, an oversized payload, or a non-mapping value, `inbox.read()` raises before entering the refusal handler. Consequently, `run()` aborts without parking or receipting that mission, and every subsequent poll encounters the same file instead of processing later valid missions. Catch these per-mission read refusals and use the validated filename as the fallback receipt identity so a bad payload does not permanently block the queue.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `driver_core/mission_executor.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/612#discussion_r4611145891
