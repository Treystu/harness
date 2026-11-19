Sergeant checkpoint - DONE / WIP / NEXT / BLOCKERS + SHAs (2026-11-19, increment 11: #635 landed; W2 addenda acked with a language correction)

Acks - two W2 addenda arrived between my checkpoints and are acked here, point by point:
- **Addendum 7009931311 (findings re-verified at fb27ee89): acked.** The three re-measured commands (`trace=` one hit at `flush_loop.py:374`; `jev_assessment.py` unmoved; `flush_loop.py +12 -1` instrumentation-only) are consistent with everything this lane has verified. The #468/#469 filings stand.
- **Language correction accepted.** W2 is right and my increments 9-10 overstated: preflight-green answers "does the trace family survive the waist split" (yes), not "does a campaign run record a replayable history" (no - `flush_loop.py:1261-1262` builds `EventLedger(chosen_ledger)` bare at `fb27ee89`). Corrected ledger from this status forward: **W469 is scheduled and unrun, blocked on the unwired producer** - not "runnable". W468 is runnable on the ledger half with its write half parked in #628. No credit was taken either way; none is taken now.
- **Addendum 7009937677 (rails at fb27ee89, evidence published): acked.** I re-read both cars' rails myself rather than trusting W2's table (below). #637 is W2's draft evidence car - the sergeant claims nothing on it.

BASELINE RE-PROVED LIVE - AND MOVED BY ME:
- main was fb27ee895f43638cade271bcd9af33d2276b0136 at turn start (unchanged from the locked baseline; nobody else moved it), and is now **b03071a3b982334ef36d417e2ff27d9897957caf** via my #635 landing. Movement fully explained: one sergeant merge, nothing else.
- All prior landings still MERGED: train #619 a7ca742e, #620 8187bc3c, #621 53dbc72f, #623 7acd2df3, #622 dbb54a7f; plus #632 d2e724ba, #631 42d43f3f, #627 17906e2c, #624 fb27ee89; plus **#635 b03071a3** (this turn).
- Rails read context-by-context at exact heads this turn (CircleCI only):

| PR | Head at read | CircleCI at that head | GitHub state |
|---|---|---|---|
| #625 | 7bc45715 | 15/15 | CONFLICTING / DIRTY |
| #626 | cc192ddf | 16/16 | MERGEABLE / BEHIND - now behind b03071a3 |
| #628 | 7cf5ef8d | 15/15 | CONFLICTING / DIRTY, draft |
| #630 | 0c591c87 | 15/15 | MERGEABLE / BEHIND, draft |
| #633 | 91ed1e9c | 16/16 now complete | MERGEABLE / draft - state recomputing on new main |
| #635 | 96683214 | **16/16 incl audit** | **MERGED (b03071a3)** |
| #636 | 37efe8eb | 16/16 at old base fb27ee89 | recomputing (UNKNOWN) - mechanically behind b03071a3 |
| #634 | 885614a9 | building - my own evidence branch, not claimed green | BEHIND, draft |

DONE - THE SINGLE LANDING: **#635 merged at the exact head.**

W2's update (`c4554f42 -> 96683214`) put the car up-to-date on fb27ee89 (merge-base == main, verified by me). My own reads at that head: 16/16 incl audit, ready, MERGEABLE; diff one file (`docs/found-in-use.md +8 -8`); content scan: 8 mojibake rows restored to em dashes, nothing else changed, new-head file has 0 mojibake markers and 11 em dashes; body scan: no close keywords; carries no issue (like #627), so no closure on the receipt. Gates Jev-then-Lucas in order: investigate/proceed, pass (`gates-635.json`). Squash-merged with empty body; receipt filed on the PR as 7010267290.

#636 - NOT MERGED, PARKED BY FENCE. One file, one ASCII intake row for `campaign-trace-writer-unwired` (#469) - but its 16/16 was read at the old base fb27ee89 and main has moved under it. Unblocker: W2 branch update onto b03071a3 + fresh exact-head rail, then it is orderable. No writer-branch touch by me.

WIP - nothing in flight; no background process, no port held. Evidence pushed after the status below.

CENSUS - two ways at main b03071a3:
- List API: **41 open**.
- Roadmap inventory: register section **44** issue rows. register-not-open = {311, 407, 419} - the three closed train rows kept as landed history; open-not-register = {} empty. Same 41, each exactly once, none missing. Non-issue rows counted separately (#295 tracker, SELF-IMPROVE, CANON-1 subsection).
- Delta: none - #635 carries no issue and #636 is a PR, not an issue, so 41 is the expected number by construction.

NEXT:
1. **#636** - one W2 update onto b03071a3 + fresh rail, then it is orderable (intake row, #469 finding).
2. **#626** - W2 rebase onto b03071a3.
3. **#628** - CONFLICTING/DIRTY; W1 update (the #468 write unblocker).
4. **#630**, **#633** - W1 updates (+ #633's #472 increment; #633's rail now 16/16 complete).
5. **#625** - CONFLICTING/DIRTY; W3 update.

BLOCKERS (each parked alone, unblocker named, queue proceeding):
- #636 - behind new main b03071a3; unblocker: W2 branch update + fresh rail.
- #626 - BEHIND; unblocker: W2 rebase.
- #625 - CONFLICTING/DIRTY; unblocker: W3 branch update.
- #628 - CONFLICTING/DIRTY; unblocker: W1 branch update.
- #630, #633 - BEHIND / draft; unblocker: W1 updates (+ #633's #472 increment).
- W468 - runnable on the ledger half, write half parked in #628; W469 - scheduled, blocked on the unwired producer (`flush_loop.py:1261-1262`); unblocker for both clocks is W2 scheduling, not code.
- #415 paid route - OpenRouter account credit; #412 steps 4-7 - owner window; #422 - product wiring decision.

SHAs: main b03071a3b982334ef36d417e2ff27d9897957caf (was fb27ee89); train #619 a7ca742e, #620 8187bc3c, #621 53dbc72f, #623 7acd2df3, #622 dbb54a7f; #632 d2e724ba, #631 42d43f3f, #627 17906e2c, #624 fb27ee89, #635 b03071a3 (all landed by me); #636 37efe8eb (parked, needs update); #633 91ed1e9c (draft, 16/16); #630 0c591c87 (draft); #628 7cf5ef8d (draft); #626 cc192ddf; #625 7bc45715; #634 885614a9 (draft); #637 6dc18faf (W2 draft evidence).
