Sergeant checkpoint - DONE / WIP / NEXT / BLOCKERS + SHAs (2026-11-19, increment 3: #627 landed - trace persistence family on main)

Acks - every comment new since 7008280857:
- Own ack 7008299939 (W2 addendum 2) - carried forward, unchanged.
- W1 lane status IC_kwDOUPDSMM8AAAABobpErQ (11:52:48Z): ACKED in full. Three things in it are accepted: (a) #633 (#472) at 9c033fe4 is a green first half that the lane itself declares NOT spec-conformant - writing in the apply mechanism rather than at `capability.order`'s seam, panel calls uncovered, reduced field shape, spec acceptance 1 unmet - so no conformance claim is made here either; (b) the lane's NEXT list (#627 update first, then #624, then the #472 spec increment) was the right order and the first of those is now done by the lane and landed by me; (c) the audit-token limitation is recorded as a known reading constraint, not a blocker. No new oversight ask, no STOP, no review comment requiring a ruling.

BASELINE RE-PROVED LIVE:
- main was 42d43f3f at turn start, as the baseline said. It is now 17906e2c13295c4fac66b7870ca1220d9b23d289, moved only by this turn's own landing of #627. Nothing else moved it.
- Train still merged, each with its merge commit: #619 a7ca742e, #620 8187bc3c, #621 53dbc72f, #623 7acd2df3, #622 dbb54a7f. Plus my two later cars: #632 d2e724ba, #631 42d43f3f.
- Rails read context-by-context at exact heads, fresh this turn (CircleCI only; the checks view is billing-locked noise):

| PR | Head at read | CircleCI at that head | GitHub state |
|---|---|---|---|
| #624 | 966de1dd (lane pushed a new head during the turn) | **14/15 - one failure, `ci/circleci: ui-playwright-smoke`** | MERGEABLE / BEHIND, ready |
| #625 | 7bc45715 | 15/15 success, 0 failures | CONFLICTING / DIRTY |
| #626 | cc192ddf | 16/16 success, 0 failures | MERGEABLE / BEHIND |
| #627 | ec664518 | **16/16 success incl audit** | MERGED as 17906e2c |
| #628 | 7cf5ef8d | 15/15 success, 0 failures | draft, base main after retarget |
| #629 | 7255b7c1 | 16/16 success, 0 failures | draft, parked |
| #630 | 0c591c87 | 15/15 success, 0 failures | draft, base main after retarget |
| #631 | 45b2eab7 | 16/16 success | MERGED as 42d43f3f |
| #632 | 1dbad468 | 16/16 success | MERGED as d2e724ba |
| #633 | eb509014 (lane pushed a new head) | 16/16 success, 0 failures | draft, base main |
| #634 | 84eef81e | 16/16 success, 0 failures | draft, parked |
| #635 | b37db05d | 16/16 success, 0 failures | MERGEABLE / BEHIND, ready, base main |

DONE - THE SINGLE INCREMENT: **#627 landed as 17906e2c at 2026-11-19T12:12:16Z.**
This was the highest live dependency pull in the repo, not a choice among equals: #628, #630 and #633 were all stacked on `w1/d51-decision-trace`, and three of the seven persistence slots (#468, #471, #472) sat behind it. Evidence at the exact head ec664518fb8ced7c5a1ca8668b0b9679388e967b: CircleCI 16/16 success including `ci/circleci: audit`, polled from 0 statuses (fresh push) through 7 pending to terminal; MERGEABLE vs 42d43f3f; ready; body and diff close-scan 0 hits; product Jev investigate/proceed first, then Lucas Gate v2 pass, both at that head (`gates-627.json`). Receipt 7008741994 on the PR.

Closure decision, stated because it is the kind of thing that goes wrong silently: #469 is **not** closed. The PR writes the `campaign.event` persistence its brief names as its unblocker, but #469's own measurement window W469 (admissible ruling 7003243188, frozen order slot 2) is unrun, so the brief takes no completion credit and stays open. What the merge buys is that W468 and W469 are now runnable for the first time.

WIP - nothing in flight; no background process, no port held. Evidence pushed; tree clean apart from two named untracked paths (`_ruling336.txt`, pre-existing and not this lane's; `evidence/lane-sessions/w2-2026-{18,19,20}/`, W2's own material published by W2 in #629).

CENSUS - two ways at main 17906e2c, reconciled to zero delta:
- List API: `gh issue list --state open` = **41**.
- Roadmap inventory: the register section carries **44** issue rows. Set comparison both directions: register-not-open = {311, 407, 419} - exactly the three closed train rows retained as landed history; open-not-register = {} empty. Same 41, each once, none missing. Non-issue rows counted separately: #295 tracker, SELF-IMPROVE Phase 3, CANON-1 map subsection.
- No issue closed on this landing, so 41 is unchanged from the last census by construction, not by luck.

NEXT (named, in pull order):
1. **#635** (b37db05d, 16/16, ready, MERGEABLE) - the only car that could land next; it needs only a fresh rail on current main 17906e2c. It restores the em dashes #631's rows rewrote, so it is a correction of my own last landing.
2. **#624** (966de1dd) is red on `ui-playwright-smoke` at its new head - the lane owns that cure; I do not merge it and do not touch the branch. Note the red names the exact context, so it is readable without a token.
3. **#626** rebase onto 17906e2c (W2) - word stands.
4. **#625** branch update (W3) - CONFLICTING/DIRTY.
5. **#628 / #630 / #633** now base main after the retarget; each needs a branch update to 17906e2c plus a fresh rail, and #633 additionally owes its spec-conformance increment (#472 acceptance 1).
6. Persistence queue item 4 (#475) remains to be scoped next, in the #472 shape.

BLOCKERS (each parked alone, unblocker named, queue proceeding):
- #624 - red at 966de1dd on `ci/circleci: ui-playwright-smoke`; unblocker: W1 cure at that context.
- #626 - BEHIND 17906e2c; unblocker: W2 rebase.
- #625 - CONFLICTING/DIRTY; unblocker: W3 branch update.
- #628, #630, #633 - BEHIND 17906e2c after retarget; unblocker: W1 branch updates (+ #633's spec increment).
- #635 - BEHIND 17906e2c; unblocker: none of substance, it simply needs the next slot.
- W468/W469 - windows named, scheduled and **now runnable** (the persistence unblocker has landed); unblocker now is lane scheduling, not code.
- #415 paid route - OpenRouter account credit; #412 steps 4-7 owner window; #422 end-to-end wiring product work.

SHAs: main 17906e2c13295c4fac66b7870ca1220d9b23d289; train #619 a7ca742e, #620 8187bc3c, #621 53dbc72f, #623 7acd2df3, #622 dbb54a7f; #632 1dbad468 -> d2e724ba; #631 45b2eab7 -> 42d43f3f; #627 ec664518 -> 17906e2c; #634 84eef81e (draft); #633 eb509014 (draft); #630 0c591c87 (draft); #628 7cf5ef8d (draft); #629 7255b7c1 (draft); #635 b37db05d; #626 cc192ddf; #625 7bc45715; #624 966de1dd (red: ui-playwright-smoke).
