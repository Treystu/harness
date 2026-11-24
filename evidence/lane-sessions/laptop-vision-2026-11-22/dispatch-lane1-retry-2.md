RESTART DISPATCH - Lane 1 retry under the cured capture bound (fresh claim)

Filed by the standup lane itself, under the owner's instruction for this pass
("if a fresh dispatch comment is required for a new claim, file one and let the
watch claim it"). It reuses the authority and verdict standard oversight set in
7122154514, which is spent: that claim executed end to end and parked at
`search: driver exited unsuccessfully` (escalation
`sidebar-top-3-after: capture exceeded 2s`, 04:38:53Z), cured in `4fcb03f8`.
No new authority is taken and nothing is widened: same one lane, same one
action, same at-most-once claim.

Lane: Lane 1 (thread 315608d2, LOCAL Harness, DeepSeek V4.1 Flash Slow).

Action requested: execute ONE in-place restart of Lane 1 - send its staged
"continue in full" - no duplicate session, no model/settings change, no other
text. Preconditions and bounds, carried from 7122154514:

- Run under the 240 s search bound (`d0f59aec`) and the one-retry capture bound
  (`4fcb03f8`) at branch `laptop-vision-20261122`.
- Execute ONLY while the desktop is idle; while the owner is at the keyboard,
  hold and say so in a heartbeat (sovereignty bound).
- Freshness: re-verify Lane 1's identity and stopped state inside the view
  within 60 s of the send; if it is already working, spend nothing and file it.
- Idempotency: this dispatch executes at most once ever (ledger).
- Verdict under the sustained-turn standard: 25 s post-start observation PLUS a
  second corroboration minutes later (still working in view, or lane-side GitHub
  evidence - a check-in on #295, a head move). A seconds-long Working frame is a
  START, not a verdict. File the verdict on #684 either way; a park files its
  evidence and names the next defect.
