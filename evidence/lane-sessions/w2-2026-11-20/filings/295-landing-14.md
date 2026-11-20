## W2 turn 14 - retraction landed on main d916a7b; trigger still armed

Comm lock: #295 re-read after addendum `7018323562`. No new oversight comment addressed to W2. No STOP.

The sergeant merged #640 (`9992715`, 16/16 green at that head). Verified directly on main, not from the merge notice:

- `origin/main` = `d916a7b` ("docs(intake): retract the keyless-vocabulary row (#413) (#640)").
- `driver-vocabulary-keyless-claim-false` occurrences on main: **0**. `docs/found-in-use.md` row count: **14**. The surviving keyless row `driver-decision-tier-unkeyed` is present (1) and untouched.

So the false row is off main and the index is back to its pre-#639 content. #413's verdict remains PARTIAL as corrected in `7018097385`; #413 stays open on its acting-tier blocker.

Trigger re-read at the same time: **#628 still open, draft, head `e8ef0b63`** - the W468 persistence unblocker has not landed, so no frozen brief was re-run and none was approximated.

Nothing held: no process, no port. Evidence on `w2/turn11-evidence` (#637); its rail restarts on the addendum commit `12ab449b` (16 contexts, 8 ok / 8 pending / 0 fail at read) and gets a context-by-context read next turn.
