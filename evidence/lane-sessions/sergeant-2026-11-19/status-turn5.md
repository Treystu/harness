Sergeant checkpoint - DONE / WIP / NEXT / BLOCKERS + SHAs (2026-11-19, increment 5: #473 scoped from live code; #635 and #624 parked on writer-owned updates)

Acks - nothing new. Between my checkpoint 7008900528 (12:19:24Z) and this status there is **no new oversight comment, no lane status, no review and no STOP** on #295: read at turn start and again after each filing below (475 untouched, 473 at 7008977889, 466 at 7008989563). #624's head moved twice during the turn (966de1dd -> cb0a8eed -> 6c90298b), which is W1 acting on my named unblocker and is acknowledged here rather than treated as a review item.

BASELINE RE-PROVED LIVE:
- main is 17906e2c13295c4fac66b7870ca1220d9b23d289 - unchanged from the locked baseline; nobody moved it this turn.
- Five train PRs still MERGED: #619 a7ca742e, #620 8187bc3c, #621 53dbc72f, #623 7acd2df3, #622 dbb54a7f. Plus my later cars #632 d2e724ba, #631 42d43f3f, #627 17906e2c.
- Rails read context-by-context at exact heads this turn:

| PR | Head at read | CircleCI at that head | GitHub state |
|---|---|---|---|
| #624 | 6c90298b (moved twice this turn) | **pending 15/16, 1 pending, 0 failures** - still building at read time | MERGEABLE / BLOCKED, ready |
| #625 | 7bc45715 | 15/15 | CONFLICTING / DIRTY |
| #626 | cc192ddf | 16/16 | MERGEABLE / BEHIND |
| #627 | ec664518 | 16/16 incl audit | MERGED (17906e2c) |
| #628 | 7cf5ef8d | 15/15 | CONFLICTING / DIRTY, draft |
| #630 | 0c591c87 | 15/15 | MERGEABLE / BEHIND, draft |
| #633 | eb509014 | 16/16 | MERGEABLE / UNSTABLE, draft |
| #634 | 10601c25 | building (7/15, 8 pending) - my own evidence branch, not claimed green | MERGEABLE / BEHIND, draft |
| #635 | b37db05d | 16/16 incl audit | MERGEABLE / BEHIND, ready |

DONE - THE SINGLE INCREMENT: **persistence queue item 5 (#473) now carries a code-grounded scoped spec** - filed as 7008977889 on the carrier, indexed on #466 as 7008989563.

Built from code at `17906e2c`, every claim cited: `harness/router.py::_rotation_ordered`:91-111, the four rotation surfaces at 112 (`panel_pool`), 120 (`apply_pool`), 128 (`specialist_pool`), 136 (`escalation_pool`); `note_model_result`:64-82 as the only writer of the instance dict `_model_health`:51; `model_health`:84-90; and `harness/dynamic_allocation.py::rank_models_dynamically`:253-286, whose `scores` dict is computed and thrown away at the single `return sorted(...)` on :286. Health callers traced to `harness/apply_policy.py::_note_model_health`:285 (forwarding at 292) with eight invocation sites (171, 178, 394, 413, 426, 443, 464, 497).

Two findings the spec records, both from the code rather than from the brief's wording:
1. **The reason for an order is discarded where it is computed** - the ranker returns ids only, `_rotation_ordered` returns silently, and the health registry is in-memory, so a restart erases every observation and rotation silently reverts to declared order.
2. **The brief's "three configured pools" undercounts the decision surfaces** - there are four at this head, each a separate ordering decision. The spec makes `surface` a required field so the count is derivable from rows instead of from memory, and condition 8 asserts four distinct values appear.

Eight falsifiable acceptance conditions: order recomputable from the row (including the tie case where the stable sort must preserve declared order), absolute head pin, silence for unobserved pools, health replayable across a restart, sink-independence, byte-identical behaviour without the path, dedupe by call id, surface coverage. Contract: `router.health` (model, ok, errors_before/after, latency_ms, surface) and `router.rotation` (surface, pool_declared, pool_returned, head_pinned/head_model, health_snapshot, unrounded scores, config, rank_rule). Gates: product Jev investigate/proceed then Lucas Gate v2 pass (`gates-473spec.json`).

#635 - NOT MERGED, PARKED BY FENCE. Its head has **not moved** (still b37db05d) since last turn's disposition (7008883838): 16/16 incl audit, ready, content-final, but BEHIND 17906e2c, and strict protection refused the merge verbatim last turn. I did not use `--auto` or `--admin` and did not touch W2's branch. Unblocker: W2 branch update onto 17906e2c, then a fresh rail, then I land it.

WIP - nothing in flight; no background process, no port held. Evidence branch pushed after the status below.

CENSUS - two ways at main 17906e2c:
- List API: **41 open**.
- Roadmap inventory: register section **44** issue rows. register-not-open = {311, 407, 419} - the three closed train rows retained as landed history; open-not-register = {} empty. Same 41, each exactly once, none missing. Non-issue rows counted separately (#295 tracker, SELF-IMPROVE, CANON-1 subsection).
- Delta: none - this turn closed no issue (a spec filing takes no completion credit by design), so 41 is the expected number by construction.

NEXT:
1. **#635** - the closest landable car; needs one W2 branch update onto 17906e2c and a fresh rail.
2. **#624** - W1 is pushing new heads (two this turn); when a head is green context-by-context AND up to date on current main, it lands on 15/15 or better or not at all.
3. **#626** - W2 rebase onto 17906e2c.
4. **#628** - CONFLICTING/DIRTY; W1 branch update (it is the #468 unblocker).
5. **#630**, **#633** - W1 updates; #633 owes the #472 spec increment.
6. Queue item 6 (**#476**, ceiling refusals with outcomes + widened measured-spend join) is the next spec, in the #472/#473/#475 shape.

BLOCKERS (each parked alone, unblocker named, queue proceeding):
- #635 - BEHIND 17906e2c; unblocker: W2 branch update.
- #624 - mid-rail at 6c90298b and BLOCKED/BEHIND; unblocker: W1 update to a green head on current main.
- #626 - BEHIND; unblocker: W2 rebase.
- #625 - CONFLICTING/DIRTY; unblocker: W3 branch update.
- #628 - CONFLICTING/DIRTY; unblocker: W1 branch update.
- #630, #633 - BEHIND / draft; unblocker: W1 updates (+ #633's #472 increment).
- W468/W469 - runnable since #627; unblocker is lane scheduling, not code.
- #415 paid route - OpenRouter account credit; #412 steps 4-7 - owner window; #422 - product wiring decision.

SHAs: main 17906e2c13295c4fac66b7870ca1220d9b23d289; train #619 a7ca742e, #620 8187bc3c, #621 53dbc72f, #623 7acd2df3, #622 dbb54a7f; #632 d2e724ba, #631 42d43f3f, #627 17906e2c (all landed by me); #635 b37db05d; #624 6c90298b (15/16, 1 pending); #633 eb509014 (draft); #630 0c591c87 (draft); #628 7cf5ef8d (draft); #626 cc192ddf; #625 7bc45715; #634 10601c25 (draft).
