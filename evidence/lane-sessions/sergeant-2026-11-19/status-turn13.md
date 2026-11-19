Sergeant checkpoint - DONE / WIP / NEXT / BLOCKERS + SHAs (2026-11-19, increment 13: #636 park re-affirmed at unchanged state; queue re-proved at exact heads)

Acks - nothing new to ack. Between my checkpoint 7010355183 (13:21:36Z) and this status there is **no new oversight comment, no lane status, no review and no STOP** on #295: read at turn start and again after the census below.

BASELINE RE-PROVED LIVE - UNMOVED:
- main is b03071a3b982334ef36d417e2ff27d9897957caf - unchanged from the locked baseline; nobody moved it this turn.
- All prior landings still MERGED: train #619 a7ca742e, #620 8187bc3c, #621 53dbc72f, #623 7acd2df3, #622 dbb54a7f; plus #632 d2e724ba, #631 42d43f3f, #627 17906e2c, #624 fb27ee89, #635 b03071a3.
- Rails read context-by-context at exact heads this turn (CircleCI only):

| PR | Head at read | CircleCI at that head | GitHub state |
|---|---|---|---|
| #625 | 7bc45715 | 15/15 | CONFLICTING / DIRTY |
| #626 | cc192ddf | 16/16 | MERGEABLE / BEHIND b03071a3 |
| #628 | 7cf5ef8d | 15/15 | CONFLICTING / DIRTY, draft |
| #630 | 0c591c87 | 15/15 | MERGEABLE / BEHIND, draft |
| #633 | 4c76ca09 (NEW head - W1 acting on its unblocker) | 7/15, 0 fail, 8 pending - building, not claimed green | MERGEABLE / BLOCKED, draft |
| #634 | a3100f2f (= my evidence push) | 7/15, 0 fail, 8 pending - building, not claimed green | MERGEABLE / BEHIND, draft |
| #635 | 96683214 | 16/16 incl audit | **MERGED (b03071a3)** |
| #636 | 37efe8eb (unmoved) | 16/16 at old base fb27ee89 | **MERGEABLE / BEHIND b03071a3** |
| #637 | 09190bdf (NEW head - W2 evidence) | 1/6, 0 fail, 5 pending - building, not claimed | MERGEABLE / BEHIND, draft |

DONE - THE SINGLE OUTCOME: **#636 park re-affirmed, forensics unchanged, hazard restated not re-claimed.**

Neither main nor the #636 branch moved since last turn, so last turn's forensics stand verbatim by construction and are cited, not redone: merge-base(`37efe8eb`, `b03071a3`) = `fb27ee89` (re-verified this turn); diff `b03071a3 -> 37efe8eb` still 10+/8- on `docs/found-in-use.md` (re-verified this turn) - 8 lines of stale mojibake overwriting #635's cure, 2 lines of genuine intake row. The car is BEHIND under strict protection and unmergeable as-is.

Unblocker (unchanged, W2's act): branch update onto `b03071a3` keeping main's 8 fixed em-dash rows and adding only the `campaign-trace-writer-unwired` row, then a fresh 16/16 rail at the new head. No writer-branch touch by me; no merge below green at the exact head; no close keywords in the body; carries no issue.

Movement noted, not acted on: **#633's new head `4c76ca09`** means W1 is working its unblocker (update + #472 increment) - its rail is mid-build and claimed by no one; **#637's new head `09190bdf`** is W2's draft evidence, likewise unclaimed. Both stay parked until green at their exact heads.

Gates on this park, recorded as returned: product Jev **escalate**, disposition proceed; Lucas Gate v2 pass (`gates-636park2.json`). Third consecutive escalate on a publish-not-merge act; published verbatim as before.

WIP - nothing in flight; no background process, no port held. Evidence pushed after the status below.

CENSUS - two ways at main b03071a3:
- List API: **41 open**.
- Roadmap inventory: register section **44** issue rows. register-not-open = {311, 407, 419} - the three closed train rows kept as landed history; open-not-register = {} empty. Same 41, each exactly once, none missing. Non-issue rows counted separately (#295 tracker, SELF-IMPROVE, CANON-1 subsection).
- Delta: none - a re-affirmed park takes no credit, so 41 is the expected number by construction.

NEXT (sergeant's order):
1. **#636** - W2 hazard-aware update + fresh rail, then it lands (preferred next).
2. **#626** - W2 rebase onto b03071a3.
3. **#633** - W1's new head mid-rail; landable only when 16/16 at `4c76ca09` AND up-to-date AND marked ready by W1 (the ready-mark is the owning lane's act).
4. **#628** - CONFLICTING/DIRTY; W1 update (the #468 write unblocker).
5. **#630** - W1 update (draft).
6. **#625** - CONFLICTING/DIRTY; W3 update.

BLOCKERS (each parked alone, unblocker named, queue proceeding):
- #636 - behind b03071a3 + mojibake hazard; unblocker: W2 hazard-aware update + fresh rail.
- #626 - BEHIND; unblocker: W2 rebase.
- #633 - new head mid-rail + draft; unblocker: W1 rail completion + ready-mark.
- #625 - CONFLICTING/DIRTY; unblocker: W3 branch update.
- #628 - CONFLICTING/DIRTY; unblocker: W1 branch update.
- #630 - BEHIND / draft; unblocker: W1 update.
- W468 - ledger-half runnable, write half parked in #628; W469 - scheduled, blocked on the unwired producer; unblocker for both clocks is W2 scheduling, not code.
- #415 paid route - OpenRouter account credit; #412 steps 4-7 - owner window; #422 - product wiring decision.

SHAs: main b03071a3b982334ef36d417e2ff27d9897957caf; train #619 a7ca742e, #620 8187bc3c, #621 53dbc72f, #623 7acd2df3, #622 dbb54a7f; #632 d2e724ba, #631 42d43f3f, #627 17906e2c, #624 fb27ee89, #635 b03071a3 (all landed by me); #636 37efe8eb (parked); #633 4c76ca09 (W1 new head, mid-rail, draft); #630 0c591c87 (draft); #628 7cf5ef8d (draft); #626 cc192ddf; #625 7bc45715; #634 a3100f2f (my draft, building); #637 09190bdf (W2 draft evidence, building).
