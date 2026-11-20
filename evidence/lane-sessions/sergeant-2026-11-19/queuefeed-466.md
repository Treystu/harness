## Sergeant queue feed - persistence unblocker 3 of 7 (#472) now carries a scoped spec

Spec filed on the carrier: [comment 7008217920](https://github.com/Treystu/harness/issues/472#issuecomment-7008217920).

Queue state, in the register order from 6995807908, each row exactly as it stands:

| Slot | Brief | Unblocker | State now |
|---|---|---|---|
| 1 | #468 | persist five aspect distributions + disposition | DELIVERED as W1 draft PR #628 (`7cf5ef8d`, stacked on #627) |
| 2 | #471 | persist start rung, rung attempted, realized pass | DELIVERED as W1 draft PR #630 (`0c591c87`, stacked on #627) |
| 3 | #472 | persist candidate pool + ordered attempt sequence per routed call | **SCOPED this filing** - site `harness/capability.py::ordered_pool` (line 814, read at main `d2e724ba`), eight fields per event, five observable acceptance conditions; blocked on the trace family landing (#627) so no second writer is built |
| 4 | #475 | per-attempt `http_status` + attempt timestamps | queued, not yet scoped |
| 5 | #473 | router health + ordering at each rotation | queued, not yet scoped |
| 6 | #476 | ceiling refusals with outcomes + widened measured-spend join | queued, not yet scoped |
| 7 | #469 | retain campaign ledgers | carried by W1 PR #627 (`43891d83`), parked BEHIND main `d2e724ba` |

One dependency fact belongs on this issue because it shapes three of the seven: the trace writer family (`DecisionTrace`, `read_trace_events`) is **not on main** at `d2e724ba` - it lives in #627. Slots 1, 2 and 3 are therefore all stacked behind that one landing, which makes #627's branch update the single highest-value unblocker in the queue. Every slot still takes no completion credit: the briefs stay open and unmeasured until their windows run.

Gates on this filing: product Jev investigate/proceed, then Lucas Gate v2 pass (`gates-472spec.json`, untracked receipt).
