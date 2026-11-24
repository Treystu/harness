# Register: #343 closed, #344's retrieval-decision binding, #660 filed

Head: `0a1eb9429d1d5251e621140e94ff0647ff86b2fc` (branch
`lane1/register-344-660`, base `main` `03306b0e`). Docs only; no code.

## Rows changed

- **#343** was still `OPEN` in the W5 table after the operator closed it at
  2026-11-22T08:43:02Z with no close comment. The row now reads `CLOSED` and
  records what actually landed on that line (PR #647 per-candidate admission;
  PR #658 fetched-page subject gate), then points at #660 for the two
  acceptance lines that were unbuilt at the close. No completion credit is
  implied for those lines.
- **#344** now records PR #661 (`03306b0e`): reuse is bound to the current
  retrieval decision with the recorded reason `retrieval-declined`, and the
  declined and changed-request controls run through `run_hourglass_request`.
  Its two remaining items are kept named: approved-plan/receipt binding (no
  checkpoint schema field exists) and saved native-route reuse across a changed
  request.
- **#660** added to the W5 table and to the W1 work list: the two unbuilt #343
  acceptance lines filed verbatim per oversight decision `7076933398`.

## Census

Two methods, read this pass: `gh issue list --state open` = 40 and the search
API `type:issue is:open` = 40. The open set is enumerated in full on the census
line, so the number is checkable rather than asserted. The enumeration now
carries the RSI Build 1-4 issues (#649-#652) and #653-#656 that the 2026-11-19
line predated, drops #343 (closed by the operator) and #474 (already closed),
and adds #660.

## Scope

Docs only, one file: `docs/jev-roadmap.md`. No issue is closed by this PR and
no code behaviour changes. CI is read at this exact head from the CircleCI
commit statuses; the merge follows only that read.

## Gate findings and their cures

Two red heads were diagnosed against the jobs' own checks rather than retried:

- `33a7c21f` failed `driving-hygiene`: the #660 row phrased the operator's
action as "closed #343", which the close-keyword rule reads as an auto-close
claim in a register diff. The row now says the operator ended it.
- `884fd7a3` failed all hermetic legs, `test` and `audit` because these rows
live inside the `REGISTER_MIRROR` block: its declared arithmetic (108 rows,
52 `OPEN`, 56 `CLOSED`) and the W5 wave row (4 rows) no longer reconciled with
the tables once #343 moved to `CLOSED` and #660 was added. The mirror now
declares 109 rows, 52 `OPEN`, 57 `CLOSED`, and W5 carries 5 rows.

At this head `python -m unittest tests.test_docs_contracts` is OK (15 tests,
including `RegisterMirrorParityTests`) and `python scripts/driving_hygiene_ci.py`
prints `PASS driving-hygiene: all four deterministic checks passed`. No check
was weakened or skipped.
