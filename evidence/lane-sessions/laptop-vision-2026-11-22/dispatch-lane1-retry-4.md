RESTART DISPATCH - Lane 1 retry after the narrowed-walk cure (fresh claim)

Filed by the standup lane under the owner's instruction for this pass ("get a
fresh/valid dispatch claimed and executed by the watch through to the end of its
phases"). Same authority and verdict standard as 7122154514; claims 7119751841,
7122154514, 7122241209 and 7122320861 are spent and none reached a send:

- 7119751841 parked at the 65 s default deadline (cured `d0f59aec`).
- 7122154514 and 7122241209 parked on a native capture fault, 0xc0000005 in
  GraphicsCapture.dll (cured `7d44f056`).
- 7122320861 ran clean under the 240 s bound but spent it inside
  `navigate_by_unique_prefix` on eight pages (cured `5308f5bb`, which narrows
  the list with the app's own Search chats field and keeps the unique-prefix
  proof on the filtered roster at the same 240 s).

Lane: Lane 1 (thread 315608d2, LOCAL Harness, DeepSeek V4.1 Flash Slow).

Action requested: execute ONE in-place restart of Lane 1 - send its staged
"continue in full" - no duplicate session, no model/settings change, no other
text. Preconditions and bounds, carried unchanged:

- Run under the 240 s search bound (`d0f59aec`), the slow-frame retry
  (`4fcb03f8`), the worker-isolated capture (`7d44f056`) and the narrowed walk
  (`5308f5bb`) at branch `laptop-vision-20261122`.
- Execute ONLY while the desktop is idle; while the owner is at the keyboard,
  hold and say so in a heartbeat (sovereignty bound).
- Freshness: re-verify Lane 1's identity and stopped state inside the view
  within 60 s of the send; if it is already working, spend nothing and file it.
- Idempotency: this dispatch executes at most once ever (ledger).
- Verdict under the sustained-turn standard: 25 s post-start observation PLUS a
  second corroboration minutes later (still working in view, or lane-side GitHub
  evidence - a check-in on #295, a head move). A seconds-long Working frame is a
  START, not a verdict. If the second look says otherwise, file the negative.
