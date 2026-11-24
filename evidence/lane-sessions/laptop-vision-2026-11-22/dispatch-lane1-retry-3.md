RESTART DISPATCH - Lane 1 retry after the capture-worker cure (fresh claim)

Filed by the standup lane itself, under the owner's instruction for this pass
("if a fresh dispatch comment is required for a new claim, file one and let the
watch claim it"). It carries the same authority and verdict standard as
7122154514 and the 7122241209 retry, both spent:

- 7122154514 executed and parked at `sidebar-top-3-after: capture exceeded 2s`.
- 7122241209 executed and parked at `search: driver exited unsuccessfully`,
  which the Windows Application log explains: pythonw.exe, 0xc0000005 in
  GraphicsCapture.dll (04:43:05Z). Frames are now taken in a worker process
  (`7d44f056`), and a dead worker is re-taken once.

Lane: Lane 1 (thread 315608d2, LOCAL Harness, DeepSeek V4.1 Flash Slow).

Action requested: execute ONE in-place restart of Lane 1 - send its staged
"continue in full" - no duplicate session, no model/settings change, no other
text. Preconditions and bounds, carried unchanged:

- Run under the 240 s search bound (`d0f59aec`), the slow-frame retry
  (`4fcb03f8`) and the worker-isolated capture (`7d44f056`) at branch
  `laptop-vision-20261122`.
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
