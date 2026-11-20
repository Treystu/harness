Sergeant checkpoint - DONE / WIP / NEXT / BLOCKERS + SHAs (2026-11-19, increment 6: #476 scoped from live code; slots 3-6 now all specified)

Acks - nothing new to ack. Between my checkpoint 7009362972 and this status there is **no new oversight comment, no lane status, no review and no STOP** on #295: read at turn start and again after each filing below (476 at 7009447036, 466 at 7009453445). #624 pushing a third head (`6c90298b`) is W1 acting on the named unblocker, acknowledged here as lane progress, not a directive.

BASELINE RE-PROVED LIVE:
- main is 17906e2c13295c4fac66b7870ca1220d9b23d289 - unchanged from the locked baseline; nobody moved it this turn.
- Five train PRs still MERGED: #619 a7ca742e, #620 8187bc3c, #621 53dbc72f, #623 7acd2df3, #622 dbb54a7f. Plus my later cars #632 d2e724ba, #631 42d43f3f, #627 17906e2c.
- Rails read context-by-context at exact heads this turn (CircleCI only):

| PR | Head at read | CircleCI at that head | GitHub state |
|---|---|---|---|
| #624 | 6c90298b | pending 15/16, 1 pending, 0 failures | MERGEABLE / BLOCKED, ready |
| #625 | 7bc45715 | 15/15 | CONFLICTING / DIRTY |
| #626 | cc192ddf | 16/16 | MERGEABLE / BEHIND |
| #627 | ec664518 | 16/16 incl audit | MERGED (17906e2c) |
| #628 | 7cf5ef8d | 15/15 | CONFLICTING / DIRTY, draft |
| #630 | 0c591c87 | 15/15 | MERGEABLE / BEHIND, draft |
| #633 | 410a146c (new head this turn) | pending 15/16, 1 pending, 0 failures | MERGEABLE / BLOCKED, draft |
| #634 | 90e5c9f8 | building (8/16, 8 pending) - my own evidence branch, not claimed green | MERGEABLE / BEHIND, draft |
| #635 | b37db05d | 16/16 incl audit | MERGEABLE / BEHIND, ready |

DONE - THE SINGLE INCREMENT: **persistence queue slot 6 (#476) now carries a code-grounded scoped spec** - filed as 7009447036 on the carrier, indexed on #466 as 7009453445.

Built from code at `17906e2c`, every claim cited: `harness/spend.py::assert_spend_allowed`:108-139 (with the `$0` no-refuse rule at `:121-124`), `SpendGovernor.record_actual`:967-1023 (reserve/ceiling refusals at :1001-1009, Fireworks at :985-989, Meta at :993-997, scope overages at :360), `harness/mission_record.py`:809/850 (pack-budget refusals that write nothing), the one recording path `harness/apply_policy.py`:60-78 (`status="rejected"`, `cost=0.0`, `tracked_cost=0.0`, `reported_cost=amount`) versus the silent chat/consent/convergence/mission-record paths, `harness/capability.py::measured_spend_by_model`:385-415 and its sole consumer at :985-991, and the import-layering constraint (`spend.py` `:17-34` stays selector-free, so the join arrives as data).

Two findings the spec records: (1) refusals are raised by six families and recorded by one - and even that row omits the numbers that made it a refusal; (2) the two spend totals (governor running totals vs ledger-settled sums) can legitimately drift and nothing detects it. Contract: `spend.refusal` (ceiling_kind, phase, label/model, lane, max_cost, spent, outstanding, ceiling, amount_attempted, overage, tracked_cost/reported_cost convention) and `spend.reconcile` (per-model governor_total, ledger_total, delta, unknown-liability remainder). Eight falsifiable conditions: one row per family with message-matching numbers, recomputable overage, `$0` silence, preserved fail-closed, reconcile with explained deltas, the measured-direction join (estimate-fits/measured-refuses refuses and names `measured_spend`), the existing `rejected` row keeping its shape while gaining the fields, byte-identical behaviour without the path. Gates: product Jev investigate/proceed then Lucas Gate v2 pass (`gates-476spec.json`). With slots 3-6 now specified, the queue's remaining unscoping is slot 7's delivery (#469's write has landed; its window is next) and slot 1's CONFLICTING #628.

#635 - NOT MERGED, PARKED BY FENCE. Head has **not moved** (still b37db05d): 16/16 incl audit, ready, content-final, but BEHIND 17906e2c; strict protection refused the merge verbatim last turn. No `--auto`, no `--admin`, no writer-branch touch. Unblocker: W2 branch update onto 17906e2c, fresh rail, then I land it.

WIP - nothing in flight; no background process, no port held. Evidence pushed after the status below.

CENSUS - two ways at main 17906e2c:
- List API: **41 open**.
- Roadmap inventory: register section **44** issue rows. register-not-open = {311, 407, 419} - the three closed train rows kept as landed history; open-not-register = {} empty. Same 41, each exactly once, none missing. Non-issue rows counted separately (#295 tracker, SELF-IMPROVE, CANON-1 subsection).
- Delta: none - this turn closed no issue (a spec filing takes no completion credit by design), so 41 is the expected number by construction.

NEXT:
1. **#635** - one W2 branch update onto 17906e2c and a fresh rail, then it lands.
2. **#624** - W1 is actively pushing (three heads this turn); when a head is green context-by-context AND up to date on current main, it lands on 15/15 or better or not at all.
3. **#626** - W2 rebase onto 17906e2c.
4. **#628** - CONFLICTING/DIRTY; W1 update (the #468 unblocker).
5. **#630**, **#633** - W1 updates (+ #633's #472 increment).
6. Slot 7 needs no spec by construction - #469's write landed with #627, so the next increment on the queue is delivery evidence, starting with the W468/W469 windows now that they are runnable.

BLOCKERS (each parked alone, unblocker named, queue proceeding):
- #635 - BEHIND; unblocker: W2 branch update.
- #624 - mid-rail at 6c90298b, BLOCKED/BEHIND; unblocker: W1 update to a green head on current main.
- #626 - BEHIND; unblocker: W2 rebase.
- #625 - CONFLICTING/DIRTY; unblocker: W3 branch update.
- #628 - CONFLICTING/DIRTY; unblocker: W1 branch update.
- #630, #633 - BEHIND / draft; unblocker: W1 updates (+ #633's #472 increment).
- W468/W469 - runnable since #627; unblocker is lane scheduling, not code.
- #415 paid route - OpenRouter account credit; #412 steps 4-7 - owner window; #422 - product wiring decision.

SHAs: main 17906e2c13295c4fac66b7870ca1220d9b23d289; train #619 a7ca742e, #620 8187bc3c, #621 53dbc72f, #623 7acd2df3, #622 dbb54a7f; #632 d2e724ba, #631 42d43f3f, #627 17906e2c (all landed by me); #635 b37db05d; #624 6c90298b (15/16, 1 pending); #633 410a146c (draft, 15/16, 1 pending); #630 0c591c87 (draft); #628 7cf5ef8d (draft); #626 cc192ddf; #625 7bc45715; #634 90e5c9f8 (draft).
