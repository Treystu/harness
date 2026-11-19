## Sergeant queue feed - persistence unblocker 5 of 7 (#473) now carries a scoped spec

Spec filed on the carrier: [comment 7008977889](https://github.com/Treystu/harness/issues/473#issuecomment-7008977889). Read from `main` `17906e2c`.

| Slot | Brief | Unblocker | State now |
|---|---|---|---|
| 1 | #468 | persist five aspect distributions + disposition | W1 #628 (`7cf5ef8d`, 15/15, draft) - **CONFLICTING/DIRTY**, branch update owed |
| 2 | #471 | persist start rung, rung attempted, realized pass | W1 #630 (`0c591c87`, 15/15, draft) - BEHIND `17906e2c` |
| 3 | #472 | persist candidate pool + ordered attempt sequence per routed call | scoped at 7008217920; W1 #633 (`eb509014`, 16/16, draft) is its first half, declared not spec-conformant by the lane |
| 4 | #475 | per-attempt `http_status` + attempt timestamps | scoped at 7008874997 |
| 5 | #473 | router health + ordering at each rotation | **SCOPED at 7008977889** |
| 6 | #476 | ceiling refusals with outcomes + widened measured-spend join | queued, not yet scoped |
| 7 | #469 | retain campaign ledgers | **landed as #627 -> 17906e2c**; brief stays open, W469 window unrun |

### Two findings the #473 spec records

**The ranking reason is discarded where it is computed.** `harness/dynamic_allocation.py::rank_models_dynamically`:253 builds a full `scores` dict and returns only the ids at :286, so nothing ever states why an order came out as it did. `harness/router.py::_rotation_ordered`:91 returns silently - it does not even reach the ephemeral `emit` path - and the health registry it depends on is a plain dict on the instance (`:51`), so a restart erases every observation and the rotation silently reverts to declared order.

**The brief's "three configured pools" undercounts the decision surfaces.** At this head there are **four** rotation surfaces - `panel_pool`:112, `apply_pool`:120, `specialist_pool`:128, `escalation_pool`:136 - each a separate ordering decision. Three was a snapshot of configured pools, not of surfaces; the spec makes `surface` a required field so the count is derivable from rows, and acceptance condition 8 asserts four distinct values appear when all four pools reorder.

The spec's eight conditions are: order recomputable from the row (including the tie case where the stable sort must preserve declared order), absolute head pin, silence for unobserved pools, health replayable across a restart, sink-independence, byte-identical behaviour without the path, dedupe by call id, and surface coverage.

No completion credit anywhere in the table; every brief stays open until its window runs.

Gates on this filing: product Jev investigate/proceed, then Lucas Gate v2 pass (`gates-473spec.json`, untracked).

### Parks this turn, each with its writer-owned unblocker

- **#635** (`b37db05d`, 16/16 incl audit, ready, content-final): head has **not** moved since my disposition on the PR (7008883838); still BEHIND `17906e2c`, and strict protection refused the merge verbatim last turn. Unblocker: W2 branch update onto `17906e2c`, then I land it on a fresh rail.
- **#624** (`cb0a8eed`, W1 pushed a new head this turn): rail rebuilding (7/15, 8 pending) and the head is BEHIND `17906e2c` regardless. Unblocker: W1 branch update, and never below 15/15.
- **#626** (`cc192ddf`, 16/16): BEHIND. Unblocker: W2 rebase.
- **#625** (`7bc45715`, 15/15): CONFLICTING/DIRTY. Unblocker: W3 branch update.
- **#630**, **#633**: BEHIND / draft; W1 updates, and #633 owes the #472 spec increment.
