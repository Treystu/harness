# Exclude live requests before classifying checkpoints as recovered

Part of #683, finding 31 (P2). Verified against `main` `8fc28a0e` on
2026-11-25: still present.

## Current evidence

harness/server.py:1431 `recovered_requests()` calls `discover_requests(self.history_dir)` with no live-owner set; `discover_requests` (harness/run_recovery.py:141) classifies every checkpoint in the directory, and the status surface at :2130 merges live and recovered without excluding live request ids.

## The finding

**

When a chat request is running in this server, its lifecycle checkpoint is already present in the same history directory. This call discovers that checkpoint without checking live ownership, and the listing consequently includes both the live run and an `interrupted` recovery record claiming that its process is gone. I reproduced this with a live `UiState` run writing a checkpoint: the run remained `running` while recovery reported `no live owner`. Track the lifecycle request/session associated with live runs and exclude those checkpoints from recovery on both listing and status surfaces; otherwise normal in-flight work is incorrectly advertised as interrupted and safe to resume.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `harness/server.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/614#discussion_r4617290244
