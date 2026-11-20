## Intake classification - `campaign-trace-writer-unwired` (#469)

**Symptom key.** `campaign-trace-writer-unwired`

**First seen.** 2026-11-20

**Observed at.** `17906e2c13295c4fac66b7870ca1220d9b23d289`

**Owner.** #469 (Champion Audit: flush-loop stop bar and oscillation breaker).

**Severity claimed.** high for this family. The merge that was accepted as #469's persistence unblocker does not change what a campaign run records: the writer is reachable only when a caller injects it, and no product caller does.

### What was observed

- `harness/flush_loop.py:374` adds a `trace` parameter to `EventLedger.__init__`; `harness/flush_loop.py:392-396` forwards each appended event to `DecisionTrace.campaign_event` when a writer is present.
- `git grep -n "trace=" 17906e2c -- "harness/*.py"` returns exactly one hit: that parameter declaration. No product construction supplies a writer.
- The campaign CLI entry builds the ledger bare: `harness/flush_loop.py:1261-1262`, `FlushLoop(ledger=EventLedger(chosen_ledger), ...)`. The canary paths at `:1050` and `:1056` are equally bare.
- Therefore the forwarding block is dead in every product path, and campaign events still land only in `<campaign>.events.jsonl` - the surface #623 already filed as never committed or retained.
- The 16/16 green rail at `ec664518` does not cover this: the only constructor that injects a writer is `tests/test_decision_trace_469.py:235-236`.

### Why it is not a duplicate

`flush-campaign-ledgers-uncommitted` (filed at `699f677`, PR #623) records that no sidecar is retained or archived. This row records the state *after* #627: a retention path now exists in code and is still not reached in use. The first is "no archive exists"; this one is "the archive that landed is not wired to the producer". Both remain true and both point at #469.

### Disposition

open - no fix attempted by this lane; the wiring call site is product work owned by #469. Evidence: this filing; the W469 re-run attempt `469-rerun-at-17906e2c.md`; gate receipts `gates-rerun.json`.
