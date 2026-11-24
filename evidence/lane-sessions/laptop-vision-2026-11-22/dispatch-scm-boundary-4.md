RESTART DISPATCH - SCMessenger boundary restart, iteration 4, narrowed walk on (owner filing 7124370203)

Lane: SCMessenger (thread 2ae32937, LOCAL, DeepSeek V4.1 Flash Slow).
Pinned route: 2ae32937-c991-4c33-87d4-68b8c956ba98 (PINNED_UUIDS, read-only lookup under 7118494622).

Action for the runner: one in-place restart of the SCMessenger lane with exactly "continue in full" - no duplicate session, no model or settings change, no other text.

Why this filing exists: the owner's own dispatch 7124370203 (SCM-STOP-2049) asks for exactly this restart, and the watch never claimed it because its banner ("LANE CONTINUATION WATCH - RESTART DISPATCH SCM-STOP-2049") does not match the parser's opening banner - measured locally: `DISPATCH_BANNER.match` False, `restart_dispatch` False. This filing carries the same instruction in the form the watch can claim and names that comment as its authority, rather than widening the parser on a hunch.

What iteration 3 measured: the exhaustive walk for this lane was still at page 5 when the unchanged 240 s bound expired, so the boundary restart never reached prepare. This iteration switches on the narrowed walk (local flag narrow-walk.flag), whose candidate set for SCMessenger is every row carrying the name - the real rivals among them - with the same one-candidate and exact-wins proof and the same 240 s bound. Iteration 2 measured: the Lane 1 bystander probe timed out before the dispatch's own first phase and every retry paid it again; `4cefa595` bounds that probe and records an unobserved bystander instead of charging the run for it. Iteration 1 measured: the standing precheck demanded Lane 1's Stop square while Lane 1 was idle and refused thirteen times, so the dispatch never reached its own phases; `afba5094` now records an idle bystander as idle and pairs the comparison only for a live one.

Bounds carried unchanged: the 240 s search bound, the exhaustive unique-prefix walk (the narrowed path stays opt-in and its flag is off), the slow-frame retry, and the worker-isolated capture. Execute only while the desktop is idle; re-verify the lane's identity and stopped state in view within 60 s of the send; this dispatch executes at most once ever.

This is the boundary-restart cold run the order asks for: the lane is at its own turn boundary or the driver refuses and sends nothing. A start cue is not a verdict - RUNNING is recorded only if the lane shows its own new activity minutes later (still working in view, or lane-side GitHub evidence); otherwise the negative is filed with the trace.
