RESTART DISPATCH - SCMessenger boundary restart (owner filing 7124370203, SCM-STOP-2049)

Lane: SCMessenger (thread 2ae32937, LOCAL, DeepSeek V4.1 Flash Slow).
Pinned route: 2ae32937-c991-4c33-87d4-68b8c956ba98 (PINNED_UUIDS, read-only lookup under 7118494622).

Action for the runner: one in-place restart of the SCMessenger lane with exactly "continue in full" - no duplicate session, no model or settings change, no other text.

Why this filing exists: the owner's own dispatch 7124370203 (SCM-STOP-2049) asks for exactly this restart, and the watch never claimed it because its banner ("LANE CONTINUATION WATCH - RESTART DISPATCH SCM-STOP-2049") does not match the parser's opening banner - measured locally: `DISPATCH_BANNER.match` False, `restart_dispatch` False. This filing carries the same instruction in the form the watch can claim and names that comment as its authority, rather than widening the parser on a hunch.

Bounds carried unchanged: the 240 s search bound, the exhaustive unique-prefix walk (the narrowed path stays opt-in and its flag is off), the slow-frame retry, and the worker-isolated capture. Execute only while the desktop is idle; re-verify the lane's identity and stopped state in view within 60 s of the send; this dispatch executes at most once ever.

This is the boundary-restart cold run the order asks for: the lane is at its own turn boundary or the driver refuses and sends nothing. A start cue is not a verdict - RUNNING is recorded only if the lane shows its own new activity minutes later (still working in view, or lane-side GitHub evidence); otherwise the negative is filed with the trace.
