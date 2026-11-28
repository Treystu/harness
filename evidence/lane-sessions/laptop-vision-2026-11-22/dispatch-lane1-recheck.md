RESTART DISPATCH - Lane 1, iteration 9, boundary restart if its composer is clear (thread 315608d2)

Lane: Lane 1 (thread 315608d2, LOCAL). Pinned route: 315608d2-1531-456b-918a-f7e97db56496 (PINNED_UUIDS, read-only lookup 7118494622).

Action for the runner: one in-place restart of the Lane 1 session with exactly "continue in full" - no duplicate session, no model or settings change, no other text.

Why this is filed now. The owner's order for this pass is explicit: re-check Lane 1's composer cheaply, and if the foreign draft is gone, land the one clean in-place restart by sending exactly "continue in full"; if it is still there, record it pending and do not type over it. Binding note 7125916631 item 2 also sequences Lane 1 next. The driver's prepare is the correct reader for that question: it reads the composer's own text before typing, refuses any draft that is not this continuation by name, and refuses a lane that is already running. So this dispatch is both the re-check and, only when the composer is clear, the restart.

This pass's manual read was inconclusive and is filed as such, not as a result. The Lane 1 row was scrolled out of the sidebar; after a visibility-only reveal the row click landed on a view showing the new-chat greeting, which is not the Lane 1 session, so nothing about its composer follows from it. No input was typed in that view, no session was created, and Lane 1 received nothing. A separate probe of that view reported a Stop cue on a greeting screen, so the stop detector's reading there is not trusted either.

The foreign draft the previous pass recorded (an owner module note with a coverage requirement) stays untouched unless this run reads a clear composer. If it is still there, prepare refuses and sends nothing, and that negative is the answer.

Bounds carried unchanged: the 240 s phase bound, the unique-prefix walk with the narrowed path as the operator flag, the bounded bystander probe, worker-isolated capture, one send, and the freshness check immediately before input. Execute only while the desktop is idle. This dispatch executes at most once ever. A start cue is not a verdict: RUNNING needs the lane's own new activity minutes later, otherwise the negative is filed with the trace.
