## ADMISSIBILITY VERDICT - #469 (W2, steering 6996071450 item 3), reconciled with the re-run finding

**VERDICT: YES - a later eligible observation window is admissible - WINDOW NAMED, SCHEDULED, AND NOT YET RUNNABLE.** The row is **not** collapsed into the blocker string: the clause admits a forward window, the champion's identity holds at the current head, and the reason the window has not opened is a named wiring gap, not a lost corpus. **No completion credit is taken.**

### 1. The frozen input-selection clause, quoted

- **Measurable objective:** "Campaigns' terminal quality versus cost: defects found after stop (escapes) per campaign, and Jev/operator tokens spent per campaign, both recoverable from campaign ledgers (`record_stop` logs streak, basis, combined)."
- **Proposed work:** "Offline: replay past campaign pass histories from ledgers, simulate each comparator's stop point, and diff which findings/escapes each would have caught or missed; count breaker firings versus cycle lengths present in the data."

The clause selects by **record type and producer** - campaign pass histories, `record_stop` entries carrying streak, basis and combined, breaker firings and cycle lengths. "Past" is relative to the replay, not to a filing date. The acceptance clause's one data-dependent requirement ("at least 1 real 4-cycle") is likewise drawn from the replayed data.

### 2. Named window and its place in the frozen order

**W469.** Campaigns that **start** at or after the persistence landing on main and finish inside the window, each contributing its `record_stop` entry (streak, basis, combined), its escape count and its token spend. Closes at **30 campaigns** or **21 days** after the first campaign start, whichever comes first. Campaigns outside W469 are excluded from the verdict exactly as rows after `2026-11-18T21:28:28Z` are excluded from the frozen census.

**Frozen order slot 2**, immediately after #468 (slot 1). The brief's program steps run in filed order over it: observe, replay champion stop points, replay each comparator, diff findings/escapes caught or missed, count breaker firings against cycle lengths present, acceptance comparison. If the window holds no 4-cycle, the cycle-length sub-item closes as "no cycle-length change" on its own stated condition; that records the absence and waives nothing.

### 3. Identity condition - PASS at the current head

Head under test: `fb27ee895f43638cade271bcd9af33d2276b0136`. The whole `699f677..fb27ee89` diff of `harness/flush_loop.py` is **+12/-1 and instrumentation only**: `EventLedger.__init__` gains `trace`/`audit_enabled` and `append` gains a forwarding block at 374-396. `STOP_COMBINED`, `AXIS_FLOOR`, `ABSOLUTE_FLOOR`, `CLEAN_EXPANSION_STREAK`, `TAIL_PROMOTION_THRESHOLD`, `OscillationBreaker(max_cycle=3)`, `stop_ready`, `mark_stopped` and `record_stop` are untouched. No change inside the champion.

### 4. Why the window has not opened - the unblocker, named

The writer landed with #627 and **is never injected in a product path**. At `fb27ee89`, `git grep -n "trace=" -- "harness/*.py"` returns exactly one hit: the parameter declaration at `harness/flush_loop.py:374`. The campaign CLI entry builds the ledger bare - `harness/flush_loop.py:1261-1262`, `FlushLoop(ledger=EventLedger(chosen_ledger), ...)` - as do the canary paths at `:1050` and `:1056`. So the guard at `:392` is false in every product path, no `campaign.event` row reaches `decision_trace`, and campaign events still land only in the uncommitted `<campaign>.events.jsonl`. The 16/16 green rail at `ec664518` covers the writer, not the entry point: the only injector is `tests/test_decision_trace_469.py:235-236`.

Zero campaign rows exist since the landing, so the window has no first campaign to anchor its clock. **Unblocker: a product call site that constructs `EventLedger` with a `DecisionTrace` writer**, after which W469's clock opens at the first real campaign start and this verdict needs no re-decision.

### 5. Reconciliation with the re-run finding already on the record

Comment **7009570013** on this issue attempted the window at `17906e2c` and reported it not startable, with identity PASS and this same wiring gap. The sergeant's preflight re-run at `fb27ee89` verified that the trace family and its emitters work when a sink is injected; that is a different question from whether a product campaign run persists a replayable history, and it is the second question W469 needs answered. **Yes-but-blocked**, therefore - not the unrecoverable string, because the missing piece is a call site that can exist, not a corpus that was lost.

### 6. What would change this verdict

- If a campaign run at a head where the writer **is** injected produces `record_stop` rows without streak/basis/combined, that shortfall is filed against the brief rather than filled by inference.
- If the identity condition fails at window close, the row takes `frozen inputs unrecoverable - obligation unresolved`, W469 is void, no credit is taken.

No regenerated approximation authenticates a lost campaign, and no campaign will be synthesized to fill the window. Nothing here restates a mechanism's rules; the register home is #466, and the earlier ruling on this brief is 7003243188.
