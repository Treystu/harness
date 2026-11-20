# #413 correction - the keyless-vocabulary claim does not hold; the row is withdrawn

Filing: W2 turn 14. No product code changed.

## What was claimed and why it was wrong

Turn 13 filed `driver-vocabulary-keyless-claim-false` to the found-in-use index
(PR #639, merged as `04fb1cd0`). The row said a path documented as keyless
("health, verify and vocabulary are intentionally keyless") still terminated at
the keyed decision tier, because `POST /api/driver/step` with
`action: vocabulary` returned `decision_not_usable`.

That probe could not measure vocabulary. At this head
`harness/server.py:2567-2585` (`_api_driver_step`) never reads an `action`
field: it requires `target` and always calls `adapter.step(...)`. The turn-13
body carried `target` and `schema`, so it ran the model-backed decision
pipeline. The refusal that was recorded belongs to the decision stage of a
step, not to vocabulary.

Reproduced in one receipt (`probe-turn14.json`): the turn-13 body and the same
body with `action` deleted return byte-identical envelopes
(`ok: false`, `reason: decision_not_usable`, `stopped_at: decision`,
`detail: decision status 'unkeyed': no decision key configured`,
`cost_usd: 0.0`), and `{"action": "vocabulary"}` alone is refused `400`
`field 'target' is required and must be a string`. The `action` field is inert
today.

## What the keyless vocabulary route actually returns

The build exposes vocabulary on its own route:
`GET /api/driver/vocabulary` -> `_api_driver_vocabulary`
(`harness/server.py:1888-1889`, `:2528-2533`) -> `adapter.vocabulary()` ->
`_vocabulary_view` (`driver_core/server.py:136-155`), which returns the
declared vocabulary with per-action executability and never runs a decision.

Measured keyless, with `DRIVER_DOM_URL` declared and health reporting
`keyed: false`, `sources: ["dom"]`, `key_provisioning: unkeyed`:

| Surface | Result |
|---|---|
| `GET /api/driver/vocabulary` (owner token) | `200`, `ok: true`, 15 actions, 4 `executable: true`, 11 `refused_until_backend` with `needs` naming the missing executor |
| `GET /api/driver/vocabulary` (no token) | `401` |
| `GET /api/driver/verify` | `200`, `ok: true`, keys `audit`, `budget`, `ok` |
| `GET /api/driver/schemas` | `200`, 3 schemas |
| `GET /api/driver/health` | `200`, `keyed: false` |
| `POST /api/driver/step` (`schema: dom`, `target`, no `action`) | `200`, `ok: false`, `reason: decision_not_usable`, `stopped_at: decision` |

All three surfaces the health text calls keyless answer keyless, and the one
that refuses says so at the decision stage. The contract the row described does
not exist at this head.

## Disposition

- The intake row `driver-vocabulary-keyless-claim-false` is **withdrawn** from
  `docs/found-in-use.md` (retraction PR, branch `w2/retract-vocab-413`). The
  index returns to 14 rows; no other line is touched.
- No new defect is routed in its place. The keyless decision tier is already on
  the index as `driver-decision-tier-unkeyed` (2026-11-18, `9741066`, #413), and
  the observation above adds nothing to it.
- **#413's verdict is corrected, not upgraded.** It stays PARTIAL: capture
  clears with a declared DOM source, the round-trip still stops at the unkeyed
  decision stage, and the acting tier remains unmeasured for want of
  `DRIVER_JEV_API_KEY`. The correction moves the vocabulary, verify and schemas
  reads from unmeasured to measured working, and removes the false finding.
- Attribution: the error was caught by the Codex review on #639
  (`2026-11-19T14:40:17Z`), which named the exact routing split. The receipt is
  the re-probe, not the review.

## Evidence

- `probe_turn14.py`, `probe-turn14.json` - the re-probe, head
  `cdc72fde239afae00d18545a937d60a331b9bdf2` with
  `harness/server.py`, `driver_core/server.py`, `driver_core/driver.py`
  identical to `main` `04fb1cd0` (asserted in the receipt).
- `serve-8798-turn14.log`, `serve-8798-turn14.stdout` - the serving process.
- `gates-turn14.json` - product Jev then Lucas Gate v2 on this text.
