# Supply the configured MCP authentication token to the probe

Part of #683, finding 34 (P2). Verified against `main` `8fc28a0e` on
2026-11-25: still present.

## Current evidence

harness/server.py:117 returns the bare `check_mcp_stdio` function, so the monitor probes without `settings.mcp_auth_token`; an MCP server that loads the token rejects the unauthenticated `tools/call` and a healthy backend reads as unreachable.

## The finding

**

When `mcp_auth_token` is configured, returning the bare doctor function causes the monitor to call `check_mcp_stdio()` without authentication. The spawned MCP server loads that token and rejects unauthenticated `tools/call` requests in `McpServer._authorize`, so its `ledger_status` check fails and a healthy backend is reported as unreachable. The existing doctor entry point passes `settings.mcp_auth_token` explicitly; bind the configured token here as well, independently of the UI authentication tokens.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `harness/server.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/617#discussion_r4621118718
