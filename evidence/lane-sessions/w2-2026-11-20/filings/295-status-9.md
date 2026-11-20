## W2 lane turn 9 — DONE / WIP / NEXT / BLOCKERS — main `a7ca742e`, 2026-11-20

**Acks, in order.** Comm lock read at turn start and after each filing. Newest oversight `7005085362` (the #627 D12 audit cause) is addressed to **W1**: it names `decision_trace.py:102,166,172,177,181,203` and assigns the cure to W1, so no W2 act is taken on it — recorded here so the ack is not missing. `7004064953` (W3 review-cure) and `7004817604` (W1 addendum) read; neither routes to W2. Steering `7002214498` and `6996071450` remain governing.

**Sergeant's blocker (2) is stale.** His checkpoint listed "#621 BEHIND (W2 update owed)" at head `5f3930fa`. The rebase landed earlier: #621 is at `e010c9d98df622afacf2c6519b661e9b1af9240d`, **base `main`, mergeable MERGEABLE, mergeState UNSTABLE** (CircleCI rail 15/15 success context-by-context including `audit`; the UNSTABLE state comes from non-required GitHub Actions check-runs that always fail on the billing lock). #623 is likewise at `23f0b2b6951d098b2f7c088d8d3ce3ae2ec37348`, MERGEABLE, same rail.

---

### DONE

**1. Provider ceiling is not a key limit — named unblocker corrected (#415).** Zero-spend read of OpenRouter's `/key` at `583120b4`: HTTP 200, `limit_remaining 1.5`, `usage_daily 0`, free-model quota 1000/1000. The serve log prints `key_remaining=$1.500000` on the same key. A bounded paid ask (run `6097567437c4`) still terminated `error` / `provider_spend_limit` in ~30 s, while a direct `openrouter/free` call on that same key returned HTTP 200 at `cost 0`. **The blocker is account credit, not the key limit**; raising the key limit cannot clear it. Filing: comment `7006424771` on #415.

**2. #415 re-run on the $0 lane — the Jev approval path refused the answer.** Run `add821eb7c09` (`POST /api/chat` -> 201, `allow_paid:false`): status `needs_iteration`, tier `web-research`, model `accounts/fireworks/models/nemotron-lightning-3p5-30b-a3b`, Jev `answer_sufficient 0.06` against threshold 0.70 with `plan_required 0.45`. Spend **$0.000114** (Jev ledger), model spend $0.00, session spent $0.0. Acceptance: ask + Jev path + model/spend/verdict **MET**; exact-plan/decline coverage **NOT MET**. No completion credit taken. Gates: product Jev seq 81518 `escalate`, Lucas Gate v2 `pass`.

**3. Two new defects observed in that run.** `freelane-reasoning-in-answer` — the answer field is the model's scratchpad, with the required `HARNESS_DEFER:` line last; `web_used:true` with 5 web records, **0 addressing the question**, none preceded by an approved query-bound plan. Rows staged for `docs/found-in-use.md` (below).

**4. #422 verification at `583120b4` — gate exists, path does not call it.** `harness/citation_verify.py` implements the deterministic contract (closed-set statuses, DOI normalisation, field-by-field compare, passage hash + locator, `not_verifiable` on every retrieval failure). But **no resolver is implemented anywhere** (`crossref|openalex|doi.org|datacite` -> no matches in `harness/`) and **`citation_verify` has no call site outside itself**. End-to-end acceptance **NOT MET**; the 2026-10-28 finding is partly cured at library level. Filing: comment `7006435161` on #422. Gates: Jev seq 81519 `investigate`, Lucas `pass`.

**5. #567 surfaces re-checked at `583120b4`.** With the owner token, `/api/chat/sessions`, `/api/chat/history`, `/api/ledger/tail`, `/api/status` all answer **200** (unauthenticated still 401): the audit's "log store not available" limitation is cured for future audits; the three-turn transcript's untimed window is unchanged. Filing: comment `7006435712` on #567. Gates: Jev seq 81520 `escalate`, Lucas `pass`.

**6. #413 driver probe at `583120b4`.** Driver starts on `8798`, health `keyed:false`; `read_dom` and `vocabulary` both return `ok:false, reason:no_capture, stopped_at:capture` — "no configured source serves that class; nothing was tried. Configured sources: ['none']". Round-trip **NOT MET**; unblockers are configuration (`DRIVER_DOM_URL`/`DRIVER_CLI_COMMAND`/`DRIVER_MCP_COMMAND`+`DRIVER_MCP_TOOL`/`DRIVER_SCREEN=1`, plus an input backend or `DRIVER_ALLOW_WRITE=1` to act), none of which this lane set. Filing: comment `7006516696` on #413. Gates: Jev seq 81521 `investigate`, Lucas `pass`.

---

### WIP

Nothing in flight. No background process, no port held beyond this turn's `:8797` serve, which is stopped at turn end.

### NEXT

1. Publish this turn's artifacts as a dedicated evidence PR (same shape as #626), so the run records are reviewable without regeneration.
2. Stage two `docs/found-in-use.md` rows (`freelane-reasoning-in-answer` -> #415, `citation-gate-unwired` -> #422) for the first docs PR after #621/#623 land, to avoid a conflicting insertion at the same table tail.
3. Re-run W468/W469 unchanged at the new head the moment the sergeant confirms a persistence unblocker has landed.

### BLOCKERS

| Item | Blocker, by name |
|---|---|
| #415 paid lane | OpenRouter **account credit exhausted**; `key_remaining` reports the unused key limit and not the payable balance |
| #415 coverage clause | no approved query-bound plan record before web retrieval (product behaviour, owner #415/#342) |
| #422 end to end | no resolver implementation and no call site; wiring is product work the lane may not do |
| #413 round-trip | no perception source configured; acting additionally needs an input backend or `DRIVER_ALLOW_WRITE=1` |
| #412 steps 4-7 | owner-signed-in GUI window not granted |
| #467 count | provisional until #626 (`c01e01182c`) is on main; 28 recorded cases = 27 keyed answers + 1 fail-closed fallback |
| W468/W469 | no persistence unblocker landed |

**SHAs.** main `a7ca742e7e1002f28099a45ff3c9021d3a164687`; operated head `583120b436ce747c40be8543c4fa8cbf686cb48b`; #621 `e010c9d98df622afacf2c6519b661e9b1af9240d`; #623 `23f0b2b6951d098b2f7c088d8d3ce3ae2ec37348`; #626 `c01e01182c7b845195bf7e8901ddf8c18a0e8ece`.
