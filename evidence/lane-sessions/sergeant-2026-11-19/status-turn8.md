Sergeant checkpoint - DONE / WIP / NEXT / BLOCKERS + SHAs (2026-11-19, increment 8: #624 landed on 16/16; #635 re-parked on the new main)

Acks - nothing new to ack. Between my checkpoint 7009581193 (12:48:50Z) and this status there is **no new oversight comment, no lane status, no review and no STOP** on #295: read at turn start and again after each filing below (#624 receipt 7009644522, #635 routing 7009661670). W2's #635 update to `c4554f42` is new lane activity and is acknowledged here as progress acted on, not as a directive.

BASELINE RE-PROVED LIVE - main MOVED, by me, once:
- main was 17906e2c at turn start. It is now fb27ee895f43638cade271bcd9af33d2276b0136, moved only by this turn's landing of #624 at 2026-11-19T12:51:19Z. Nothing else moved it.
- Five train PRs still MERGED: #619 a7ca742e, #620 8187bc3c, #621 53dbc72f, #623 7acd2df3, #622 dbb54a7f. Plus my later cars #632 d2e724ba, #631 42d43f3f, #627 17906e2c, and now #624 fb27ee89.
- Rails read context-by-context at exact heads this turn (CircleCI only):

| PR | Head at read | CircleCI at that head | GitHub state |
|---|---|---|---|
| #624 | 6c90298b | **16/16 incl audit, 0 failures** | MERGED (fb27ee89) |
| #625 | 7bc45715 | 15/15 | CONFLICTING / DIRTY (recomputing post-merge) |
| #626 | cc192ddf | 16/16 | BEHIND fb27ee89 |
| #627 | ec664518 | 16/16 incl audit | MERGED (17906e2c) |
| #628 | 7cf5ef8d | 15/15 | CONFLICTING / DIRTY, draft |
| #630 | 0c591c87 | 15/15 | BEHIND fb27ee89, draft |
| #633 | 410a146c | **16/16, 0 failures (was 15/16+1 pending mid-turn)** | BEHIND fb27ee89, draft |
| #634 | 885614a9 | building - my own evidence branch, not claimed green | BEHIND fb27ee89, draft |
| #635 | c4554f42 (W2 updated mid-turn) | **16/16 incl audit, 0 failures** | BEHIND fb27ee89, ready |

DONE - THE SINGLE INCREMENT: **#624 landed as fb27ee89 at 12:51:19Z.**

It was the closest landable car by rail timing, not by preference: at turn start #624 was 15/16+1 pending and #635 was 11/16+5 pending. W1's head finished first; I gated it (product Jev investigate/proceed first, Lucas Gate v2 pass second, both at the exact head - `gates-624.json`), re-verified main/head/rail immediately before the merge (`main=17906e2c`, `head=6c90298b`, rail `success 16/16`), and merged through the PR. Receipt 7009644522.

Evidence at the exact head 6c90298b: 16/16 incl `ci/circleci: audit`, read context-by-context; MERGEABLE vs 17906e2c (the head's tree contains it, verified by merge-base); ready; no review required; body and diff close-scan 0 hits. W1's cure lands on 16/16 at the exact head, as routed since the restart: it never blocked the train and never landed below 15/15. Carries no issue, closes nothing - #308 stays open. Body pins `d2ac50e9` (rule-9 staleness, noted on the receipt for the lane's next touch).

#635 - GREEN BUT PARKED, by main movement, not by doubt. W2's update to `c4554f42` is verified green (16/16 incl audit, ready, content-final) - and it is BEHIND the new main `fb27ee89` (verified by merge-base), so strict protection would refuse it verbatim as it refused `b37db05d`. Routing note posted on the PR itself (7009661670). Unblocker: one more W2 update, onto `fb27ee89`, plus a fresh rail. It remains the next car I intend to take.

WIP - nothing in flight; no background process, no port held. Evidence pushed after the status below. No new delivery artifact this turn beyond the landing itself: last turn's W468/W469 preflight stands un-re-claimed (its checks were run at `17906e2c`; re-running at `fb27ee89` is queued as the next delivery increment once the tree settles).

CENSUS - two ways at main fb27ee89:
- List API: **41 open**.
- Roadmap inventory: register section **44** issue rows. register-not-open = {311, 407, 419} - the three closed train rows kept as landed history; open-not-register = {} empty. Same 41, each exactly once, none missing. Non-issue rows counted separately (#295 tracker, SELF-IMPROVE, CANON-1 subsection).
- Delta: none - this landing closed no issue (#308 stays open), so 41 is the expected number by construction.

NEXT:
1. **#635** - one W2 update onto fb27ee89 + fresh rail, then it lands.
2. **#626** - W2 rebase onto fb27ee89.
3. **#628** - CONFLICTING/DIRTY; W1 update (the #468 write unblocker).
4. **#630**, **#633** - W1 updates (+ #633's #472 increment; #633's rail is now green at 410a146c).
5. Re-run the W468/W469 preflight at fb27ee89 as the next delivery increment.
6. **#625** - CONFLICTING/DIRTY; W3 update.

BLOCKERS (each parked alone, unblocker named, queue proceeding):
- #635 - BEHIND fb27ee89; unblocker: W2 branch update.
- #626 - BEHIND fb27ee89; unblocker: W2 rebase.
- #625 - CONFLICTING/DIRTY; unblocker: W3 branch update.
- #628 - CONFLICTING/DIRTY; unblocker: W1 branch update.
- #630, #633 - BEHIND fb27ee89 / draft; unblocker: W1 updates (+ #633's #472 increment).
- W468/W469 - runnable (preflight stands, re-run queued on the new main); unblocker is W2 scheduling, not code.
- #415 paid route - OpenRouter account credit; #412 steps 4-7 - owner window; #422 - product wiring decision.

SHAs: main fb27ee895f43638cade271bcd9af33d2276b0136; train #619 a7ca742e, #620 8187bc3c, #621 53dbc72f, #623 7acd2df3, #622 dbb54a7f; #632 d2e724ba, #631 42d43f3f, #627 17906e2c, #624 fb27ee89 (all landed by me); #635 c4554f42; #633 410a146c (draft); #630 0c591c87 (draft); #628 7cf5ef8d (draft); #626 cc192ddf; #625 7bc45715; #634 885614a9 (draft).
