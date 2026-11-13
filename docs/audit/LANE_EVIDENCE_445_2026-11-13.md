# Lane evidence — #445 pyright baseline debt (2026-11-13)

**Item:** #445 — baseline pyright debt in core modules makes the changed-file
typecheck leg fail on any PR that touches them.

**Delivery state:** READY-TO-MERGE — HAR-SAMS merges; author does not.
No pull request could be opened from this lane (server-side credential is
fetch/pull/push only, `gh` unauthenticated, REST API 403 with no token); this
record replaces the PR body. Rail: **NOT CHECKED from this lane** — no named
CircleCI status is readable here, and no combined status is offered as
evidence.

**Branch / exact head:** `lane/core-445-server-pyright` (off `9967aa8`).

## Scope, stated honestly

The issue's own module list lives in text this lane cannot read, so the scope
was chosen by what is reproducible from the tree: the modules this lane's
delivery touches and that the changed-file leg would therefore diagnose.
`harness/mcp.py` was already clean. `harness/server.py` carried **24**
baseline errors and is the module the #299 POST-body work modifies, so it is
the module that would block that PR. Two annotations whose owner is another
file (`harness/agent.py`, `harness/spend.py`) were added where they belong
rather than suppressed at the use site.

| File | Before | After |
| --- | --- | --- |
| `harness/server.py` | 24 errors | 0 errors |
| `harness/mcp.py` | 0 | 0 |
| `harness/agent.py` | 0 | 0 |
| `harness/spend.py` | 0 | 0 |

`pyright --pythonversion 3.9` (the pinned CI invocation, pyright 1.1.414) over
those four files: `0 errors, 0 warnings, 0 informations`.

## What was actually wrong

Most of it was annotation shapes on stdlib subclasses, but one item was a real
runtime defect:

- **Plan+execute was dead code.** `run_plan_task` built
  `PlanExecutor(engine=..., dag=..., task_id=..., cancel_check=...)` and
  called `executor.execute()` with no argument. The real constructor is
  `PlanExecutor(engine, node_routes, *, ...)` and execution is
  `execute(dag)` — the same assembly the CLI and MCP lanes build. Every HTTP
  plan+execute raised `TypeError: PlanExecutor.__init__() got an unexpected
  keyword argument 'dag'` before a node ran. It is now called the documented
  way, with the plan's own node routes and local gate threaded through.
  The existing test passed only because it mocked `PlanExecutor` itself.
- `_api_site_route` was defined twice, identically; the earlier copy was dead
  code that could drift from the one that ran. Removed, with a note.
- `log_message`/`log_error` overrode the stdlib with a parameter named `fmt`
  where the base names it `format` — renamed to match the seam they override.
- `self.server.ui` was typed as the bare `BaseServer`; the handler now narrows
  once in its `ui` property instead of at each of its five uses.
- `_opt_int` legitimately returns `Optional[int]`; the missions route supplies
  defaults, so it asserts what its own defaults guarantee instead of passing an
  Optional into a required-int parameter.
- `key_status()` is explicitly `Dict[str, Any]`: callers attach their own
  nested blocks (`/api/spend` adds `session`), so a float-only value type was
  simply wrong.
- `AutonomousAgent` declared no `transport`/`script_proposals` attributes; it
  now types the transport as the `Transport` base (the GUI binds a
  cancellation view over it) and defaults `script_proposals` to false.
- Small truthfulness fixes: the driver probe timeout is an int, the cost-cap
  message cannot interpolate `None`, and a recorded lifecycle step asserts the
  state it indexes instead of raising a bare subscript error.

No threshold, gate, verdict, canon row, or other module's behavior changed.

## Evidence on the exact head

| Suite | Result |
| --- | --- |
| `tests.test_server tests.test_plan_http_batch tests.test_agent tests.test_jev_ledger_spend` | Ran 255 tests, OK |
| `tests.test_server_driver tests.test_site_server tests.test_intake tests.test_agent_run_limits tests.test_agent_desktop_audit_report` | Ran 122 tests, OK |
| `ruff check harness/server.py harness/agent.py harness/spend.py` | All checks passed |
| `pyright --pythonversion 3.9` on the four modules | 0 errors |

## Second, independent method (not the same run twice)

Static typing is one claim; the plan+execute defect is a runtime one, so it was
driven directly. The probe called the real `run_plan_task` with the real
`PlanExecutor` (only `apply_session` and `compose_plan` doubled, i.e. the
model/composer boundary) and ran both call shapes:

```
old call: TypeError: PlanExecutor.__init__() got an unexpected keyword argument 'dag'
new call: status=ok execution=True
probe: PASS
```

The old shape provably cannot construct; the shipped shape executes and
returns an execution block. This is evidence a type checker cannot produce:
the path works, not merely type-checks.

## Not checked

- CircleCI rail statuses on this head (no access from this lane).
- A second non-author reviewer verdict (no reviewer reachable).
- The rest of the repository's pyright debt (741 errors across `harness/` and
  `driver_core/` at `9967aa8`): untouched, because those files are outside
  what this lane's delivery modifies. A whole-repo cure needs the issue's
  module list.
