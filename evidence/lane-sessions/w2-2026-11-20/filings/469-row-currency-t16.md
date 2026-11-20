## W469 — admissibility row re-measured at main `d916a7b` (W2, steering 6996071450 item 3)

**Ruling of record:** `7003243188` (ADMISSIBLE), reconciled verdict `7010349175`.
This filing re-measures the identity condition and the input state at the head
this turn ran against, and states the exact row text the register carries. **No
completion credit is taken in either direction.**

### 1. The frozen input-selection clause this ruling rests on — quoted, cited

From this issue's filed brief, verbatim:

- **Measurable objective:** "Campaigns' terminal quality versus cost: defects
  found after stop (escapes) per campaign, and Jev/operator tokens spent per
  campaign, both recoverable from campaign ledgers (`record_stop` logs streak,
  basis, combined)."
- **Proposed work:** "Offline: replay past campaign pass histories from ledgers,
  simulate each comparator's stop point, and diff which findings/escapes each
  would have caught or missed; count breaker firings versus cycle lengths present
  in the data."

The clause selects inputs by **record type and producer**; "past" is relative to
the replay, not to a filing date, and the acceptance clause's one data-dependent
requirement ("at least 1 real 4-cycle") is likewise drawn from the replayed data
(ruling `7003243188`, section 1).

### 2. Identity condition at `d916a7b` — PASS (measured, not asserted)

Head under test: `d916a7bbe3de878dc842635c69f9f1cf3e619bfa`.

- `git diff --stat 699f677b d916a7b -- harness/flush_loop.py` is **+12/-1** and
  instrumentation only — the same change the verdict at `fb27ee89` characterised
  and measured; it adds a trace forwarding hook and moves nothing in the stop
  logic.
- `git diff --stat fb27ee89 d916a7b -- harness/flush_loop.py` → **empty**, so the
  identity measured then still holds at today's head.

Nothing inside this champion has moved. The window is not voided.

### 3. Input state at `d916a7b` — the writer is still never injected

`git grep -n "trace=" d916a7b -- "harness/*.py"` → **one** hit:
`harness/flush_loop.py:374`, the `EventLedger.__init__` parameter declaration. No
product call site constructs the ledger with a writer, so no campaign row
reaches a replayable history and the window still has no first campaign to anchor
its clock.

**Unblocker unchanged: a product call site that constructs `EventLedger` with a
`DecisionTrace` writer.** When it lands, W469's clock opens at the first real
campaign start; no part of this ruling is re-decided then.

### 4. Row text for the register (verbatim)

> #469 — ADMISSIBLE (ruling 7003243188; reconciled verdict 7010349175).
> Window W469: campaigns that start at or after the persistence landing on main
> and finish inside the window, each contributing its `record_stop` entry
> (streak, basis, combined), its escape count and its token spend; closes at 30
> campaigns or 21 days after the first campaign start, whichever comes first.
> Frozen order **slot 2**, immediately after #468. Identity re-verified at
> `d916a7b`. Not openable yet: the writer exists but is injected at no product
> call site (`git grep "trace="` → only `harness/flush_loop.py:374`). No
> completion credit taken.

### 5. The one event that would collapse the row

If the identity condition fails at window close, the row takes the literal text
**frozen inputs unrecoverable - obligation unresolved** and W469 is void with no
credit. If a campaign produced stop rows without streak/basis/combined, that
shortfall is filed against the brief rather than filled by inference.

Mechanism rules live at #466 and are not restated here; this filing reports an
admissibility outcome only.

Gates on this filing: product Jev (keyed) `investigate` on a non-change
admissibility filing, destructive well below the 0.15 band; Lucas Gate v2
typed track `status: pass` — `gates-turn16.json`.
