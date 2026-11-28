# Require request-specific evidence before marking a state confirmed

Part of #683, finding 35 (P2). Verified against `main` `8fc28a0e` on
2026-11-25: still present.

## Current evidence

harness/state_report.py:198 sets `confirmed: reachable` for every record whenever the backend probe is OK, and the default probe asks only for MCP init, tool listing and `ledger_status(limit=1)`; no request id is ever queried.

## The finding

**

Whenever the generic backend probe succeeds, every recovered record is marked `confirmed`, even an unreadable checkpoint whose state is `unknown`. The production probe only checks MCP initialization, tool listing, and `ledger_status(limit=1)`; it never queries these request IDs or reconciles their states. Consequently, recovery of connectivity falsely upgrades stale local evidence to backend-confirmed request state. Keep confirmation false unless request-specific evidence was actually obtained, while preserving the independently reported backend reachability and durable checkpoint state.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `harness/state_report.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/617#discussion_r4621118727
