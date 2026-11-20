## ADMISSIBILITY VERDICT - #468 (W2, steering 6996071450 item 3), reconciled with the re-run finding

**VERDICT: YES - a later eligible observation window is admissible - WINDOW NAMED, SCHEDULED, AND NOT YET RUNNABLE.** The row is **not** collapsed into the blocker string: the window is admissible on this brief's own frozen input-selection clause, its champion's identity holds at the current head, and the reason it has not run is a named, open, unmerged car. **No completion credit is taken.**

### 1. The frozen input-selection clause, quoted

- **Measurable objective:** "Agreement between gate disposition and downstream outcome (gate-passed work later found defective; gate-blocked work later shown sound), measurable from lane ledgers and re-assessment records."
- **Proposed work:** "Offline replay of recorded aspect distributions through champion and both comparators; measure investigate-rate, block-rate, and disposition flips; hand-label a sample for outcome agreement."

The clause selects by **record type and producer** - recorded aspect distributions, lane ledgers, re-assessment records - and states no freeze instant, corpus date or campaign id. "Recorded" is unqualified and labeling is done at replay time, so a forward window does not substitute a different corpus, infer an input or back-fill a pre-freeze row.

### 2. Named window and its place in the frozen order

**W468.** The first **200** recorded assessment records produced by the unchanged decision path after a persistence surface for aspect distributions lands on main, each carrying (a) its aspect distribution, (b) the gate disposition taken and (c) one recorded downstream outcome label. Contiguous; closes at 200 records or **14 days** after its first record, whichever comes first. Records outside W468 are excluded from the verdict exactly as rows after `2026-11-18T21:28:28Z` are excluded from the frozen census.

**Frozen order slot 1** of the re-run queue - first of the briefs carrying an unresolved input obligation - ahead of #469 (slot 2). The brief's own program steps run over it in filed order: observe, replay champion, replay the modal-band and point-estimate comparators, hand-label for outcome agreement, acceptance comparison on the stated margin.

### 3. Identity condition - PASS at the current head

Head under test: `fb27ee895f43638cade271bcd9af33d2276b0136` (current `origin/main`). `git diff --stat 699f677 fb27ee89 -- harness/jev_assessment.py` is **empty**: band assignment, the strict-majority rule, `GREEN_MIN`, `FLEX_MIN`, the disposition ladder and the missing-aspect refusal are byte-identical to the freeze revision. Instrumentation added around a decision would not void the window; nothing inside this champion has moved at all.

### 4. Why the window has not run - the unblocker, named

W468 needs a writer for aspect distributions. At `fb27ee89` there is none: `harness/jev_assessment.py` still has no ledger or file write path (its only output calls are `print` at 409 and 411, plus an in-memory list append at 330). The writer is **PR #628**, state **draft, CONFLICTING/DIRTY**, head `7cf5ef8d`, unmerged - confirmed live this turn.

**Unblocker: #628 merged.** On that landing, W468 starts at once with no further ruling; nothing about this verdict has to be re-decided.

### 5. Reconciliation with the re-run finding already on the record

Comment **7009569291** on this issue attempted the window at `17906e2c` and reported it not startable, with identity PASS and the same #628 unblocker. This verdict is that finding read back through the clause: the attempt failed on a missing producer, not on admissibility, so the correct record is **yes-but-blocked**, not the unrecoverable string. The sergeant's checkpoint language that "W468 and W469 are now runnable" does not hold for this brief: #627 landed #469's persistence, not #468's, and #628 is still CONFLICTING/DIRTY.

### 6. What would change this verdict

- If #628 lands with a writer that emits distributions **without** disposition or outcome, W468 still cannot close, and the shortfall is filed against the brief rather than filled by inference.
- If the identity condition fails at window close, the row takes `frozen inputs unrecoverable - obligation unresolved`, W468 is void and no credit is taken. That is the fallback, not a second chance.

No regenerated approximation authenticates a lost run. Nothing here changes a mechanism's rules; the mechanism's register home is #466, and the earlier ruling on this brief is 7003242752.
