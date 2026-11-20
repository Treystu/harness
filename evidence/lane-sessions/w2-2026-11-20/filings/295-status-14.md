## W2 turn 14 - correction: my keyless-vocabulary intake row was false, withdrawn in #640; re-run trigger still armed

Comm lock: #295 read at turn start (newest my own addendum `7012569455`) and re-read after each filing below. **New oversight comments: none addressed to W2.** No STOP. At turn start `origin/main` was `4618b5f9` and #628 was open at `e8ef0b63`; mid-turn main moved to `04fb1cd0` by merging my own intake row (#639). #628 is **still open**, so queue item 4 remains armed.

### DONE - a false finding of mine is retracted, not defended

The Codex review on #639 (`2026-11-19T14:40:17Z`) said the row `driver-vocabulary-keyless-claim-false` was probed through the wrong surface. It is correct, and the row is wrong. `_api_driver_step` (`harness/server.py:2567-2585`) never reads `action`: it requires `target` and always calls `adapter.step(...)`. My turn-13 body carried `target` and `schema`, so `action: vocabulary` measured the **decision** pipeline. Vocabulary lives at `GET /api/driver/vocabulary` -> `_vocabulary_view` (`driver_core/server.py:136-155`).

Re-probed keyless at `cdc72fde` (`harness/server.py`, `driver_core/server.py`, `driver_core/driver.py` identical to `main` `04fb1cd0`, asserted in the receipt), DOM source declared, health `keyed: false`, `sources: ["dom"]`:

| Surface | Result |
|---|---|
| `GET /api/driver/vocabulary` (owner token) | `200`, `ok: true`, 15 actions, 4 executable, 11 `refused_until_backend` with `needs` |
| `GET /api/driver/vocabulary` (no token) | `401` |
| `GET /api/driver/verify` | `200`, `ok: true` |
| `GET /api/driver/schemas` | `200`, 3 schemas |
| `POST /api/driver/step` with and without `action` | byte-identical `decision_not_usable` envelopes |

Every surface the health text calls keyless answers keyless, so the contract the row described does not exist at this head.

- **Retraction PR #640** (docs only, no product code): head `9992715`, base `04fb1cd0`, MERGEABLE. `docs/found-in-use.md` 15 -> 14 rows, em dashes 11 -> 11, no mojibake, and the diff is exactly the row plus one separator. No replacement row is filed; the keyless decision tier is already `driver-decision-tier-unkeyed` (#413).
- **Correction filed on #413** (`7018097385`): the row withdrawn, the vocabulary/verify/schemas reads moved into the measured column, and the verdict left **PARTIAL** - capture clears, the round-trip still stops at the unkeyed decision stage, the acting tier is still unmeasured for want of `DRIVER_JEV_API_KEY`.
- **Reply to the Codex finding on #639** (`7018098490`), accepting it on the record.

Gates on the correction text (`gates-turn14.json`): product Jev `investigate`/proceed on both items, Lucas Gate v2 `pass` on both.

### Corrected statement of #413's verdict

PARTIAL, unchanged in substance and not upgraded: capture clears with a declared DOM source; `POST /api/driver/step` stops at `decision_not_usable` (`stopped_at: decision`, `cost_usd: 0.0`) because the decision tier is unkeyed; the acting tier cannot be measured keyless. Added to the measured pass column: vocabulary (15 actions with per-action executability), verify, and schemas all answer keyless under the owner token and refuse 401 without it.

### WIP

#640's rail, read context-by-context at `9992715` once CircleCI reports. No process or port held after this filing (serving process on 8798 stopped).

### NEXT

1. #640 review and merge - the sergeant's call; it is a one-row docs retraction on current main.
2. On #628 merge (persistence unblocker for #468): re-run the W468 frozen brief UNCHANGED at the new head, slot 1, publish the comparison on #468.
3. On a product call site injecting `DecisionTrace` into `EventLedger`: open W469's clock at the first real campaign start, slot 2.
4. Verifications per the sergeant's order; #412 steps 4-7 and #415 remain parked with their unblockers named.

### BLOCKERS

- **W468**: #628 open/draft, unmerged - `harness/jev_assessment.py` still has no write path. Trigger armed, not fired.
- **W469**: `git grep -n "trace=" 4618b5f9 -- "harness/*.py"` returns only the `flush_loop.py:374` parameter declaration; no product call site injects a writer.
- **#413 acting tier**: needs `DRIVER_JEV_API_KEY` (operator config); `DRIVER_JEV_API_KEY` is unset in this environment and no `.env` exists.
- **#422**: needs a DOI resolver plus the report-path call site; product-owner decision via the sergeant.
- **#412**: owner-signed-in browser window. **#415**: OpenRouter credit (`/api/v1/key` 200 with `limit_remaining 1.5` while paid calls 402).

Evidence: `413-correction-t14.md`, `639-codex-reply.md`, `probe_turn14.py`, `probe-turn14.json`, `gates-turn14.json`, `retract_413_row.py` under `evidence/lane-sessions/w2-2026-11-20/`, pushed to `w2/turn11-evidence` (#637).
