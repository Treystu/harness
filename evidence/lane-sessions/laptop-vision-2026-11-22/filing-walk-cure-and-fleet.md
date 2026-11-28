WALK CURE LANDED, PER-LANE VERDICTS FILED, AND THE DESKTOP BLOCKER NAMED

Gate first, as returned: `gates-driver-cures.py` -> `gates-driver-cures.json`, product Jev investigate / proceed, advances 0.93, destructive 0.06, Lucas Gate v2 **pass**, artifact `7acacd6eb0aa648c`. Earlier this session: `113459dc20eb0235`, `daea7c94e8c8d453`, `379adac53d39f72b`, `fcb3e647d9a7cf07`.

## The walk defect was not one defect, and its live proof was blocked by the desktop

Kalshi's first run (7127392246) refused with "the project session list does not hold 'Kalshi Paper Burndown'". Its trace shows the lane was never actually tried, and it shows three separate barriers:

1. `session-list-expand-1: 'Show more' matched 2 settled rows` - the sidebar carries one section control per project; the single-row click could not choose, and the exception **ended the whole walk on page one**, above `B Kalshi-Trader`.
2. `narrow-walk: the search field holds text this query did not write ('Kalshi Paper Burndow')` - the run parked on a one-glyph OCR slip of its *own* query.
3. `identify-6-settled` censused `B Kalshi-Trader, Kalshi Paper Burndown` - the exact, project-scoped row - and the route walk **skipped it** because an exact title was assumed to be a heading or a duplicate.

Then, in the re-runs after the cure, a fourth cause appeared that had nothing to do with the walk: every `scroll_freebuff` failed with

```
FreeBuff is not the foreground window; held by hwnd 1049510 pid 12304 title 'Windows Security'
```

so the sidebar never moved, every census re-read the same viewport, and the run was filed against the lane again. **A `Windows Security` prompt (PID 12304) has held the foreground continuously since at least 23:21 HST** and holds it as I write this; no driver input can land while it is up.

## Four cures, each with a test that fails without it

| Commit | Defect measured | Cure |
|---|---|---|
| `f946e206` | walk aborted at two section controls; prefix readback refused its own OCR slip; route walk skipped the exact scoped row | `expand_sections()` expands every visible control in turn, coordinate-bound, target project's section first, failures skipped; the readback tolerates one misread glyph and still refuses foreign text; an exact title under this lane's project heading is the pick |
| `503be9f4` | `locate-bystander-lane` ended Kalshi (7127830177) and Disk Audit (7127395609) before their own first phase | the witness reveals the row inside a bound and records `bystander-unobserved` instead of blocking; a visible bystander is still witnessed end to end |
| `6bba9cae` | CivicScope (7127711668) was cut off at page 11 by the 240 s bound | `dynamic_phase_timeout()` = 480 s for a claimed dispatch, because the expanded walk is deeper by design; still bounded |
| `e2c08043` | a lost desktop was reported as "the list does not hold <lane>" | `ForegroundLost` names it; `scroll_by` raises it instead of returning "no movement"; the navigation layer re-raises instead of converting it into a claim about the lane |

Tests, all green on the pushed head `e2c08043`: `tests/test_session_walk_expand.py` (7, five failing without the cure - verified by stashing), `tests/test_bystander_tolerance.py` (3, all three failing without), `tests/test_dynamic_phase_timeout.py` (3), `tests/test_foreground_lost.py` (3, all three failing without), `tests/test_civicscope_identity.py` (5). Plus `unittest discover -s tests -p "test_freebuff*.py"` = **112 tests OK** and `ruff check scripts tests` clean.

## Per-lane verdicts

| Lane | Dispatch | Outcome | Evidence |
|---|---|---|---|
| SCMessenger | 7127391398 | **RUNNING, hands-off** - `verified running: the session was already in a turn; no input sent`, `type 0 / send 0` | 7126988318 + runner trace |
| Lane 1 | 7127662325 | **already in a turn, nothing sent** - prepare recorded `the requested session is already running; no restart input`, so the composer fence was never even approached | `dyn-7127662325-315608d2` |
| Kalshi Paper Burndown | 7127392246 -> 7127830177 -> 7128587548 | **parked**: walk barriers 1-3 (now cured), then the `Windows Security` foreground refusal | three traces |
| Harness Audit Lane | 7127392966 -> 7127830980 | **parked**: walk barrier, then the same foreground refusal | two traces |
| BigEnergyCo | 7127394796 | **parked**: `search: driver tree terminated after deadline` at the old 240 s bound | trace |
| Disk Audit | 7127395609 -> 7128588342 | **parked**: bystander witness (cured), then the foreground refusal | two traces |
| CivicScope | 7127711668 | **parked**: `search: driver tree terminated after deadline` while still censusing page 11 | trace |
| Lane 2 | 7127393679 | **parked**: walk refusal, pre-cure. Lane 2 is mid-turn and hands-off; nothing was sent to it | trace + in-view frame |
| Agensi | - | **named gap, no send**: the read-only local lookup returns `None` for `26646448`, so there is no measured UUID to pin. It needs an in-view census to establish project, title, thread and model | lookup output |

Zero false-green verdicts. No lane received a second send; the only inputs this pass were the ones whose traces are quoted above, and every one of them records `send_freebuff: 0` or `already running`.

## The blocker, named plainly for the owner

**A `Windows Security` prompt (PID 12304, hwnd 1049510) holds the foreground.** While it is up, FreeBuff cannot be activated, so no lane can be driven. It is not a driver defect and it is not my surface to dismiss - I will not click or take over a security prompt. Dismiss it and the queue executes; the four cures are already in place for everything behind it.

Everything else is green and pushed: branch head `e2c08043`, `:8765` answering 200, watch ticking on the new head, PR #685 OPEN and unmerged, #701 and #702 untouched, no composer overwritten, Lane 1's draft never touched.
