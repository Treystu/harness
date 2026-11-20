## W2 — #415 re-run after the daily reset: paid route still refuses (402) while the key surface reports headroom; the $0 lane ran the ask and Jev refused the answer

Register home: #466. Nothing fixed by this lane; no product code touched.

**Revision under test.** Operator tree HEAD `583120b436ce747c40be8543c4fa8cbf686cb48b`, served by `python -m harness serve --host 127.0.0.1 --port 8797` (own port; the operator UI on `:8765` untouched). Identity line: `serving harness 0.5.1 at commit v0.5.1-167-g583120b`. No other lane process was restarted or stopped.

### 1. The named unblocker has changed shape, not cleared

The 2026-11-18 filing named three unblockers: owner credit, the daily reset, or an authorised alternate route. The daily reset has happened, and the provider's own key surface agrees:

| Read | Result |
|---|---|
| `GET https://openrouter.ai/api/v1/key` (zero spend) | **HTTP 200** — `limit 1.5`, `limit_remaining 1.5`, `limit_reset daily`, `usage_daily 0`, free-model quota `1000/1000` remaining |
| serve log at the same moment | `[OK] using key 'sk-or-v1-361...a57', key_limit=$1.5, key_remaining=$1.500000 (resets: daily)` |
| one bounded GUI ask on the paid lane (`POST /api/chat`, `web:true`) | run `6097567437c4`, **status `error`, `error_kind: provider_spend_limit`**, terminal in ~30 s, `known_cost_usd: null` |
| direct free-route call, same key (`openrouter/free`) | **HTTP 200**, `cost 0` — the key itself is accepted and can serve a $0 route |

So the refusal is **not** the key's daily limit, which is what the surface and the serve log both advertise. Paid calls are refused while the same key's $0 route answers, which is the signature of account-level credit (\#415's `spend-key-remaining-stale` row, now reproduced after a reset). The blocker, restated by name: **the OpenRouter account behind this key has no payable credit; `key_remaining` reports the unused key limit and not the payable balance.**

### 2. The $0 lane ran the ask, end to end

Same prompt as the 2026-11-18 attempt, same GUI entry point (`POST /api/chat` -> **201**, run `add821eb7c09`), one change: `allow_paid:false`.

| Field | Recorded |
|---|---|
| status | `needs_iteration` (no completion claimed) |
| intent / tier | `conversation` / `web-research` (native, `source: jev_request_workflow`) |
| model | `accounts/fireworks/models/nemotron-lightning-3p5-30b-a3b` |
| Jev semantic verdicts | `answer_sufficient 0.06` (threshold 0.70, passed `false`), `plan_required 0.45`, `iteration_required 0.47` |
| stop reason | `Jev review did not authorize another bounded answer attempt` |
| run cost field | `0.003059` (model spend on the free route is 0; see §3) |
| session spend | `ceiling 0.2, spent 0.0` |

The Jev approval path is therefore exercised live on a real ask and it **refused the answer**: the semantic gate ran, scored the lane's output below threshold and stopped rather than promoting it. That is the behaviour the issue asks to see.

### 3. Two defects observed in that same run

- **The reasoning stream is the answer.** The `response` field is the model's internal scratchpad, including scratch copy ("Defer message: ...", "Let me consider: ...", "Final decision: ..."), with the required line appended at the very end: `HARNESS_DEFER: MCP specification revision and exact publish URL require web search tools, which are not usable in this lane; only pre-gathered evidence is accessible.` A user reading the answer gets the chain of thought first and the defer line last. New symptom, owner #415: `freelane-reasoning-in-answer`.
- **`web_used: true` with no on-query source.** Five web records were produced for an MCP-specification question — `entire.io` (fetch, failed), `en.wikipedia.org/wiki/Research`, `researchgate.net`, `scholar.google.com`, `entire.com` — none addressing the question, and none preceded by an approved, query-bound plan record. Zero of five on-query; the defer is honest, but the capability record shows retrieval happening before the plan the issue requires be approved.

Spend accounting: Jev ledger delta across the run is **$0.000114** (2523 -> 2524 calls); model spend on the $0 route is **$0.00**; the `0.003059` in the run result is a routing estimate, not a billed amount, and no `known_cost_usd` was recorded. Total billed spend for this turn: **$0.000114**, bounded and below the 0.20 session ceiling.

### 4. Acceptance, per the issue's own clauses

| Clause | Result |
|---|---|
| one real ask through the GUI with the Jev semantic approval path | **MET** — run `add821eb7c09`; keyed Jev verdicts above |
| model, spend, verdict recorded | **MET** — model and all three Jev values above; spend `$0.000114` |
| spend kept bounded; no paid attestation re-run | **MET** — no attestation run; no paid route billed |
| exact proposed query/source plan, Jev accept/revise/decline, network-call count; zero calls on decline/failure | **NOT MET** — 5 web records before any plan record; no approve/decline of an exact query to report |

No completion credit is taken: the issue stays open on the coverage clause and on the paid-route blocker.

**Unblocker, by name and restated.** Owner adds payable credit to the OpenRouter account behind `sk-or-v1-361…a57` (raising the *key* limit changes nothing — it already reports full). The reasoning-leak and plan-order findings are code facts at this head and need no unblocker.


**Gates, in order.** Product Jev (keyed `jev-1.14.0`, caller `w2-champion-audit`, site `audit_admissibility`, ledger seq 81518): verdict `escalate`, supported 0.12, cost $2.7426e-05. Lucas Gate v2 (typed track): `status: pass`, artifact `5f94a61f7a04cbf1`. The Jev verdict is reported as returned, not re-run for a friendlier verdict; the disposition above rests on the observed run, not on the gate label.
