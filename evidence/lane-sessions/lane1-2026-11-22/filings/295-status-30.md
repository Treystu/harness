## Gate receipt (filed before posting)

- Lucas Gate v2 (typed track): see the JSON block prepended to the posted copy.
- Product Jev (`jev-1.14.0`): see the same block. No issue is closed, no gate
  is loosened, and no completion credit is taken.

---

# LANE 1 UPDATE - watch execution state, six-row claim order, and the pickup root cause

Read at `2026-11-25T13:00Z`. Answers oversight ask `7157795486` item 1,
amendment `7157843844`, and supplement `7157864331`.

## DONE

1. **What the watch is executing right now.** Nothing, between ticks: the
   scheduled watch is `idle_watching`, `paused: false`, PID `24552`, worktree
   `Harness-laptop-vision-20261122`, last completed tick `12:56:28Z` with
   `exit_code: 0`. Its cadence is **2 minutes**: the log records a tick every
   2 minutes from `11:24Z` through `12:56Z` with no gap, and the ticks that
   log `another watch tick already holds watch.lock` are the scheduler
   colliding with a tick that is still executing a dispatch. The watch head
   moved `df4049be` -> `798148ce` (11:52Z) -> `e6e9b319` (12:32Z) -> `7a7d7ca1`
   (this filing).

2. **The claim order for the six burn dispatches.** The six `08:51Z` rows were
   never claimed, and the reason is now measured rather than inferred. Each one
   matches the dispatch banner, each one resolves to its lane
   (`0d7e2f37`, `918dad1a`, `2ae32937`, `26646448`, `46472fcc`, `7d4a9b14`),
   and each one fails exactly one grammar rule: they write the instruction as
   `Action: re-read session state ...` **mid-paragraph**, while the parser
   requires an Action line at line start. The parser returned `None` for all
   six, so every scan reported them in the heartbeat's `not claimable` list -
   the `12:18:33Z` heartbeat `7162199250` names all six - and `not claimable`
   was read as "handled" rather than "unreadable".

   Their `09:29:53Z` successors were claimed and executed in this order, with
   the verdict each produced:

   | # | dispatch | lane | claimed | verdict |
   |---|----------|------|---------|---------|
   | 1 | `7158410873` | `918dad1a` Harness Audit | `09:31:10Z` | parked at prepare: composer held a foreign draft, not typed over |
   | 2 | `7158410892` | `7d4a9b14` Kalshi | `09:35:01Z` | parked: driver tree terminated after deadline |
   | 3 | `7158410977` | `46472fcc` CivicScope | `09:40:59Z` | parked: driver tree terminated after deadline |
   | 4 | `7158410992` | `2ae32937` SCMessenger | `09:46:58Z` | **verified running** `09:53:22Z`, no input sent |
   | 5 | `7158410813` | `0d7e2f37` BigEnergyCo | `11:59:25Z` | parked: project session list does not hold the lane and no candidate exposes its route |
   | 6 | `7158410915` | `26646448` Agensi | `12:07:23Z` | same blocker |
   | - | `7159142905` | `315608d2` Lane 1 | `12:15:24Z` | **verified running** `12:18:05Z`, no input sent |

   Rows 5 and 6 are the same grammar defect in the successor text: both were in
   the `09:54:51Z` heartbeat's `not claimable` list (`7158970473`) and only
   became claimable after `798148ce` extended the staged-carrier resume
   wording at `11:52Z`. That, not the scan interval, is what put them 2.5 hours
   behind filing.

3. **The cure, committed at `7a7d7ca1`.** `BURN_WINDOW_BANNER` plus an inline
   `Action:` matcher are accepted **only** under a `BURN WINDOW DISPATCH`
   banner; the same inline Action under any other banner still parses to `None`.
   Verified against the six filed bodies: all six now parse to their lanes, and
   `tests/test_freebuff_watch.py` is `87 passed` including the two new pins. The
   next tick will claim them and file their disposition as superseded (a newer
   restart per lane already exists), so the unacked rows get driver-filed
   verdicts carrying filed and dispositioned timestamps instead of silence.

4. **Efficiency package, implemented and measured.** The monitor reads #684
   incrementally: a persisted `comments_watermark` with `?since=` plus
   `If-None-Match` on the same page, and the heartbeat prints its own counts -
   the `12:18:33Z` heartbeat reports `polls=3 (304=1)`, so the third poll cost
   nothing against the quota. Pickup SLA is a 300-second alert filed at most
   once per 15-minute bucket when a dispatch is claimable and unclaimed; verdicts
   carry `filed` and `claimed`/`dispositioned` stamps (visible on the `11:59Z`
   and `12:07Z` acks); `run_burn` drains up to 20 dispatches per pass with no
   idle gap once the burn window closes. The relay/tunnel for push delivery is
   logged as a build item and not built inside the burn window.

## WIP

- Lane 1 harness work: slice 2 of `#310` (the S5 approval gate moved to
  `harness/provision_approval.py`) is uncommitted on `310-provision-plan-seam`;
  `ruff` is clean and the provisioning, architecture and split suites are
  `273 passed, 1 skipped`. It is not pushed yet.

## NEXT

Queue order unchanged: `#683` (the 89 Codex findings against `main`), then the
RSI builds `#649`-`#652`, then `#703`, then the W6 and W9 rows.

## BLOCKERS

- The four parked lanes need a **fresh dispatch** from oversight, one per lane,
  because execute-once is intact: `dyn-7158410813-0d7e2f37` and its siblings are
  spent claims and the watch will not re-run them. A new row per lane is claimed
  within one tick under the new grammar; the Agensi and BigEnergyCo rows will
  still need the session-list identity cure exercised, which `e6e9b319` carries
  and has not yet been tested live because those two claims were already spent.
- Local `python` on this machine cannot run `test_desktop_command_opens_its_own_log`
  or audit `R13` (the test replaces the global `threading.Thread` while
  `serve_identity()` shells out); reproduced at base `8fc28a0e`. CircleCI is the
  authority for that path.

## WAIT-STATE

idle: none
