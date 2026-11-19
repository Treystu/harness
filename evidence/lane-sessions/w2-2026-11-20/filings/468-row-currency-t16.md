## W468 — admissibility row re-measured at main `d916a7b` (W2, steering 6996071450 item 3)

**Ruling of record:** `7003242752` (ADMISSIBLE), reconciled verdict `7010347186`.
This filing does not re-decide either. It re-measures the identity condition and
the input state at the head this turn ran against, and states the exact row text
the register carries. **No completion credit is taken in either direction.**

### 1. The frozen input-selection clause this ruling rests on — quoted, cited

From this issue's filed brief, verbatim:

- **Measurable objective:** "Agreement between gate disposition and downstream
  outcome (gate-passed work later found defective; gate-blocked work later shown
  sound), measurable from lane ledgers and re-assessment records."
- **Proposed work:** "Offline replay of recorded aspect distributions through
  champion and both comparators; measure investigate-rate, block-rate, and
  disposition flips; hand-label a sample for outcome agreement."

The clause selects inputs by **record type and producer** and states no freeze
instant, corpus date or campaign id; labeling is performed at replay time. That
is why a forward window satisfies it by its own terms rather than by
approximation (ruling `7003242752`, section 1).

### 2. Identity condition at `d916a7b` — PASS (measured, not asserted)

Head under test: `d916a7bbe3de878dc842635c69f9f1cf3e619bfa`.

- `git diff --stat 699f677b d916a7b -- harness/jev_assessment.py` → **empty**.
  The champion's decision logic is byte-identical to the freeze revision
  `699f677b`.
- The one file the range does touch, `harness/flush_loop.py` (+12/-1), belongs to
  #469's mechanism (instrumentation added by #627), not to this champion.
- `git diff --stat fb27ee89 d916a7b -- harness/jev_assessment.py
  harness/flush_loop.py harness/lucas_gate.py` → **empty**, so the identity
  measured for the verdict at `fb27ee89` still holds at today's head.

Nothing inside this champion has moved. The window is not voided.

### 3. Input state at `d916a7b` — still no writer

`git grep -nE "open\(|write_text|ledger|EventLedger" d916a7b --
harness/jev_assessment.py` → **0 matches**: the module still has no persistence
path for aspect distributions, dispositions or outcome labels. The writer is
**PR #628**, live state this turn: head `e8ef0b63`, **draft**, **BEHIND**,
unmerged.

**Unblocker unchanged: #628 merged.** On that landing W468 starts at once; no
part of this ruling is re-decided then.

### 4. Row text for the register (verbatim)

> #468 — ADMISSIBLE (ruling 7003242752; reconciled verdict 7010347186).
> Window W468: the first 200 recorded assessment records produced by the
> unchanged decision path after a persistence surface for aspect distributions
> lands on main, each carrying its aspect distribution, the gate disposition
> taken and one recorded downstream outcome label; contiguous; closes at 200
> records or 14 days after its first record, whichever comes first. Frozen order
> **slot 1**. Identity re-verified at `d916a7b`: `harness/jev_assessment.py`
> byte-identical to `699f677b`. Not runnable yet: #628 (draft, `e8ef0b63`) is
> the named unblocker. No completion credit taken.

### 5. The one event that would collapse the row

If the identity condition fails at window close, the row takes the literal text
**frozen inputs unrecoverable - obligation unresolved** and W468 is void with no
credit. That is the fallback, not a second chance. No regenerated approximation
authenticates a lost run.

Mechanism rules live at #466 and are not restated here; this filing reports an
admissibility outcome only.

Gates on this filing: product Jev (keyed) `investigate` on a non-change
admissibility filing, destructive well below the 0.15 band; Lucas Gate v2
typed track `status: pass` — `gates-turn16.json`.
