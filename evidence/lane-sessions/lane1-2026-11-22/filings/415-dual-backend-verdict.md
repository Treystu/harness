# #415 verdict - OpenRouter credit retest and the OpenRouter/Fireworks dual backend, end to end

**Base under test:** `main` `280ee3d4f99bf3d33645ddde21b243cebe0b191b`.
**Instrument:** `evidence/lane-sessions/lane1-2026-11-22/dual_backend_verify.py`,
receipt `evidence/lane-sessions/lane1-2026-11-22/dual-backend-receipt.json`.
**Calls made:** three bounded probes across three runs (two the first two runs,
one after the attribution fix), total billed **$0.00000664**. No attestation
re-run, no campaign, no GUI ask in this pass.

## 1. The credit block is lifted - retested live, not assumed

The 2026-11-19 park named the unblocker exactly: OpenRouter *account credit*
exhausted, not the key limit, evidenced by the paid route returning **402** while
`/api/v1/key` advertised `limit_remaining 1.5`. Re-read at this head:

| Read | 2026-11-19 (parked) | 2026-11-22 (this pass) |
| --- | --- | --- |
| `GET /api/v1/key` | 200, `limit_remaining 1.5` | 200, `limit_usd 1.5`, `spend_usd 0`, `remaining_usd 1.5`, reset daily |
| paid dispatch | **402** `spend limit exhausted` | **200**, content `ok` |
| usage envelope | no cost (never reached a model) | `prompt_tokens 11`, `completion_tokens 2`, **`cost 0.00000094` reported by the provider** |

The 402 is gone on a real paid call, and the cost is the provider's own reported
number rather than an estimate (`cost_estimated: false`). The owner's word is
therefore confirmed by the surface that contradicted it before.

## 2. Both backends answer through the product path

Not a hand-built payload: both calls go through `chat_routed`, the single entry
point the panel seats, the judge, apply and verify use.

| Backend | Model | Status | Answer | Tokens (prompt/completion) | Cost |
| --- | --- | --- | --- | --- | --- |
| OpenRouter | `deepseek/deepseek-v4.1-flash` | 200 | `ok` | 11 / 2 | $0.00000094 (reported) |
| Fireworks | `accounts/fireworks/models/deepseek-v4p1-flash` | 200 | `ok` | 11 / 2 | $0.0000057 (estimated from committed rates) |

## 3. Each model reaches its own endpoint, and only its own

The transport recorded the URL of every call:

| Check | Result |
| --- | --- |
| OpenRouter model -> `openrouter.ai/api/v1/chat/completions` | yes |
| Fireworks model -> `api.fireworks.ai/inference/v1/chat/completions` | yes |
| OpenRouter model ever hit the Fireworks URL | no |
| Fireworks model ever hit the OpenRouter URL | no |

The OpenRouter lane rewrites the id it sends (`:floor` appended by the tier
floor) while still posting to the OpenRouter endpoint; the receipt attributes by
URL plus model family for that reason.

## 4. No silent single-backend degradation: a disabled backend refuses

Identity, not configuration, decides the backend, and a backend that is
disabled refuses instead of quietly serving from the other one:

| Probe | Result |
| --- | --- |
| `backend_for_model` - OpenRouter id / Fireworks path / `muse-` / `groq/` | `openrouter` / `fireworks` / `meta` / `groq` |
| `route_for_model(fireworks path, fireworks_enabled=False)` | **refused**: "is a Fireworks path but fireworks is disabled (HARNESS_FIREWORKS_ENABLED)" |
| `route_for_model(openrouter id, openrouter_enabled=False)` | **refused**: "has no enabled provider: OpenRouter is disabled (HARNESS_OPENROUTER_ENABLED)" |

The failure mode this rules out is the one the issue asked about: a Fireworks
model silently answered by OpenRouter (or the reverse) when one backend is
unavailable. Neither direction degrades.

## 5. Failover behaves: idle while healthy, real when exhausted

Measured on `harness.availability`, whose ledger is the one owner of "is this
model servable now":

| State | `failover_models([openrouter], [fireworks])` |
| --- | --- |
| primary healthy | `[]` - **no substitution** |
| primary recorded `account_funding` (HTTP 402) | `[accounts/fireworks/models/deepseek-v4p1-flash]` - substitution |
| the selected failover target resolves to | `fireworks` |
| `$0` route (`deepseek-v4.1-flash:free`) while the balance is dry | **still selectable** |

So failover is not a standing preference for the second backend: it engages on
the primary's recorded provider exhaustion, the target is a genuinely different
backend, and a dry balance does not disable the $0 route.

## 6. Two observations from the same pass (recorded, not fixed here)

- **Fireworks sends no cost accounting.** The raw envelope at
  `api.fireworks.ai/inference/v1/chat/completions` carries `prompt_tokens`,
  `completion_tokens`, `total_tokens` and a details block - no `cost`. The
  product estimates it from committed rates in `_ensure_fireworks_accounted`,
  but that runs only when a governor is threaded into `_chat_fireworks`. An
  ungoverned dispatch therefore records no cost at all, and a naive reader of
  the usage envelope sees $0.00. Filed here as a low-severity accounting note
  next to `spend-key-remaining-stale`, not as a new issue: the governed lanes
  are covered, and the estimate is labelled when it is produced.
- **The 16-token starvation is reproducible.** At `max_tokens 16` with the
  default effort, the Fireworks deepseek path returned **HTTP 200 with empty
  `content`** and 16/16 completion tokens spent on `reasoning_content`. This is
  the #304 defect, reproduced on live traffic; the probe now sends
  `reasoning_effort: none` at 64 tokens, which is what the product's vote lanes
  do, and both backends then answer with `finish_reason: stop` and zero
  reasoning characters.

## 7. What this does and does not close

- **Proven:** the OpenRouter backend serves paid calls again at this head; the
  Fireworks backend serves its own model; the two never cross; a disabled
  backend refuses; failover engages only on recorded exhaustion.
- **Not claimed:** #415's own acceptance is a **live GUI ask through the Jev
  semantic approval path, with model, spend and verdict recorded, plus one
  external-research request with its exact query plan**. That is a GUI pass, not
  this probe, and the credit unblocker that stopped it is now cleared. The next
  bounded pass on #415 is that GUI ask; this filing is the backend half of the
  prerequisite and does not stand in for it.
