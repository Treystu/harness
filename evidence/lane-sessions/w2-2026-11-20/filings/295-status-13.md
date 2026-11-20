## W2 turn 13 - queue item 3 measured at 6ea96c29: #567 PASS, #414 PASS, #413 partial with a new finding, #422 parked with its decision owner

Comm lock: #295 read at turn start (newest sergeant turn 20 at 14:24:25Z) and again after each filing below. **New oversight comments: none addressed to W2** in that window; no STOP. Sergeant checkpoints 18-20 read and acked here: #630 parked (W1), #634 current, #638 mid-rail (W1).

### Revision under test, named

Working tree HEAD **`6ea96c29fed9373e8a591085ca3173d18c9edd1b`** (`sergeant/evidence-2026-11-19`), served as a live process on `127.0.0.1:8797` (pid 5212, startup marker `2026-11-19T14:28:15Z`). `git diff --name-only 4618b5f9..6ea96c29` = **74 files, all `evidence/`** - zero product paths - so the product code measured is identical to `main` **`4618b5f9`**. Owner token from the token store, never printed. No product code and no repo configuration changed.

### DONE - verifications

| Issue | Result | Evidence | Filed |
|---|---|---|---|
| **#567** | **PASS for the stand-up limitation.** `sessions` 200 (80 records), `history` 200 (5,292 typed turns), `ledger/tail` 200 (3 hash-chained `jev_eval` rows), `status` 200 (`auth_required true`, `recovered_count 25`); all four return **401** unauthenticated. The 2026-11-16 transcript remains unrecoverable and is not claimed. | `probe-turn13.json` | **7012308109** |
| **#413** | **PARTIAL, one stage further than before.** With `DRIVER_DOM_URL` declared, health reports `sources: ["dom"]`; `read_dom` and `vocabulary` now clear capture and stop at **`decision_not_usable`** (`stopped_at: decision`, `cost_usd 0.0`); schema-less step still 400; `/api/driver/stop` is **404** (no such route). Round-trip **NOT MET**. | `probe-turn13.json` | **7012308615** |
| **#414** | **PASS (hermetic).** Real MCP stdio client: `protocol 2025-06-18`, `serverInfo harness 0.5.1`, **33** tools, `ledger_status` present, read-only call `isError: false`, exit 0. | probe stdout | **7012310015** |
| **#422** | **PARKED - cannot execute end-to-end.** At `4618b5f9` the gate runs and refuses honestly (`not_verifiable`, `resolver_error: no DOI resolver was supplied`, `may_label false`), but the only importers are tests - **zero production call sites**. Unblocker: resolver + report-path call site; **decision owner: product owner (Treystu), routed by the sergeant.** | `422-probe.txt` | **7012310598** |

**Intake routing.** New row `driver-vocabulary-keyless-claim-false` (medium, owner #413) in **PR #639** (head `52628cbf`, base `4618b5f9`, one file, 14 -> 15 rows, 11 em dashes preserved, mojibake absent). It is the #413 finding that is not the existing `driver-decision-tier-unkeyed` row: the driver's health text calls vocabulary "intentionally keyless", yet the vocabulary action terminates at the keyed decision stage. #567 and #414 produced no new symptom, so they add no row.

**Parked, confirmed and up to date.** #412 steps 4-7 (**7012311431**): owner-signed-in browser window. #415 (**7012311968**): **OpenRouter account credit**, not a key limit - `/api/v1/key` 200 with `limit_remaining 1.5` while paid dispatch 402s.

### Gates, in order (receipts in `gates-turn13.json`)

Product Jev `jev-1.14.0`, caller `w2-champion-audit`, site `audit_admissibility`: #567 `investigate`, #413 **`escalate`**, #414 `investigate`, #422 `investigate`, intake-413 **`escalate`**; all with disposition `proceed`. Lucas Gate v2 typed track: **`pass`** on all five. Reported as returned; no verdict upgraded.

### Re-run trigger: STILL ARMED - no persistence unblocker has landed

- **#468:** #628 is still **OPEN and draft** (head moved to `e8ef0b63`, now MERGEABLE, **unmerged**). `harness/jev_assessment.py` still has no write path at `4618b5f9`. W468 stays slot 1.
- **#469:** `git grep -n "trace=" 4618b5f9 -- "harness/*.py"` still returns **one** hit - the `EventLedger.__init__` parameter at `flush_loop.py:374`. No product call site injects a writer, so campaign events still never reach `decision_trace`. W469 stays slot 2.
- The sergeant's "W468/W469 preflight standing extended to `4618b5f9`" (turn 18) is a **preflight of the trace family**, not a landing confirmation of either brief's persistence write, so it does not trigger a re-run.

### WIP
Server on `127.0.0.1:8797` (pid 5212) still up from the measurements; it will be stopped at turn end. No other process, no port held.

### NEXT
1. On **#628 merged**: run W468 unchanged at that head (slot 1).
2. On **a product call site injecting the trace writer**: open W469's clock (slot 2).
3. #639 rail to terminal, then it is the sergeant's to order.
4. #626 rebase remains outside this turn's fence.

### BLOCKERS (each parked alone, unblocker named)
- **W468** - #628 unmerged (draft).
- **W469** - trace writer never injected by a product caller (#469).
- **#413** - `DRIVER_JEV_API_KEY` in the serving environment (operator config); acting tier needs an input backend or `DRIVER_ALLOW_WRITE=1`.
- **#422** - resolver + report-path call site; product-owner decision.
- **#412** - owner-signed-in window.
- **#415** - OpenRouter account credit.

Evidence links: #567 `7012308109`; #413 `7012308615`; #414 `7012310015`; #422 `7012310598`; #412 `7012311431`; #415 `7012311968`; intake **#639** `52628cbf`; receipts `evidence/lane-sessions/w2-2026-11-20/{probe-turn13.json,422-probe.txt,gates-turn13.json}`.
