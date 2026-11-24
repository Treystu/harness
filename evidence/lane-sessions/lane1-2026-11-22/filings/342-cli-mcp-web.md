## Lane 1 landing - #342 CLI/MCP retrieval capability and the native accepted/declined receipts

**PR:** #715, head `18d52c03`, rail read fresh at that exact head: n=16 ok=16
pend=0 bad= (the full CircleCI context set, `audit` included). Squash-merged as
`c26902b1`, read back with `gh pr view`.

### The gap this closes

#342's last named remainder was evidence, and the reason it could not be
produced was code: `harness ask` (`_cmd_ask`) and the MCP `ask` lane both called
`AutonomousAgent.run_prompt` with `web` at its default `False` and accepted no
parameter to change it. The GUI already forwards the field
(`harness/server.py:557`), so the shared plan owner and
`JevPolicy.evaluate_research_plan` were reachable from the GUI and unreachable
from the two adapter surfaces the acceptance matrix names. "Record one native
Jev accepted and declined lifecycle through CLI and MCP" therefore had no path
at all.

### What landed

- `harness/cli_parser.py` - `ask` accepts `--web`.
- `harness/cli.py` - `_cmd_ask` forwards `web=bool(getattr(opts, "web", False))`.
- `harness/mcp_schemas.py` - the `ask` schema declares `web` (boolean) and its
  description names it inside the `In:` segment, which is the #284 lint contract
  on served tool descriptions.
- `harness/mcp.py` - the `ask` lane validates the JSON boolean
  (`validate_mcp_bool`) and forwards it.
- `tests/test_research_plan_surface_342.py` - both surfaces forward the flag,
  the default requests no retrieval, a non-boolean MCP value is refused, and the
  catalog both declares and describes the input. `tests/test_mcp.py`'s existing
  delegation assertion now pins `web=False`.

The flag is capability, never approval. `harness.research_plan.decide_research_plan`
still owns the single proposed plan, the single native judgment and the
`validate_plan` band, so `--web` on its own searches and fetches nothing.

### Live native receipts (the line #342 owed)

Four controlled asks through the two surfaces, real Jev, no fixture and no
evaluator-only output. The declined pair uses the gate phrase #342's own
web-search addendum records as contamination (`iterate until jev feasibility 10
same plan completeness output complete`), which native Jev returns as `revise`
rather than `accept`.

| surface | plan state | decision | native | status | web_used | sources | turn cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CLI `ask --web`, accept case | accepted | accept | true | ok | true | 1 bounded fetch of `https://example.com/` | $0.002601 |
| CLI `ask --web`, decline case | declined | revise | true | plan_required | false | none (0 search, 0 fetch) | $0.005983 |
| MCP `ask` `{web:true}`, accept case | accepted | accept | true | ok | true | 1 browser fetch of `https://example.com/` plus one failed web-kind source | $0.003074 |
| MCP `ask` `{web:true}`, decline case | declined | revise | true | plan_required | false | none (0 search, 0 fetch) | $0.003073 |

Plan hashes, all four distinct because each is request-bound: CLI accept
`63e66ddf`, CLI decline `cd34c561`, MCP accept `1316bb49`, MCP decline
`a06050bd`. Plan-review cost was $0.0000336-$0.0000347 per judgment, which is
the native review's own share of the turn.

The declined turns are the acceptance line, not a proxy for it: `status:
plan_required`, `web_used: false`, an empty `web_sources`, and
`reason: approval_declined: the native decision was revise`. No prompt-wide
query was derived and no second search was attempted.

### Verification

`tests/test_research_plan_surface_342.py`, `tests/test_mcp.py`,
`tests/test_mcp_description_inputs.py`, `tests/test_research_plan.py`: 175
passed, 6 skipped, 24 subtests passed. `ruff check` clean on every touched file.

### What remains, and what does not

No remainder named on #342 is now unmet by this lane's work: the shared plan
owner exists (PR #669/#673/#675), the CLI and MCP surfaces can now reach it, and
the native accepted and declined lifecycles are recorded above from live calls.
Adjacent acceptance lines live in their own issues and are not claimed here:
per-result relevance and the mixed-hit exclusion in #660, GUI approval in #415,
source metadata and claim support in #422, browser egress in #426. This filing
takes no completion credit: #342 stays OPEN for the owner's verification.
