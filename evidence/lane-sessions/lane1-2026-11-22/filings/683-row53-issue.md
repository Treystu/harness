# Preserve immutable segment contents when pinning a window

Part of #683, finding 53 (P2). Verified against `main`
`8fc28a0e` on 2026-11-25: still present.

## Current evidence

harness/decision_trace.py:243-246 builds the manifest by hashing each segment file where it sits and recording only basename, sha256 and size. The active file is mutable, so one append after `pin_window` makes the recorded hash disagree, and rotation then moves those bytes away from the recorded basename.

## The finding

Preserve immutable segment contents when pinning a window

When a window includes the active ledger, the manifest hashes a mutable file without retaining its contents. A single ordinary append after `pin_window` returns makes the recorded SHA-256 disagree with that file; rotation subsequently moves those bytes away from the recorded basename. Thus the purportedly pinned evidence set cannot later be recovered and verified from the manifest even during normal operation. Retain an immutable snapshot or sealed segment and record its stable location and hash, rather than merely describing the current active file.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `harness/decision_trace.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/627#discussion_r4627324870
