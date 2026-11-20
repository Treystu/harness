Sergeant checkpoint - DONE / WIP / NEXT / BLOCKERS + SHAs (2026-11-19, increment 12: #636 parked with a named unblocker and a named merge hazard; queue re-proved)

Acks - nothing new to ack. Between my checkpoint 7010280412 (13:18:34Z) and this status there is **no new oversight comment, no lane status, no review and no STOP** on #295: read at turn start and again after the census below.

BASELINE RE-PROVED LIVE - UNMOVED:
- main is b03071a3b982334ef36d417e2ff27d9897957caf - unchanged from the locked baseline; nobody moved it this turn.
- All prior landings still MERGED: train #619 a7ca742e, #620 8187bc3c, #621 53dbc72f, #623 7acd2df3, #622 dbb54a7f; plus #632 d2e724ba, #631 42d43f3f, #627 17906e2c, #624 fb27ee89, #635 b03071a3.
- Rails read context-by-context at exact heads this turn (CircleCI only):

| PR | Head at read | CircleCI at that head | GitHub state |
|---|---|---|---|
| #625 | 7bc45715 | 15/15 | state recomputing on new main (was CONFLICTING/DIRTY) |
| #626 | cc192ddf | 16/16 | state recomputing (was MERGEABLE/BEHIND) |
| #628 | 7cf5ef8d | 15/15 | state recomputing (was CONFLICTING/DIRTY, draft) |
| #630 | 0c591c87 | 15/15 | state recomputing (was MERGEABLE/BEHIND, draft) |
| #633 | 91ed1e9c | 16/16 now complete | state recomputing (was MERGEABLE, draft) |
| #634 | 578b4d45 (new head - my own evidence push) | 7/15, 0 fail, 8 pending - building, not claimed green | BEHIND, draft |
| #635 | 96683214 | 16/16 incl audit | **MERGED (b03071a3)** |
| #636 | 37efe8eb (unmoved) | 16/16 at old base fb27ee89 | **MERGEABLE/BEHIND b03071a3** |
| #637 | 6dc18faf | 16/16 | state recomputing (was UNKNOWN, W2 draft evidence) |

DONE - THE SINGLE OUTCOME: **#636 parked alone with its unblocker and a merge hazard named, not merged.**

Forensics, all read live (no trust): merge-base(`37efe8eb`, `b03071a3`) = `fb27ee89` != main, so the car is BEHIND under strict protection and unmergeable as-is. The diff `b03071a3 -> 37efe8eb` on `docs/found-in-use.md` is 10 insertions / 8 deletions: 8 of those are the branch's stale mojibake rows overwriting the 8 rows #635 just cured on main, and only 2 (one row + blank line) are the genuine `campaign-trace-writer-unwired` intake row (`flush_loop.py:392-396` / `:1261-1262` / `:1050` / `:1056`, `tests/test_decision_trace_469.py:235-236`). A naive W2 update would resurrect the mojibake #635 just removed. Body scan: no close keywords; carries no issue.

Unblocker (W2's act, named precisely): branch update onto `b03071a3` that **keeps main's 8 fixed em-dash rows and adds only the intake row**, then a fresh 16/16 rail at the new head. Then it is orderable. No writer-branch touch by me; no merge below green at the exact head.

Gates on this park, recorded as returned: product Jev **escalate**, disposition proceed; Lucas Gate v2 pass (`gates-636park.json`). The escalate is published, not smoothed - it marks the mojibake-resurrection hazard above as worth oversight attention. Same handling as the #482 escalate last turn.

WIP - nothing in flight; no background process, no port held. Evidence pushed after the status below.

CENSUS - two ways at main b03071a3:
- List API: **41 open**.
- Roadmap inventory: register section **44** issue rows. register-not-open = {311, 407, 419} - the three closed train rows kept as landed history; open-not-register = {} empty. Same 41, each exactly once, none missing. Non-issue rows counted separately (#295 tracker, SELF-IMPROVE, CANON-1 subsection).
- Delta: none - a park takes no credit, so 41 is the expected number by construction.

NEXT (sergeant's order):
1. **#636** - W2 update per the unblocker above + fresh rail, then it lands (preferred next: smallest surface, intake-only, content already verified row-by-row).
2. **#626** - W2 rebase onto b03071a3 (whichever of #636/#626 W2 brings up-to-date green first is orderable; #636 preferred).
3. **#628** - CONFLICTING/DIRTY; W1 update (the #468 write unblocker).
4. **#630**, **#633** - W1 updates (+ #633's #472 increment; #633's rail now complete 16/16).
5. **#625** - was CONFLICTING/DIRTY; W3 update.

BLOCKERS (each parked alone, unblocker named, queue proceeding):
- #636 - behind b03071a3 + mojibake hazard; unblocker: W2 update preserving #635's cure + fresh rail.
- #626 - BEHIND; unblocker: W2 rebase.
- #625 - was CONFLICTING/DIRTY; unblocker: W3 branch update.
- #628 - was CONFLICTING/DIRTY; unblocker: W1 branch update.
- #630, #633 - BEHIND / draft; unblocker: W1 updates (+ #633's #472 increment).
- W468 - ledger-half runnable, write half parked in #628; W469 - scheduled, blocked on the unwired producer; unblocker for both clocks is W2 scheduling, not code (W2 addenda acked last turn).
- #415 paid route - OpenRouter account credit; #412 steps 4-7 - owner window; #422 - product wiring decision.

SHAs: main b03071a3b982334ef36d417e2ff27d9897957caf; train #619 a7ca742e, #620 8187bc3c, #621 53dbc72f, #623 7acd2df3, #622 dbb54a7f; #632 d2e724ba, #631 42d43f3f, #627 17906e2c, #624 fb27ee89, #635 b03071a3 (all landed by me); #636 37efe8eb (parked, needs W2 update); #633 91ed1e9c (draft, 16/16); #630 0c591c87 (draft); #628 7cf5ef8d (draft); #626 cc192ddf; #625 7bc45715; #634 578b4d45 (my draft, building); #637 6dc18faf (W2 draft evidence).
