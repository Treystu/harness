# Prevent checkpoint appends from recursively compacting their source

Part of #683, finding 37 (P1). Verified against `main`
`8fc28a0e` on 2026-11-25: still present.

## Current evidence

harness/ledger.py:499 append() runs _rotate_if_needed() and then sweep_compaction() synchronously at the end of the same call; _compact_old_segment (:417) hands compact_segment `append_checkpoint=lambda checkpoint: self.append(...)` (:423). No reentrancy guard exists, so a checkpoint append that rotates re-enters compaction while the outer compact_segment has not yet replaced its source file.

## The finding

Prevent checkpoint appends from recursively compacting their source

If appending a compaction checkpoint triggers rotation, `append()` synchronously starts another sweep before the outer `compact_segment()` reaches its source-file replacement. The nested sweep therefore finds the same original eligible rows and compacts them again. A sufficiently large checkpoint—possible with many alternating coverage runs—can trigger rotation on every iteration, producing duplicate archives/checkpoints until `RecursionError` aborts the original append. This is reproducible with a reduced rotation threshold. Suppress or defer rotation-triggered compaction while a compaction transaction is already in progress.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `harness/ledger.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/618#discussion_r4617725782
