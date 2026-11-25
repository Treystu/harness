## Claim-scan diagnosis, cure, and cold-run evidence (#684)

Head at posting: driver branch `laptop-vision-20261122` at `852c9854`
(`3cca6116` wording cure, `821d9d32` supersession, `8f29f91f` episode close,
`852c9854` control-surface cancellation). No merge, no promotion, no
model/settings change.

### 1. What was actually broken, and where

The live loop is `~/.harness/driver-watch/run-watch.py` (2-minute scheduled
tick, single-instance lock, `status.json` telemetry). It imports
`scripts.windows_freebuff_watch` from
`C:\Users\SCM\Documents\GitHub\Harness-laptop-vision-20261122` at the branch head
and calls its `main()`. The claim scan is `poll_dynamic_dispatches`.

Two candidate causes were ruled out from the code and local state:

- **No cursor or watermark exists.** `checkpoints()` re-reads the ledger
  directory `dispatch/laptop-driver/watch/7093801996` on every tick; the claim
  set is the current remote listing, not persisted local state. There was
  nothing to get stuck at.
- **Not the pagination window.** The scan pages `?since=2026-11-24T00:20:00Z`
  until a short page; that window holds 294 comments (3 pages), including both
  pending dispatches.

What was left is the parser, and it fails deterministically. Run with the
module's own predicates against the two live comments:

| Dispatch | owner | banner | restart | RUNNER_ACTION | quoted text | lane inferred | `parse_dynamic_dispatch` |
|---|---|---|---|---|---|---|---|
| 7145072019 (Lane 1, L1-STOP-1014) | true | true | true | **false** | true | **None** | `None` |
| 7146588401 (SCMessenger, SCM-STOP-1242) | true | true | true | true | true | **None** | `None` |

- 7145072019 writes its instruction as `Runner action requested:`; the accepted
  forms were `Action for the runner:` and `Action requested`.
- Neither dispatch writes a `Lane:` line: the lane is named only in the banner
  (`RESTART DISPATCH - Lane 1, ...`, `RESTART DISPATCH - SCMessenger, ...`), and
  lane inference read only a `Lane:` line.

So the watch scanned the same two comments every two minutes, parsed neither,
and its heartbeat reported "no unclaimed dispatches" - indistinguishable from
an empty queue. The break was wording drift in the oversight's dispatch format,
not a crashed claim loop: the tick ran every ~2 minutes with `rc=0` throughout
(`~/.harness/logs/driver-watch.log`).

### 2. The cure

Three commits on the driver branch, each with tests, ruff clean:

1. **`3cca6116` - claim what is actually filed.** Accept a third instruction
   form (`Runner action requested:`, later extended to the bare `ACTION
   (runner only)` and `Action:` forms four more owner restarts use); read the
   lane from the banner line when there is no `Lane:` line, while a lane named
   only in body prose grants nothing. The heartbeat now names an unparseable
   owner dispatch instead of claiming the queue is empty.
2. **`821d9d32` - episode supersession.** Only the newest parsed restart per
   lane is claimable; an older restart for the same lane is closed by
   construction.
3. **`8f29f91f` - the episode's own bound.** An owner `CANCELLATION` that names
   this dispatch id or its episode closes it. A cancellation naming only the
   lane does not close a later episode (7144433519 cancelled L1-STOP-1010, not
   every Lane 1 episode).

4. **`852c9854` - the operator's cancellation is code, not a comment.**
   `control.json` gained `cancelled_lanes: ["315608d2"]` at 01:28:25Z; until
   now no code read that key, so the route cancellation in the control surface
   was inert while restarts for the lane stayed claimable. `main()` now reads
   the list once per tick and the claim scan refuses a restart whose lane is in
   it, until the entry is removed.

Unchanged: execute-once through the claim checkpoint, the re-read before acting
(`guard_approval` re-reads PAUSE and the published head), owner-only parsing,
the 24-hour dispatch TTL, the `filed_on_issue` ack check, the desktop-idle and
driver-runtime interlocks. 63 tests pass in `tests/test_freebuff_watch.py` and
`tests/test_civicscope_identity.py`; `ruff check` clean.

### 3. Why the episode check did not bite, and what it does now

There was no episode-state check in the claim path at all. The dispatches state
their own bound ("execute only while episode X is still OPEN"), but the scan
relied on the claim file and the 24-hour TTL. That is why the first cured tick
executed a closed episode - and the harm is real, not theoretical:

- **01:06:54Z** the watch acked `7129310215` (episode **L1-STOP-974**, filed
  10:50Z, superseded hours earlier); the pre-guard scan took the oldest
  unclaimed id.
- **01:12Z** its send fired: `continue in full` went into Lane 1 (`315608d2`).
  Lane 1 restarted. Verdict filed 01:14:03Z: `verified running`.
- **01:16:53Z** the next tick acked `7145072019` (L1-STOP-1014).
- **01:19:19Z** that run finished `verified running: the session was already in
  a turn; no input sent` - the supersession guard (`821d9d32`) had landed
  between the two ticks, and the prepare phase found the lane already turning.

