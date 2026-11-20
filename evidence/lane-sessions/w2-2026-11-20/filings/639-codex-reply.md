## Finding accepted - the row is withdrawn

This finding is correct on both halves, and it lands a real error of mine.

1. `POST /api/driver/step` never reads `action`: `_api_driver_step`
   (`harness/server.py:2567-2585`) requires `target` and always calls
   `adapter.step(...)`. The body this PR cited carried `target` and `schema`, so
   it measured the decision pipeline, not vocabulary.
2. Vocabulary is `GET /api/driver/vocabulary` (`harness/server.py:1888-1889`,
   `:2528-2533`) -> `_vocabulary_view` (`driver_core/server.py:136-155`), which
   returns the vocabulary without a decision.

Re-probed keyless with `DRIVER_DOM_URL` declared, `keyed: false`,
`sources: ["dom"]`:

- `GET /api/driver/vocabulary` -> `200`, `ok: true`, 15 actions (4 executable,
  11 `refused_until_backend` with `needs`); `401` without the owner token.
- `GET /api/driver/verify` -> `200`, `ok: true`. `GET /api/driver/schemas` ->
  `200`, 3 schemas. `GET /api/driver/health` -> `200`, `keyed: false`.
- The turn-13 body and the same body with `action` removed return
  byte-identical `decision_not_usable` envelopes;
  `{"action": "vocabulary"}` alone is `400 field 'target' is required`.

So the contract this PR recorded does not exist at this head: every surface the
health text calls keyless answers keyless. The row was merged as `04fb1cd0`
before the review landed, so the correction is a separate retraction PR
(`w2/retract-vocab-413`) removing that one row and nothing else. No new defect
is filed in its place; the keyless decision tier is already
`driver-decision-tier-unkeyed` (#413). The #413 verdict stays PARTIAL with the
vocabulary, verify and schemas reads moved into the measured column.

Receipt: `probe-turn14.json`, `413-correction-t14.md` under
`evidence/lane-sessions/w2-2026-11-20/`.
