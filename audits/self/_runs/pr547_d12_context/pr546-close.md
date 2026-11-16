CLOSED - #541 lands through PR #547, which is the vehicle for this issue

This PR duplicates the #541 portion of PR #547 (the never-defer bundle #538-#544). One issue gets one vehicle; the wider bundle is the one being taken to green, so this branch is closed rather than iterated.

Why #547 wins: it carries the #541 repair at the same acceptance bar - raw output preserved in the record, one bounded repair strictly cheaper than a second full call (`test_repair_cost_is_strictly_less_than_a_full_second_call`), a loud heuristic fallback carrying the parse error and a reference to the preserved output (`test_unparseable_decomposition_falls_back_loudly_with_evidence`), and a fail-closed preview that still carries the raw body - while also covering #538, #539, #540, #542 and #544 in the same landing.

This PR also carried the same `ci/circleci: audit` failure as #547, from the same cause: `harness/availability.py` had no ownership row in `CONTRIBUTING.md`, so the D10 row failed with `uncovered: ['availability']`. That is cured on #547 at b6d33b5.

#541 closes when #547 merges green. Any acceptance point that turns out to be missing from that diff will be filed as a follow-up against #541 rather than resurrecting this branch.
