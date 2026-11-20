## W2 verification at 6ea96c29 - #413 driver: capture now clears with a declared DOM source; the round-trip stops one stage later at the unkeyed decision tier

**Revision under test.** Working tree HEAD **`6ea96c29fed9373e8a591085ca3173d18c9edd1b`**, served on `127.0.0.1:8797` with `DRIVER_DOM_URL=http://127.0.0.1:8797/` declared in the serving process environment, so the driver's `dom` source is configured. Product code identical to `main` **`4618b5f9`** (the operator-head diff is evidence-only).

### What was executed (one run, receipt `probe-turn13.json`)

| Step | Result |
|---|---|
| `POST /api/driver/start` | **200**, `status: running`; health `ok: true`, `sources: ["dom"]`, `keyed: false`, `key_provisioning.state: unkeyed`, `base_url: http://127.0.0.1:8791`, `run_ceiling_usd: 5.0` |
| `POST /api/driver/step` `schema: dom`, `target: http://127.0.0.1:8797/`, `action: read_dom` | **200**, `ok: false`, **`reason: decision_not_usable`**, **`stopped_at: decision`**, `cost_usd: 0.0` |
| same with `action: vocabulary` | **200**, `ok: false`, **`reason: decision_not_usable`**, `stopped_at: decision`, `cost_usd: 0.0` |
| step without `schema` | **400** - `schema is required; declare one of ['cli','dom','gui','mcp','screen']` |
| `POST /api/driver/stop` | **404** `no such endpoint: /api/driver/stop` (no stop route; recorded, not inferred) |

### What changed since the `583120b4` probe, and why it matters

The earlier run stopped at **capture** (`no_capture`, "Configured sources: ['none']"). With a DOM source declared, capture now succeeds and the step advances to the **decision** stage, where it stops because no `DRIVER_JEV_API_KEY` is configured. So the blocker is no longer "no perception source"; it is the decision tier.

**New finding, and the reason this is not a duplicate of the existing row:** the driver's own health text says "health, verify and vocabulary are intentionally keyless", yet the **`vocabulary` action also returns `decision_not_usable`** with `keyed: false`. A path advertised as keyless is gated on the keyed decision tier. Filed to the found-in-use intake as `driver-vocabulary-keyless-claim-false` (owner #413).

### Verdict against #413's acceptance

| Clause | Result |
|---|---|
| authenticated driver health + vocabulary output recorded | **PARTIAL** - health recorded and authenticated, with `sources: ["dom"]`; vocabulary returns `decision_not_usable`, not a vocabulary |
| one read_dom/click round-trip through the loopback driver recorded | **NOT MET** - stopped at `decision`; zero DOM extractions, zero clicks, `cost_usd: 0.0` |
| driver service identity and loopback-only binding confirmed | **MET** - driver on `8791`, server bound `127.0.0.1`, target loopback |

### Unblockers, named, with owner

- **Decision tier:** set `DRIVER_JEV_API_KEY` in the serving process environment (operator-owned configuration; not code). The paid route's ceiling is already tracked on #415, so this lane did not spend against it.
- **Acting tier (for click):** a registered input backend or `DRIVER_ALLOW_WRITE=1` (operator-owned).
- **Keyless-vocabulary contract:** product decision on whether vocabulary must be decision-gated; owner #413.

No product code and no configuration was changed by this lane; the DOM source existed only in the verification process environment, which is stated above so the run is reproducible.
