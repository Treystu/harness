# Pass the run ledger when assembling the MCP router

Part of #683, finding 68 (P2). Verified against `main` `8fc28a0e` on 2026-11-25:
still present.

## Method

Code read of the two assembly paths at `8fc28a0e`, nothing else: the MCP entry
(`harness/mcp.py`) and the serve path (`harness/session.py`), plus the router's
own recording seam (`harness/router.py`). No code changed in that act, so this
is a read of the shipped paths, not a run.

## Result

`harness/mcp.py:1831-1837` builds `ledger = composition.ledger_for(settings,
caller="mcp")` and then calls `composition.router_for(settings)` with no
`ledger=` argument. `harness/session.py:243-245` turns that argument into
`trace = DecisionTrace(ledger) if ledger is not None else None`, so the router
the MCP server is handed carries `trace=None`, and `harness/router.py:152-153`
writes no `router.rotation` row for MCP apply/verify operations. The serve path
is already correct: `harness/session.py:303` calls `router_for(settings,
ledger=ledger)`.

## The finding

Pass the run ledger when assembling the MCP router

For runs served through the native MCP entry point, rotation recording remains
disabled: `harness/mcp.py:1832` still calls `composition.router_for(settings)`
without the ledger it created immediately above. Consequently, the router
receives `trace=None`, and MCP apply/verify operations produce no
`router.rotation` evidence even though their other events reach the run ledger.
Update that production assembly path as well, or attach the trace centrally
when `engine_for` receives the router and ledger.

Provenance: https://github.com/Treystu/harness/pull/641#discussion_r4637149228

## Scope of this issue

One call site, one argument: pass the `ledger` already in scope at
`harness/mcp.py:1837` through to `composition.router_for(settings,
ledger=ledger)`, and pin it with a test that assembles the MCP server and
asserts the router it receives carries a trace.

The finding's alternative remedy - attaching the trace centrally inside
`engine_for` when both the router and the ledger are passed - is not part of
this issue. Rewiring `engine_for` would change how every caller that builds a
router without a ledger behaves, which is a composition-ownership decision for
`harness/session.py` and outside a single finding's blast radius. That
decision stays with the session composition owner; nothing here presumes it.

## Not claimed

- Not claimed: MCP runs record nothing. Their other events do reach the run
  ledger; this issue is only about the missing `router.rotation` rows.
- Not claimed: any behaviour change for library or test callers, which
  legitimately pass no ledger and correctly get `trace=None`.
- Not claimed: that a rotation row exists for every rotation that happens in
  an MCP run once the ledger is passed; this issue restores the writer, it does
  not audit what the writer emits.

## Acceptance

- `harness/mcp.py` passes the run ledger to `composition.router_for`.
- A hermetic test assembles the MCP server and asserts the router it receives
  carries a `DecisionTrace`.
- The serve path's behaviour (`harness/session.py:303`) is unchanged.
