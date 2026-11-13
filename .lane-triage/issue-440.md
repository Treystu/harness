## Live state: the approved job exists on `lane/burndown`, not on `main`

Drift recorded. `4422355` added the blocking job to `.github/workflows/ci.yml`:

- `driving-hygiene` / `Driving hygiene (deterministic)`, `if: github.event_name == 'pull_request'`, `permissions: contents: read`, `persist-credentials: false`.
- Step 1 runs the fixtures: `python -m unittest tests.test_driving_hygiene -v`.
- Step 2 runs the scan: `python scripts/driving_hygiene.py` against PR text, diff, credentials and issue plans.

## Acceptance check, one line each

- **Blocking job on pull requests:** present and required as a check-run; green on the lane head `cbbfc31` (run 41635922005).
- **Each of the four checks has passing and failing fixtures in the PR that adds the job:** `tests/test_driving_hygiene.py` - negated-close language in PR text and diff; close keyword flagged and the removed-reference case passing; credential fixture failing without echoing the value, plus the PR-text scan; planning-structure accept/reject; and `test_cli_fails_on_seeded_violations_and_passes_after_removal`, which is the seeded-violation-then-removal pair end to end.
- **No model calls, no secrets:** the job sets up Python, runs unittest and the CLI script; no key material is read, no network model call is made, and `scripts/driving_hygiene.py` only parses local text.
- **Seeded credential or close-keyword fails, removal passes:** `test_cli_fails_on_seeded_violations_and_passes_after_removal` demonstrates exactly this pair, and the CI step runs that test file before the live scan.

`main`'s `ci.yml` has only `checkout-hygiene`; `git grep hygiene origin/main -- .github/workflows/` returns no driving-hygiene job. The cure lands with the lane.

## Disposition

Met on the lane, kept open for the main landing, which is gated by the red base (`main 5eb9c36`, run 41576644039) and recorded on #442.
