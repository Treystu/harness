## Intake classification - `driver-vocabulary-keyless-claim-false` (#413)

**Symptom key.** `driver-vocabulary-keyless-claim-false`

**First seen.** 2026-11-20

**Observed at.** `6ea96c29fed9373e8a591085ca3173d18c9edd1b` (product code identical to `main` `4618b5f9`)

**Owner.** #413 (driver round-trip verification).

**Severity claimed.** medium - it blocks a documented keyless path, and it is the reason #413's vocabulary acceptance cannot be met even with perception configured.

### What was observed

With `DRIVER_DOM_URL=http://127.0.0.1:8797/` declared, the driver reports `sources: ["dom"]` and its health text still states "health, verify and vocabulary are intentionally keyless". Running `POST /api/driver/step` with `action: vocabulary`, `schema: dom` returned **200** with `ok: false`, `reason: decision_not_usable`, `stopped_at: decision`, `cost_usd: 0.0`, while `keyed: false`. The same call with `action: read_dom` stops at the same stage and reason.

So a path the driver's own health text advertises as keyless is gated on the keyed decision tier. The step record names the stage (`decision`), not capture, so this is not the earlier `no_capture` condition.

### Why it is not a duplicate

`driver-decision-tier-unkeyed` (#413, filed 2026-11-18) records that a step without `DRIVER_JEV_API_KEY` ends in `decision_not_usable`. This row records the narrower contract defect: the **vocabulary** action is documented in-process as keyless and still terminates at the keyed decision stage. One is "a key is needed for decisions"; this one is "a path promised not to need one does".

### Disposition

open - no fix attempted by this lane. Evidence: `413-result-t13.md` and `probe-turn13.json` in `evidence/lane-sessions/w2-2026-11-20/`. Product decision on whether vocabulary should bypass the decision tier (owner #413).
