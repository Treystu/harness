RESTART DISPATCH - Lane 1, iteration 7 (reveal cure at d4afbd94)

Distinct filing, not a repeat: claim 7124457637 was the first run to clear
search, query and select end to end, and it parked at prepare with "no route and
no highlighted sidebar row identified the pinned session". The walk had left the
sidebar scrolled away from the row, so the selection probe read a screen without
it. `d4afbd94` cures that: `reveal_lane_row` scrolls the row back into view in a
bounded four pages and records `reveal-lane-visible`; identity still requires the
highlight or the route, and send never scrolls.

Lane: Lane 1 (thread 315608d2, LOCAL Harness, DeepSeek V4.1 Flash Slow).
Pinned route, recorded read-only under 7118494622:
315608d2-1531-456b-918a-f7e97db56496.

Action for the runner: one in-place restart of Lane 1 with exactly "continue in
full" - no duplicate session, no model or settings change, no other text.

Bounds carried unchanged: the 240 s search bound (`d0f59aec`), the slow-frame
retry (`4fcb03f8`), the worker-isolated capture (`7d44f056`), and the exhaustive
unique-prefix walk (default, un-narrowed: the narrowed path stays opt-in and is
not used by this dispatch). Execute only while the desktop is idle - if the
owner is at the keyboard, hold and say so - and re-verify Lane 1's identity and
stopped state in view within 60 s of the send. This dispatch executes at most
once ever.

Verdict standard: a start cue is not a verdict. Record RUNNING only if the lane
shows its own new turn activity minutes later (still working in view, or
lane-side GitHub evidence); otherwise file the negative with the trace.
