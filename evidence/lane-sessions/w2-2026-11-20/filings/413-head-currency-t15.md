## W2 HEAD-CURRENCY RE-RUN — #413 at main `d916a7b` — verdict unchanged: PARTIAL

**Revision under test:** main `d916a7bbe3de878dc842635c69f9f1cf3e619bfa`. The served
routing files were asserted byte-identical to that commit inside the receipt
(`git show <head>:<path>` vs the on-disk file, sha256 per file):

| File | sha256 (disk = head) |
|---|---|
| `harness/server.py` | `4715b1675fbc292c4b6237b1201340698168aa2e757f31b118aa181fd958c5f6` |
| `driver_core/server.py` | `62504dc959cef15c88567e2f0dfadea69b938fb96d5d37cc412b676994c2f738` |
| `driver_core/driver.py` | `44d0c888d1d62cefe87e08747ee7a2962efaf27ce461339f86347e45b4e16dc1` |

`04fb1cd0 -> d916a7b` is a two-line documentation deletion only, so the code
under test is the same product revision; the receipt is bound to the head anyway
rather than inheriting turn-14's binding. Both runs below were taken with
**exactly one** harness process listening.

### The two states, same head, same bytes

| | no source declared (fresh default) | `DRIVER_DOM_URL` declared |
|---|---|---|
| `POST /api/driver/start` | 200, `status: running`, health `ok: true` | 200, `status: running`, health `ok: true`, `sources: ["dom"]` |
| `GET /api/driver/health` | 200, `keyed: false`, `sources: []`, `key_provisioning: unkeyed` | 200, `keyed: false`, `sources: ["dom"]`, `key_provisioning: unkeyed` |
| `GET /api/driver/vocabulary` | **200**, `ok: true`, 15 actions (4 `executable: true`, 11 `refused_until_backend`) | **200**, `ok: true`, same 15 / 4 / 11 |
| same, no auth header | **401** | **401** |
| `GET /api/driver/verify` | **200**, `ok: true` | **200**, `ok: true` |
| `GET /api/driver/schemas` | **200**, 3 schemas | **200**, 3 schemas |
| `POST /api/driver/step` (`schema: dom`, target, no action) | 200, `ok: false`, **`stopped_at: capture`**, **`reason: no_capture`**, `cost_usd: 0.0` | 200, `ok: false`, **`stopped_at: decision`**, **`reason: decision_not_usable`**, `cost_usd: 0.0`, detail `decision status 'unkeyed': no decision key configured` |
| same body plus `action: vocabulary` (the turn-13 body) | identical to the row above | identical to the row above |
| step without `schema` | 400, `schema is required; declare one of ['cli','dom','gui','mcp','screen']` | same |
| step without `target` | 400, `field 'target' is required and must be a string` | same |

### What this settles, and what it does not

- **Settled at this head:** the keyless read surfaces answer as the build
  documents them — vocabulary, verify and schemas are 200 with the owner token
  and 401 without it, with the same 15/4/11 action split recorded at
  `cdc72fde` in turn 14. No drift across the merge.
- **The configuration dependency, stated plainly:** `docs/driver.md` (lines
  42-46) says the default driver declares no source and observes nothing, and a
  step against it is refused `no_capture`. The decision tier is therefore only
  reachable once a perception source is declared; turn 13's and turn 14's
  `decision_not_usable` observations were taken with a dom source declared, and
  this re-run reproduces them exactly. Neither observation contradicts the other
  — they are two different stop positions of the same chain.
- **Not settled:** the acting tier. Still `stopped_at: decision`,
  `status: unkeyed`, zero extractions, zero actions, `cost_usd: 0.0`. The
  unblocker is unchanged and unowned by this lane: `DRIVER_JEV_API_KEY` in the
  serving process (unset here; no `.env` exists in this checkout).
- **Measured operational constraint, reported not filed as a defect:** the
  driver service binds one fixed endpoint with a token generated per start
  (`docs/driver.md` settings table: `DRIVER_BASE_URL` default
  `http://127.0.0.1:8791`, `DRIVER_TOKEN` generated per start when unset). With
  two harness processes up, the second one reached the first one's service and
  **every** driver route answered 503 `driver service returned HTTP 401:
  unauthorized` — vocabulary and schemas included, not just `step`. Both runs in
  this receipt were retaken with a single process; no product change is proposed.

**Verdict: PARTIAL, unchanged.** No completion credit is taken in either
direction by this re-run.

Gates (product Jev first, Lucas second): Jev `investigate`, Lucas `pass` on
this filing — `gates-turn15.json`.

Receipts: `evidence/lane-sessions/w2-2026-11-20/probe-turn15.json` (paired),
`probe-turn15-default.json`, `probe-turn15-configured.json`,
`probe_turn15.py` (records the head binding and the per-file sha256),
`combine_turn15.py`.
