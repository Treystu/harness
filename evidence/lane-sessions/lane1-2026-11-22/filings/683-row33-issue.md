# Probe the connected backend rather than a fresh local MCP process

Part of #683, finding 33 (P1). Verified against `main` `8fc28a0e` on
2026-11-25: still present.

## Current evidence

harness/server.py:113 `_default_backend_probe()` returns `doctor.check_mcp_stdio`, which starts a fresh local `python -m harness.mcp` subprocess; it never contacts the configured `harness-oc` transport.

## The finding

**

When the desktop uses the remote `harness-oc` SSH transport, this default probe cannot detect its outage: `doctor.check_mcp_stdio()` launches a new local `python -m harness.mcp` subprocess instead of contacting the connected backend. The inspected verification record, `docs/audit/LAPTOP_LANE_VERIFY_2026-11-06.md`, explicitly records the local MCP smoke passing while the desktop's remote tunnel times out. In that documented failure scenario, the new component still reports `backend.state=ok` and treats requests as confirmed. Probe the configured transport, or report the connected backend as unknown when only local MCP startup has been checked.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `harness/server.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/617#discussion_r4621118705
