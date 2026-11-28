## Lane 1 check-in: claim-loop cure landed, backlog census, and the lane's current state

Driver branch `laptop-vision-20261122` at `852c9854`. Watch paused
(`control.json`, `updated_by: antigravity-oversight-7149396491`, 01:28:25Z).
No merge, no promotion, no model change.

### DONE

| Item | SHA | Evidence |
|---|---|---|
| Dispatch parser accepts the wording the oversight actually files; heartbeat names unparseable owner dispatches | `3cca6116` | tests `test_parse_dynamic_dispatch_*`, 63 passing with `test_civicscope_identity.py` |
| Only the newest restart per lane is claimable; older episodes closed by construction | `821d9d32` | `test_a_superseded_restart_is_never_claimed_after_a_newer_one` |
| Owner `CANCELLATION` naming a dispatch or episode closes it; lane-only cancellation does not | `8f29f91f` | `test_a_cancelled_episode_is_closed_and_never_claimed`, negative test |
| `control.json` `cancelled_lanes` is enforced at claim time, not inert | `852c9854` | `test_a_lane_cancelled_at_the_control_surface_is_never_claimed` |
| SCM dispatch `7146588401` claimed, acked, executed, verdict filed | - | #684 comment `7149558080`, `dyn-7146588401-2ae32937/runner.jsonl` |
| Diagnosis and census posted on #684 | - | #684 comment `7149652916` |

The SCM verdict is `parked: prepare: BLOCKED: the exact pinned session route is
required for this standing dispatch`. That is the designated live proof
completing the claim path (claim -> ack -> prepare -> named refusal -> result),
not a second attempt at the same lane.

### Lane 1 desktop state

`315608d2` is **running this turn now**, on the input `continue in full`
delivered at 01:12Z by the stale dispatch `7129310215`. No turn was killed and
no second restart was sent: the 01:16 tick's prepare found the lane already
turning and its verdict was `verified running: the session was already in a
turn; no input sent` (#684 comment `7149427565`). The control surface now also
carries `cancelled_lanes: ["315608d2"]`, which the watch refuses to claim
against until the entry is removed.

### Backlog census (#684 dispatches with no claim file, at `852c9854`)

| Dispatch | Filed | Lane | Class |
|---|---|---|---|
| 7131314944 | 12:21Z | 315608d2 | SUPERSEDED (L1-STOP-980) |
| 7135450398 | 15:05Z | 315608d2 | SUPERSEDED (L1-STOP-991) |
| 7138681649 | 17:05Z | 315608d2 | SUPERSEDED (L1-STOP-999) |
| 7140150416 | 18:05Z | 315608d2 | SUPERSEDED (L1-STOP-1003) |
| 7145072019 | 21:32Z | 315608d2 | SUPERSEDED, claimed, no input sent |
| 7146588401 | 22:44Z | 2ae32937 | LIVE, claimed, executed, parked |

Nothing else in the window is claimable: `7117989632` is past the 24-hour TTL,
`7121037795` is a non-restart audit dispatch, and every other restart carries a
claim file. Net: **zero** dispatches left unclaimed and open.

### WIP

Nothing in flight. The watch is paused and the lane's only live work is PR #720.

### NEXT

1. PR #720: the `audit` D12 red at head `6ef8a317`
   (`ci/circleci: audit:failure`); local full suite already green except the two
   known local-only failures.
2. Then the next unworked queue item.

### BLOCKERS

- SCM `7146588401` needs its pinned session route from the platform side; the
  driver cannot manufacture it. Re-dispatch with the route, or accept the park.
- Watch pause and `cancelled_lanes` are Antigravity's / the owner's to clear.

### WAIT-STATE

`idle: none`. The driver is not blocked on me; it is paused by design.

Refs #684, #295.
