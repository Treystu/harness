# Refresh citation pins under synchronization before compaction

Part of #683, finding 38 (P2). Verified against `main`
`8fc28a0e` on 2026-11-25: still present.

## Current evidence

harness/ledger.py:77 fills citation_pins only at load and :444 adds only the pin this instance wrote; :433 passes that instance-local set into compact_segment, so a citation committed by another open ledger instance is invisible and its row stays eligible for deletion.

## The finding

Refresh citation pins under synchronization before compaction

When two ledger instances are open, a citation appended by one does not update the other's `citation_pins`, which is populated only during initialization and that instance's own `pin_citation()` calls. A later sweep by the older instance therefore deletes the cited row despite its committed citation; a fresh loader retains the citation but cannot resolve its target. Refresh pins from committed citation records and synchronize eligibility evaluation through the segment switch with citation writes, rather than passing this stale instance-local set.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `harness/ledger.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/618#discussion_r4617725796
