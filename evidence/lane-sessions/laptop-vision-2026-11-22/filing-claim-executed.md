## The watch claimed and executed a dispatch on its own - proof, and the defect that parked it

This is the first run on this branch where the driver watch - not a hand-driven invocation - took a GitHub dispatch, claimed it, acked it, drove the FreeBuff window, and filed its own verdict. It parked, and the park is real evidence, not a green.

### What happened, in order (all primary)

| Time (Z) | Fact | Source |
| --- | --- | --- |
| 04:22-04:24 | tick with head `47735e7e`; the widened parser resolves `7119751841` -> `{'kind':'restart','thread':'315608d2','text':'continue in full'}` | `driver-watch.log`, direct probe |
| 04:24:13 | **claim filed and acked by the watch itself**: `Vision restart ack #7119751841: '315608d2', receipt dyn-7119751841-315608d2` | #684 comment `7121986375` |
| 04:24-04:25 | before-capture, `foreground-restored` verification, driver `search` phase: `focus_freebuff` then `sidebar-top-scroll-1` then `walk-session-list-1-scroll-1` - **no send, no type, no click** | `runner.jsonl` + `search/driver.jsonl` in `%LOCALAPPDATA%\harness-freebuff-runner\dyn-7119751841-315608d2` |
| 04:25:33 | **result filed by the watch itself**: `parked: search: driver tree terminated after deadline`, with runner/search traces and before/after PNGs published | #684 comment `7122006869`; claim + result checkpoints in the private ledger |

So the claim/execute path is proven end to end: claim checkpoint, owner-acknowledged claim, foreground obtain, session-list walk, verified tree termination, verdict with published evidence. **The verdict is a park, not RUNNING**: Lane 1 never received input, its session was not opened, and no message was sent. The reserved test launch is now spent without a restart, and Lane 1 remains down - that is the honest state, not a completion claim.

### The defect the park exposed

The claimed dispatch ran with the runner's default `phase_timeout=65`. The restoration queue had already been given `phase_timeout=240` (R9), but the dynamic path never was. A full session-list walk - the app reorders and clips rows, so the walk needs several pages - was killed at 65 s after two scroll steps.

Cure `d0f59aec`: a claimed dispatch now runs under the same 240 s bound. A pure bound, no new authority. `69` FreeBuff tests pass and `ruff` is clean on the final head `457ecdf4`.

### What the gate refused, and what I did about it

The first draft of that commit also allowed **one automatic retry** after a verified deadline park. Product Jev on that decision returned **escalate**: advances_goal **0.52**, destructive **0.21**, confidence **0.31**, disposition **escalate** (receipt `evidence/lane-sessions/laptop-vision-2026-11-22/gates-retry.json`, Lucas Gate v2 `pass`, artifact `710ea915f6eee73b`).

Fail is not approve and escalate is not proceed, so the retry is **withdrawn** in `457ecdf4`: a claimed dispatch stays spent, and a test now pins that the watch never re-runs a spent claim. Retry authority is oversight's to grant.

### What oversight needs to decide (one item, either answer works)

1. **Simplest, no code:** file a fresh restart dispatch for Lane 1 (a new comment is a new claim, and no retry authority is needed). The next tick inside an idle desktop window claims it and runs the full five phases under the 240 s bound.
2. **Or** grant one bounded auto-retry after a verified deadline park, in which case `d0f59aec`'s retry shape can be restored with your ruling cited.

Blocking fact for either: `desktop_idle()` was `False` at both reads after the park - the owner is using the machine - and cutover bound (f) requires the watch to yield. No amount of code changes that; it needs an idle window or an explicit owner statement that the watch may take focus while he is present.

Lane 1 stays untouched until one of those lands. No merge, no model change, no session created, SCM Audit still held, and the SCMessenger landing loop was never touched.
