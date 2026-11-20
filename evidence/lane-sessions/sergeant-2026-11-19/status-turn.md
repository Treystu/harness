Sergeant checkpoint - DONE / WIP / NEXT / BLOCKERS + SHAs (2026-11-19, increment 2: #631 landed, persistence queue item 3 scoped)

Acks - every comment new since 7008014890:
- W2 turn-10 addendum (IC_kwDOUPDSMM8AAAABobY3Hg, 11:40:15Z): ACKED in full. #632/d2e724b and the map of record 7007760683 acknowledged; #631 replayed onto d2e724b with no content change at 45b2eab7 and its body naming that head (rule 9 satisfied); queue items 1 and 2 stay closed with windows W468/W469 named and unrun, fallback string declared. Nothing in that addendum needed correction - the head it named is the head I landed.
- W1's #630 delivery (IC_kwDOUPDSMM8AAAABobETiw, acked at 7008014890) stays acked; its rail re-read this turn at 0c591c87: 15/15 success, MERGEABLE, draft. No new W1/W3 comment has appeared since.

BASELINE RE-PROVED LIVE (not from memory):
- main is 42d43f3fa7355905ce2425d772473d97b748f7da. It moved from the locked d2e724ba for exactly one reason, this turn's own landing (#631), recorded below. d2e724ba came from last turn's #632 landing; nothing else moved it.
- Train confirmed merged, each with its merge commit: #619 a7ca742e, #620 8187bc3c, #621 53dbc72f, #623 7acd2df3, #622 dbb54a7f.
- Rails read context-by-context at exact heads (CircleCI only; the checks view is billing-locked noise):

| PR | Head | CircleCI at exact head | GitHub state |
|---|---|---|---|
| #624 | 80c1c0f8 | 15/15 success, 0 failures | MERGEABLE / BEHIND |
| #625 | 7bc45715 | 15/15 success, 0 failures | CONFLICTING / DIRTY |
| #626 | cc192ddf | 16/16 success, 0 failures | MERGEABLE / BEHIND |
| #627 | 43891d83 | 15/15 success, 0 failures | MERGEABLE / BEHIND |
| #630 | 0c591c87 | 15/15 success, 0 failures | MERGEABLE / UNSTABLE, draft, base w1/d51-decision-trace |
| #632 | 1dbad468 | 16/16 success, 0 failures | MERGED (receipt 7007943103) |
| #634 | 3092f645 | 16/16 success, 0 failures | MERGEABLE / BEHIND, draft (now head 48e8915 after this turn's evidence push) |

DONE
1. LANDED #631 -> 42d43f3f at 2026-11-19T11:49:39Z. Exact head 45b2eab7a4b999c05c0f0c855b0aa4cbe8a3c1aa: CircleCI 16/16 success including ci/circleci: audit, polled from 1 pending (audit) to terminal; MERGEABLE vs d2e724ba; ready; docs-only diff; body and diff close-scan 0 hits. Product Jev investigate/proceed first, Lucas Gate v2 pass second, both at that head (gates-631.json). Receipt 7008246380 on #631. Carries no issue, closes nothing - the three intake rows route to #415, #342, #422, all still open.
2. ADVANCED THE CONTINUOUS QUEUE, increment named: W1 persistence queue item 3 of 7 (#472) now carries a scoped spec, comment 7008217920 on its carrier, with the full queue table posted on #466 as 7008226901. The spec is grounded in the code at main d2e724ba, not in prose: site harness/capability.py::ordered_pool (line 814), the ordering decision harness/capability.py::order_pool (line 715), callers harness/apply.py:172 and harness/panel.py:239; the eight fields to persist (task, free_tier, call_lane, pool_given, scored, dropped, direct_reinserted, ordered, advisory); and five observable acceptance conditions - replayable from rows alone, byte-identical without the path, refusals write nothing, no new sink or segment, same inputs same order.
3. Published the increment's evidence: pushed sergeant/evidence-2026-11-19 to 48e89151 (spec, queue feed, #472 and #631 gate receipts).

WIP - nothing in flight; no background process, no port held. Working tree clean on sergeant/evidence-2026-11-19 with everything pushed. Two untracked paths remain and are named, not hidden: _ruling336.txt (pre-existing, not this lane's) and evidence/lane-sessions/w2-2026-{18,19,20}/ (W2's own material, published by W2 in #629).

CENSUS - two ways at main 42d43f3f, reconciled row by row:
- List API: gh issue list --state open = 41.
- Roadmap inventory: the register section carries 44 issue rows. Set comparison both directions: register-not-open = {311, 407, 419} - exactly the three closed train rows retained as landed history; open-not-register = {} empty. So the same 41 open issues, each exactly once, and zero missing.
- Non-issue rows also counted: the #295 tracker row, the SELF-IMPROVE Phase 3 row, and last turn's CANON-1 map subsection. No delta to explain; 41 matches the expectation exactly. No landing this turn carried an issue, so the count is unchanged from last turn by construction.

NEXT (named, each at its unblocker):
1. #627 branch update onto 42d43f3f (owner W1) - now the single highest-value unblocker in the repo, because #628 and #630 are stacked on it and three of the seven persistence slots (#468, #471, #472) sit behind it.
2. #626 rebase onto 42d43f3f (owner W2) - word stands; #467's count stops being provisional when it lands.
3. #624 branch update onto 42d43f3f (owner W1) - never blocks the train, never lands below 15/15.
4. #625 branch update (owner W3) - CONFLICTING/DIRTY, the only car that cannot even rebase cleanly without a content decision.
5. Queue item 4 (#475: per-attempt http_status + attempt timestamps) to be scoped next turn, in the same shape as #472's spec.

BLOCKERS (each parked alone, unblocker named, queue proceeding):
- #627, #624 - BEHIND 42d43f3f; unblocker: W1 branch updates.
- #626 - BEHIND 42d43f3f; unblocker: W2 rebase.
- #625 - CONFLICTING/DIRTY; unblocker: W3 branch update.
- #634 - BEHIND 42d43f3f, draft, parked behind the queue by choice.
- W468/W469 - windows named and scheduled, unrun; unblocker: a persistence change landing on main (none of #620/#621/#622/#623/#631/#632 is one).
- #415 paid route - OpenRouter account credit, not the key limit; #412 steps 4-7 owner window; #422 end-to-end wiring product work.

SHAs: main 42d43f3fa7355905ce2425d772473d97b748f7da; train #619 a7ca742e, #620 8187bc3c, #621 53dbc72f, #623 7acd2df3, #622 dbb54a7f (all MERGED); #632 1dbad468 -> d2e724ba MERGED; #631 45b2eab7 -> 42d43f3f MERGED; #634 48e89151 (draft); #630 0c591c87 (draft); #628 7cf5ef8d (draft); #629 7255b7c1 (draft); #626 cc192ddf; #627 43891d83; #625 7bc45715; #624 80c1c0f8.
