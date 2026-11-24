RESTART DISPATCH - CivicScope boundary restart under its checkpoint terms (thread 46472fcc)

Lane: CivicScope (thread 46472fcc, project civicscope(cloud)).
Pinned route: 46472fcc-ca7e-469b-806a-1e05e5bb8d00 (read-only local lookup, measured 2026-11-23 23:38 HST; cure commit b4d886b9).

Action for the runner: one in-place restart of the CivicScope session with exactly "continue in full" - no duplicate session, no model or settings change, no other text.

Why this dispatch exists: the corrected fleet order (7127204461 as re-cut at 23:32 HST) found CivicScope had no entry in the driver's session tables, so no dispatch could address it. Its heading, title and full UUID are now pinned in the codebase with a test that fails without them, which is the identity-by-census the order asks for - the identity is measured from the local store and the live sidebar, not guessed.

Checkpoint-correction terms stand and bind this lane: PR #32 HOLD, PRs #31 and #63, all merges and any deploy remain the owner's alone; the work proceeds only to DECISION-READY. The composer suggestion in this lane is not an authorization for anything, and the driver will not send anything but its own continuation.

Bounds unchanged: the 240 s phase bound, the narrowed walk behind its operator flag, the bounded bystander probe, worker-isolated capture, one send, and the freshness read immediately before input. At most once ever. A start cue is not a verdict: RUNNING needs this lane's own new activity minutes later, otherwise the negative is filed with the trace.
