## W2 turn 11 - queue item 4 attempted at 17906e2c: both windows blocked, one for a different reason than reported

Comm lock: #295 read at turn start, and again after each of this turn's filings. Oversight read and acked: increment-3 checkpoint (12:13:53Z), increment-4 checkpoint (12:19:24Z), and the ack of my turn-10 rail confirmation (7008788342). Nothing new after increment 4 required a ruling, and no STOP is on the thread.

### DONE - the re-runs were attempted, and neither window can start

Head under test: `17906e2c13295c4fac66b7870ca1220d9b23d289` (the #627 landing). Read live; main has not moved since.

**Identity condition - PASS for both briefs.** `git diff 699f677 17906e2c -- harness/jev_assessment.py` is empty; `harness/flush_loop.py` moved +12/-1 and the change is instrumentation only (`EventLedger` gains `trace`/`audit_enabled` and a forwarding block at 374-396). No threshold, ladder, streak, promotion rule or cycle cap changed. Neither window is voided by a change inside its champion, so the unrecoverable-blocker string is correctly **not** applied to either row.

**#468 - not startable, and the checkpoint's claim that it is runnable does not hold.** W468 needs recorded aspect distributions with disposition and outcome. `harness/jev_assessment.py` at this head still has no write path (only `print` at 409/411, unchanged from 699f677), and its persistence car is **#628**, which the same checkpoint lists as draft, CONFLICTING/DIRTY, head `7cf5ef8d`, unmerged. The two briefs were frozen on *different* persistence writes; #627 landed #469's, not #468's. Filed: #468 comment **7009569291**.

**#469 - writer landed, inert in use.** W469's unblocker was accepted as landed, but the forwarding block is dead in every product path:

- `git grep -n "trace=" 17906e2c -- "harness/*.py"` returns **one** hit - the parameter declaration at `harness/flush_loop.py:374`.
- The campaign CLI entry constructs the ledger bare: `harness/flush_loop.py:1261-1262`, `FlushLoop(ledger=EventLedger(chosen_ledger), ...)`; the canary paths at `:1050` and `:1056` are equally bare.
- So `if self.trace is not None` (`:392`) is false in product paths and no `campaign.event` row ever reaches `decision_trace`. Campaigns still write only `<campaign>.events.jsonl`.
- The 16/16 rail does not cover it: the only injector is `tests/test_decision_trace_469.py:235-236`, which constructs the writer by hand.
- Zero campaign rows exist since the landing, so the "30 campaigns or 21 days" window has no first campaign to anchor it. Synthesizing campaigns to fill it would be the regenerated approximation the ruling forbids.

Filed on the brief: #469 comment **7009570013**.

**Intake routed.** New row `campaign-trace-writer-unwired` (high, owner #469, observed `17906e2c`) via **PR #636**, head `5c36f1b6`, base `17906e2c`, one file, one ASCII row added, nothing rewritten. It is deduped against `flush-campaign-ledgers-uncommitted` (#623): that row is "no archive exists", this one is "the archive that landed is not wired to its producer".

**#635 - branch updated as asked, and the fresh rail is green.** Fast-forwarded onto current main; new head **`c4554f42`**, MERGEABLE, diff vs `17906e2c` is `docs/found-in-use.md +8 -8`, content re-read byte-wise at the new head: mojibake absent, 11 em dashes, 13 table rows, 0 CR bytes. CircleCI at `c4554f42`: **16/16 success, 0 failures, `ci/circleci: audit` success** - the car needs nothing further from W2 and can be taken on the sergeant's order.

**Gates, in order.** Product Jev (`jev-1.14.0`, caller `w2-champion-audit`, site `audit_admissibility`): #468 filing `investigate`/proceed, #469 filing `investigate`/proceed, intake classification **`escalate`**/proceed. Lucas Gate v2 typed track: `pass` on all three. Receipts in `gates-rerun.json`; the `escalate` is reported as returned and routes the severity call to oversight for confirmation on the record.

**#636 rail.** CircleCI at `5c36f1b6`: **16/16 success, 0 failures, `ci/circleci: audit` success**. Read at the exact head after the push, not inherited from another PR.

### WIP
Nothing in flight; no process, no port held. Both open W2 PRs sit green and wait on the sergeant's order, not on further W2 work.

### NEXT
1. On #628 landing (not merely rebased), run W468 unchanged at that head and publish the comparison on #468.
2. On a product call site that injects the trace writer, open the W469 clock at the first real campaign start and run the frozen replay; until then W469's blocker is that wiring, named on the brief and in #636.
3. #626's rebase remains W2's act but is outside this turn's fence; ready when the sergeant lifts it.

### BLOCKERS (each parked alone, unblocker named)
- **W468** - no assessment write path at `17906e2c`; unblocker: #628 merged (currently CONFLICTING/DIRTY).
- **W469** - trace writer never injected by a product caller; unblocker: the `EventLedger(chosen_ledger, trace=DecisionTrace(...))` call site in product code (product work, #469).
- **#415** paid route - OpenRouter account credit.
- **#412** steps 4-7 - owner-signed-in window.
- **#422** - product-owner wiring decision.

Evidence: `evidence/lane-sessions/w2-2026-11-20/filings/468-rerun-at-17906e2c.md`, `.../469-rerun-at-17906e2c.md`, `.../469-intake-row.md`, `.../gates-rerun.json`.
