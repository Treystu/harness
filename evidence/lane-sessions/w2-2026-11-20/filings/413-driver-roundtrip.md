## W2 — #413 probe at `583120b4`: loopback driver answers and fails closed at capture; no perception source and no driver decision key are configured

Register home: #466. Nothing fixed by this lane; no product code and no configuration changed.

**Revision under test.** Operator tree HEAD `583120b436ce747c40be8543c4fa8cbf686cb48b`, served on `127.0.0.1:8797` with the owner token; driver started through the server's own route on `8798`. The operator UI on `:8765` untouched.

### What answered

| Probe | Result |
|---|---|
| `POST /api/driver/start` | **200**, `status: running`; health reports `keyed: false`, `key_provisioning.state: unkeyed`, variable `DRIVER_JEV_API_KEY` — "health, verify and vocabulary are intentionally keyless" |
| `POST /api/driver/step` with `schema: dom`, `target: http://127.0.0.1:8797/`, `action: read_dom` | **200**, `ok: false`, `reason: no_capture`, `stopped_at: capture`, step `eaf51a578133` |
| same with `action: vocabulary` | **200**, `ok: false`, `reason: no_capture`, `stopped_at: capture`, step `44014f2dc015` |
| step without `schema` | **400** — `schema is required; declare one of ['cli','dom','gui','mcp','screen']`; the class must be declared rather than inferred |

The refusal text names both gaps itself: "target … is declared 'dom' and no configured source serves that class; nothing was tried. Configured sources: ['none']", and separately that acting needs a registered input backend or `DRIVER_ALLOW_WRITE=1`.

### Verdict against #413's acceptance

| Clause | Result |
|---|---|
| authenticated driver health + vocabulary output recorded | **PARTIAL** — health is recorded and authenticated; vocabulary returns the fail-closed `no_capture` record, not vocabulary for a page |
| one read_dom/click round-trip through the loopback driver recorded | **NOT MET** — stopped at capture; zero DOM reads, zero clicks, `cost_usd: 0.0` |
| driver service identity and loopback-only binding confirmed | **MET for this run** — driver on `8798`, target loopback, server bound `127.0.0.1` only |

This is the same shape as the `driver-decision-tier-unkeyed` intake row, one stage earlier: the driver refuses before the decision tier because no perception source is configured, so the unkeyed decision stage is not even reached.

**Unblockers, by name.** Either set a perception source in the process environment (`DRIVER_DOM_URL`, `DRIVER_CLI_COMMAND`, `DRIVER_MCP_COMMAND` + `DRIVER_MCP_TOOL`, or `DRIVER_SCREEN=1`) and re-run this exact probe, or accept the refusal as the issue's expected state. For the acting tier additionally a registered input backend or `DRIVER_ALLOW_WRITE=1`. None of these is code work; all are configuration the operator owns, and this lane did not set them.


**Gates, in order.** Product Jev (keyed `jev-1.14.0`, caller `w2-champion-audit`, site `audit_admissibility`, ledger seq 81521): verdict `investigate`, supported 0.07, cost $2.6796000000000002e-05. Lucas Gate v2 (typed track): `status: pass`, artifact `9c9ee23ac0579b49`. The Jev verdict is reported as returned; the disposition above rests on the observed step records.
