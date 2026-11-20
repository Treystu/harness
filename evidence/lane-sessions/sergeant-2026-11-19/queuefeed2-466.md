## Sergeant queue feed - persistence unblocker 4 of 7 (#475) now carries a scoped spec

Spec filed on the carrier: [comment 7008874997](https://github.com/Treystu/harness/issues/475#issuecomment-7008874997). Read from `main` `17906e2c`, after #627 put the `trace_v1` writer family on main, so it builds to a seam that exists.

| Slot | Brief | Unblocker | State now |
|---|---|---|---|
| 1 | #468 | persist five aspect distributions + disposition | delivered as W1 #628 (`7cf5ef8d`, draft; CONFLICTING after its base merged - branch update owed) |
| 2 | #471 | persist start rung, rung attempted, realized pass | delivered as W1 #630 (`0c591c87`, draft, base main, BEHIND `17906e2c`) |
| 3 | #472 | persist candidate pool + ordered attempt sequence per routed call | scoped at 7008217920; W1 #633 (`eb509014`, 16/16, draft) is its first half and the lane itself declares it not spec-conformant |
| 4 | #475 | per-attempt `http_status` + attempt timestamps | **SCOPED at 7008874997** - see the finding below |
| 5 | #473 | router health + ordering at each rotation | queued, not yet scoped |
| 6 | #476 | ceiling refusals with outcomes + widened measured-spend join | queued, not yet scoped |
| 7 | #469 | retain campaign ledgers | **landed as #627 -> 17906e2c**; the brief stays open because its W469 window is unrun |

### The finding that makes slot 4 worth its own spec

The brief says "no per-attempt `http_status` and no attempt timestamps". Read at `17906e2c`, the truth is sharper and more dangerous than that: **every one of those values is already computed and then thrown away.** `harness/events.py::emit`:223 returns immediately when no sink is registered - the default CLI path - so Jev's accurate `http_status`/`duration_s` (`harness/jev.py`:754-756, 970-972), panel's `http_status` on rotation (`harness/panel.py`:420-423) and chat's param-rejection notice (`harness/chat.py`:1019-1028) exist only for a process that happened to install a sink, and never survive the process. The breaker's own state (`CircuitBreakers`:453) is in memory only, so a restart erases the evidence that a site was being broken.

That is why the spec's first acceptance condition is sink-independence: no sink registered, scripted `429, 429, 200`, and the durable rows must still carry `[429, 429, 200]`. It fails today by construction. The remaining seven conditions cover one-row-per-attempt, status fidelity, timing sanity, byte-identical behaviour without the path, silence on refusals, reader-side ladder reconstruction, and breaker reconstruction after restart.

No completion credit is taken by any slot; every brief stays open and unmeasured until its window runs.

Gates on this filing: product Jev investigate/proceed, then Lucas Gate v2 pass (`gates-475spec.json`, untracked receipt).
