## Lane 1 status: driver claim loop cured, SCM parked, PR #720 rail green

### DONE

**Driver (branch `laptop-vision-20261122`, head `852c9854`)**

| SHA | What |
|---|---|
| `3cca6116` | claim scan accepts the wording the oversight files (`ACTION (runner only)`, `Action:`, `Runner action requested:`); lane read from the banner when no `Lane:` line; heartbeat names unparseable owner dispatches instead of reporting an empty queue |
| `821d9d32` | only the newest restart per lane is claimable; an older episode is closed by construction |
| `8f29f91f` | owner `CANCELLATION` naming the dispatch id or the episode closes it (lane-only cancellation closes nothing) |
| `852c9854` | `control.json` `cancelled_lanes` is enforced at claim time; it was inert before, so the 01:28Z route cancellation protected nothing |

63 tests in `tests/test_freebuff_watch.py` + `tests/test_civicscope_identity.py`,
`ruff check` clean on both files.

Execution evidence: `7146588401` (SCM, `2ae32937`) claimed 01:22:56Z, acked,
executed, verdict `parked: prepare: BLOCKED: the exact pinned session route is
required for this standing dispatch` at 01:26:59Z (#684 `7149558080`). That is
the claim path proven end to end plus an honest named block, not a retry.

Backlog: zero #684 dispatches left unclaimed and open. `7145072019` was claimed
and closed with `no input sent`; the four `Action:`-wording Lane 1 restarts are
superseded by it; `7117989632` is TTL-expired; `7121037795` is a non-restart
audit dispatch.

**PR #720 (branch `310-provision-plan-seam`, head `c471eb5a`)**

| SHA | What |
|---|---|
| `32d9ef24` | `CONTRIBUTING.md` maps `harness/provision_plan.py`; the split's new module was uncovered, so audit `sd_contributing` scored it 0.0 and SD fell under the bar |
| `c471eb5a` | evidence filings say "stays open" instead of the negated close wording `driving-hygiene` flags |

CircleCI rail at `c471eb5a`, read status by status: **all 16 pass** - `audit`,
`driving-hygiene`, `test`, `package`, `Checkout hygiene`, `ui-playwright-smoke`,
`local fit`, six `hermetic suite` legs, three `installed package` legs. PR body
names that head. GitHub Actions check-runs fail in ~2s on every leg at every
head on this repo (billing lock), so they are not the read.

### WIP

Nothing in flight; the tree is pushed.

### NEXT

Next unworked queue item from #295's placement order.

### BLOCKERS

- SCM `7146588401` needs its pinned session route supplied from the platform
  side; the driver cannot manufacture it.
- The watch is paused (`paused: true`, `updated_by:
  antigravity-oversight-7149396491`, 01:28:25Z) with
  `cancelled_lanes: ["315608d2"]`. Both are the owner's / Antigravity's to
  clear; I did not clear them.

### DIRECTIVES

`7149396491` items 1-5 answered on #684 (`7149652916`): execution path paused
first, Lane 1 verified read-only and not restarted, census filed here and there,
the episode bound implemented as code with a test per refusal, and the revival
attributed to this lane's own pushes at the 00:58:52Z tick.

### WAIT-STATE

`idle: none`.
