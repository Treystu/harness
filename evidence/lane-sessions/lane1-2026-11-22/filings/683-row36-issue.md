# Allow verification to cross consecutive signed drop runs

Part of #683, finding 36 (P1). Verified against `main` `8fc28a0e` on
2026-11-25: still present.

## Current evidence

harness/ledger_compaction.py:431 `crosses_gap` requires one run with `first_seq == prev_seq + 1` and `last_seq == seq - 1`; `_coverage_runs` (:242) splits runs whenever the classification reason changes, so two contiguous signed runs across one gap cannot compose.

## The finding

**

When adjacent eligible rows have different classification reasons, `_coverage_runs()` emits separate drop runs, but this check requires one run to span the entire gap between retained entries. For example, compacting `jev_eval → test-provenance offer → successful canary_probe → jev_eval` succeeds, yet a fresh loader reports verification failure at the second `jev_eval`. The omission is fully signed, but neither individual run matches both retained neighbors. Compose contiguous runs with matching hash boundaries so valid compaction does not break verification and block evidence export.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `harness/ledger_compaction.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/618#discussion_r4617725763
