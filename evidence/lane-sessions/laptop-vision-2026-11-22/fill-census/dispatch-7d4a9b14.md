RESTART DISPATCH - fill stage 4: Kalshi Paper Burndown boundary restart (thread 7d4a9b14)

Lane: Kalshi Paper Burndown (thread 7d4a9b14, LOCAL, project Kalshi-Trader).
Pinned route: 7d4a9b14 (identity read by the driver's own gates this run).

Action for the runner: one in-place restart of this lane with exactly "continue in full" - no duplicate session, no model or settings change, no other text.

Authority: comprehensive fill dispatch 7116554238, stage order as filed (stage 1 SCMessenger, stage 4 boundary restarts). This is the stage 4 entry for Kalshi Paper Burndown.

Boundary rule, and why this is safe even if the lane is busy: the runner proves the lane's identity and then refuses to type when the session is already in a turn - "the requested session is already running; no restart input". A lane that is mid-turn therefore receives nothing, which is the hands-off rule enforced in the driver rather than by a guess here.

Bounds carried unchanged: the 240 s phase bound, the unique-prefix walk with the narrowed path as the operator flag, the bounded bystander probe, worker-isolated capture, one send, and the freshness read immediately before input. Execute only while the desktop is idle. At most once ever. A start cue is not a verdict: RUNNING needs this lane's own new activity minutes later, otherwise the negative is filed with the trace.
