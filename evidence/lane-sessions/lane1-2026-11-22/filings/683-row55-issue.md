# Include retained segments when reading a ledger path

Part of #683, finding 55 (P2). Verified against `main`
`8fc28a0e` on 2026-11-25: still present.

## Current evidence

harness/decision_trace.py:198-199 treats a string source as exactly one path and never calls `_segment_paths`, so a path-based read silently excludes retained segments after rotation, despite the reader's documented active-plus-archive behaviour.

## The finding

Include retained segments when reading a ledger path

When a ledger has rotated, the new string-path branch reads only the active file, silently excluding assessments in retained segments despite this reader's documented active-plus-archive behavior. `AutonomyLedger.append()` rotates after persisting the assessment, so an assessment that crosses the 10 MB threshold can already be absent from a path-based read immediately after a successful write. Reproduced with a lowered rotation threshold: `read_trace_events(ledger)` returns the assessment while `read_trace_events(ledger.path)` returns an empty list. Resolve the path through the ledger's existing segment enumeration rather than treating it as a single segment.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `harness/decision_trace.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/628#discussion_r4637150541