With `821d9d32` and `8f29f91f` in place the same scan refuses both by
construction: `7129310215` is not the newest Lane 1 restart, and a cancelled
episode is closed. Tests pin both refusals
(`test_a_superseded_restart_is_never_claimed_after_a_newer_one`,
`test_a_cancelled_episode_is_closed_and_never_claimed`,
`test_a_cancellation_of_another_episode_does_not_close_this_one`).

### 4. Control action taken, in the order the oversight asked

1. **Paused the execution path first.** `~/.harness/driver-watch/control.json`
   set to `paused: true` at **01:19:06Z**, recorded before any further triage.
   The in-flight tick was allowed to finish rather than killed mid-automation;
   it sent nothing (verdict above) and exited `rc=0` at 01:19:19Z.
2. **Verified Lane 1's desktop state read-only.** Lane 1 (`315608d2`) is
   **running a turn now**, on the input `continue in full` delivered by the
   01:12Z send, started 01:12Z. Evidence: the window capture taken by the
   driver's own prepare phase shows this session's current turn text and its
   running command block; the 01:06 run's `send/` holds
   `platform-response-1..4.png` and a stop cue at 01:13:49Z. No turn was killed,
   and Lane 1 was not restarted again.
3. **Unpaused at 01:21:49Z for the designated live proof only** (SCM
   `7146588401`), per the dispatch's item 3; the census below shows no other
   claimable item exists. The SCM claim and ack went out at 01:22:56Z; its
   verdict is section 6.
4. **The watch was paused again at 01:28:25Z by `antigravity-oversight-7149396491`,**
   which also wrote `cancelled_lanes: ["315608d2"]`. That is the current state
   (`paused: true`), and item 4 of the cure above makes the lane entry real. I
   did not clear either; the pause and the lane cancellation are the owner's and
   Antigravity's calls, not this lane's.
5. **Revival was this lane's act, not spontaneous.** The log switches head from
   `18e8160b` to `3cca6116` at the 00:58:52Z tick - the tick after the cure was
   pushed - and my 01:19:06Z pause was the only control change I made besides
   the 01:21:49Z unpause for SCM.

### 5. Backlog census (every #684 dispatch with no claim file)

Produced with the watch's own parser over all owner comments since 00:20Z,
joined against the ledger's claim files:

| Dispatch | Filed | Lane | Class | Claim |
|---|---|---|---|---|
| 7131314944 | 12:21Z | 315608d2 | SUPERSEDED (L1-STOP-980) | none |
| 7135450398 | 15:05Z | 315608d2 | SUPERSEDED (L1-STOP-991) | none |
| 7138681649 | 17:05Z | 315608d2 | SUPERSEDED (L1-STOP-999) | none |
| 7140150416 | 18:05Z | 315608d2 | SUPERSEDED (L1-STOP-1003) | none |
| 7145072019 | 21:32Z | 315608d2 | SUPERSEDED - claimed, no input sent | `claim-dyn-7145072019-315608d2` |
| 7146588401 | 22:44Z | 2ae32937 | LIVE - claimed, executed, parked | `claim-dyn-7146588401-2ae32937` |

Re-censused at `852c9854` after the parser cure: the four Lane 1 restarts now
classify as SUPERSEDED rather than unparseable, and the count of dispatches with
no claim file and no closed episode is **zero**. The only dispatch that could
have executed was SCM, and it did - once.

The four earlier Lane 1 restarts were unparseable for the `ACTION (runner
only)` / `Action:` wording; they are now parseable and refused as superseded by
`7145072019`. `7117989632` (00:21Z) parses but is outside the 24-hour TTL.
Every other restart in the window carries a claim file; `7121037795` is a
non-restart audit dispatch and is correctly not claimable.

### 6. SCM execution verdict (designated live proof)

Dispatch `7146588401`, lane 2ae32937, claimed 01:22:56Z (`claim-dyn-7146588401-2ae32937`),
acknowledged in the same tick, executed, verdict filed 01:26:59Z as
comment `7149558080`:

> parked: prepare: BLOCKED: the exact pinned session route is required for this
> standing dispatch

The claim path is proven end to end against a live dispatch: claim file written
-> ack posted -> runner started -> prepare consulted the lane's pinned route ->
refused with a named block -> result checkpoint and verdict posted, exit `rc=0`
at head `8f29f91f` (the tick that started it found head `8f29f91f`; `852c9854`
landed while the watch was paused). No input was typed into any session. This is
the honest bound of this driver: it can claim and dispatch, but it cannot invent
an adversarial route the platform requires, so SCM is parked rather than faked.
Receipts: `dyn-7146588401-2ae32937/runner.jsonl` (seq 1..7, `stop_cue: true`,
final state = the park string), `prepare.jsonl`, and the two evidence digests
linked in the result comment.

What remains is a platform-side unblock: the dispatch needs the exact pinned
session route supplied to the runner (the same route shape the m365 proof
used), or the oversight reissues it with that route. Until then SCM sits parked
with a claim and a result, which is the at-most-once outcome, not a second
attempt lane.

Refs #684. Issue #684 stays open until oversight accepts against 7094050344;
this filing claims no completion.
