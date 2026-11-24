## Lane 1 check-in - 2026-11-22, pass 1 (LD-002 execution)

**Base:** `main` `280ee3d4f99bf3d33645ddde21b243cebe0b191b`, zero open PRs.
**Live reads this pass:** the head above, the open PR list, the #295 comment tail
(through `7073572374`), and the cloud lane's `standup/lane1-2026-11-21` filings
(`status-refresh-01.md`, `turn2-filings.md`, `467-measurement-record.md`).

**Cloud findings, read and not duplicated.** The cloud session did **not** land
the #422 call site. Its turn-2 filing proves the resolver still has no product
caller at `280ee3d4` - `grep -rn "citation_resolver\|CitationResolver\|DoiResolver"`
returns only `tests/test_citation_resolver.py` - and explicitly declines to run
an acceptance against a path that does not exist. So #422's remaining work is
unchanged and is this lane's: the report-path call site.

### DONE - the #415 delta

- **OpenRouter retested live, not assumed.** `GET /api/v1/key` -> 200, `limit_usd
  1.5`, `spend_usd 0`, `remaining_usd 1.5`; one real paid dispatch through
  `chat_routed` -> **200, content `ok`**, `prompt 11 / completion 2` tokens,
  `cost 0.00000094` **reported by the provider**. The 402 credit block is
  cleared on evidence.
- **Dual backend verified end to end.** Fireworks path -> 200 `ok` on
  `api.fireworks.ai`; OpenRouter model -> 200 `ok` on `openrouter.ai`; neither
  call crossed to the other endpoint; a disabled backend **refuses** by name
  instead of degrading; `failover_models` returns `[]` while the primary is
  healthy and the Fireworks path once the primary is recorded
  `account_funding`; the `$0` route stays selectable on a dry balance.
  **11/11 checks pass**, billed **$0.00000664** for the whole pass.
- **Filed on #415:** `7075425275` - Lucas Gate v2 `pass` (artifact `6ed47049`),
  product Jev `investigate` / `proceed` (supported 0.07, `jev-1.14.0`), receipt
  `gates-415-dual-backend.json`. It closes nothing: #415's own acceptance is the
  live GUI ask through the Jev semantic approval path, now unblocked and named
  as the next bounded pass there.

**One observation, recorded not fixed:** Fireworks' response envelope carries no
`cost` field (tokens and a details block only); the product's rate-based
estimate runs only when a governor is threaded into `_chat_fireworks`. Governed
lanes are covered; an ungoverned dispatch records no cost. Written into the #415
filing beside the existing `spend-key-remaining-stale` row. No new issue filed.

### Status

- **WIP:** #422 call site - the resolver exists and is tested, the product never
  calls it. This is a code car, not a re-measurement.
- **NEXT:** #422 call site -> PR -> rail at the exact head -> landing -> live
  acceptance; then the W469 measurement window, the #343/#344 closure records,
  finite deliverables in register order, and RSI #649-#652 in dependency order.
- **BLOCKERS:** none for the queue. #413 stays host-side (no `driver-core serve`
  on `127.0.0.1:8791`), unchanged from the cloud filing.
- **WAIT-STATE:** idle: none.
- **DIRECTIVES:** LD-002 executed in its stated order - re-read live state, do
  not duplicate the cloud lane, #415 first among the deltas.
