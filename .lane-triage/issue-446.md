## Diagnosis

The test invoked the real `--check-fresh` face, and that face answers a wall-clock question about a file committed to the repo: `load_tier_snapshot()` reads `packs/tiers.snapshot.json`, `check_tier_snapshot_freshness()` compares its `captured_at` (2026-10-18) against `datetime.now()` with `max_age_days: 14`. On 2026-11-01 the artifact aged out, `_cmd_economics` took its stale branch and raised `SystemExit(2)`, and unittest reports an escaping `SystemExit` as an *error*, not a failure. That is why the symptom was "errors=2" on heads that changed nothing: it fired on a calendar, not on a diff, and main aged out on the same day as the PR heads. It began between Oct 29 and Oct 31 because that is when the artifact crossed the window, not because anything landed.

The second half was a dead end behind the gate: the stale warning said "refresh via `harness economics --report`", and `--report` writes no snapshot. So the only advisory the gate emitted pointed at a command that could not cure the condition it was describing.

## Cure on `lane/burndown`

1. **The test no longer reads the clock** (`tests/test_economics_cli.py`): a fixture snapshot captured now, pointed at through a patched `TIERS_SNAPSHOT_PATH`, pins payload shape, `age_days` and the exit-on-stale path. Shipped-data currency belongs to the scheduled workflow; committed artifact *shape* is pinned without comparing it to today's date.
2. **The writer exists** (`harness/routing_table.py`, `harness/cli_parser.py`, `harness/cli.py`): `harness economics --refresh-snapshot` rebuilds `price_table` from the live catalog, restamps `captured_at`, preserves tier membership, `task_classes`, schema and `max_age_days`, writes atomically, and refuses with exit 2 and an untouched artifact on an unreadable artifact, empty catalog, any tier id absent from the catalog, any priced id unpriced, or a negative rate.
3. **The advisory names the route that works**: the stale warning now says `harness economics --refresh-snapshot`, pinned by `test_check_fresh_names_the_route_that_actually_writes_the_artifact` (exit 2, `ok: false`, wording).
4. **Delivery loop restored** (`.github/workflows/rankings.yml`): refresh, then freshness check, then a `gh`-CLI PR with the refreshed artifact; `contents: write` and `pull-requests: write`.
5. **Artifact refreshed**: `captured_at 2026-11-03T11:00:23Z`, catalog 408 models, 16 tier ids, 12 price entries; `--check-fresh` returns `ok: true, age_days 0.0`. The delisted T0 id `nvidia/nemotron-3-super-120b-a12b:free` was replaced by its live successor in both the artifact and the bootstrap literal.

## Evidence

- `a8c6be5` (run 41628519244): 17/17 check-runs success - all six hermetic legs, audit, changed-file typecheck, UI smoke, hygiene, package and installed-package legs.
- `6a4988d`: same tree plus the advisory fix and its pin.
- Local: `Ran 5354 tests ... OK (skipped=65)` in 446.7 s on the merged tree.

## Disposition

Diagnosed, cured, and green on the lane; **not closed**. The red this issue tracks is the repo-wide failure on `main`, and main still carries it until this cure lands. Landing is gated by the base being green (`main 5eb9c36` is red on its own run 41576644039), which is recorded as the blocker on #442. Close this when the cure is on main and the hermetic legs there are green.
