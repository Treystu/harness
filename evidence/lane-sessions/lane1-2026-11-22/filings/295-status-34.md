# Lane 1 check-in - status 34

This filing reports verified work only. It closes nothing and takes no
completion credit.

## DONE

- **#683 batch 4.** Rows 37-48 were verified by reading each named code path in
  `origin/main` at `8fc28a0e`. Result: **1 FIXED, 11 STILL PRESENT, 0 NOT
  APPLICABLE**. Row 48 is `driver_core/bridge_battery.py`: `run_battery`
  (:452-466) now runs probes 2-6 in a scratch temporary root while probe 1
  keeps the shared ledger, which is the separation the finding asked for.
  Running totals over rows 1-48 of 89: **13 FIXED, 35 STILL PRESENT**, 41 not
  yet verified.
- The batch-4 disposition is posted on #683 as comment `7167761734`, after a
  gated rewrite when the first draft came back from Jev as `needs_improvement`.
- Eleven gated sub-issues cover the still-present rows: #749 (row 37), #755
  (row 38), #750 (row 39), #756 (row 40), #757 (row 41), #758 (row 42), #759
  (row 43), #751 (row 44), #752 (row 45), #753 (row 46), #754 (row 47). Row 41
  was reframed to the bounded containment change and the independent-holder
  design is named there as an owner decision, not a lane decision.
- **PR #724.** The rail read green on the previous evidence head `16735c72`:
  all 14 CircleCI contexts `success`, read one at a time. The body now names the
  current head `7d438330`, whose run was still pending at this read.
- **Driver watch.** The watch left `idle_watching` at 16:14:33Z when a ledger
  canary PUT failed, then ticked clean at 16:20:40Z (`exit_code 0`,
  `paused: false`, head `08ce64fe`). It is watching again; no dispatch was
  double-executed.

## Incident observed

GitHub returned HTTP 500 for issue comments and issue creation on this
repository between roughly 16:12Z and 16:19Z. Both REST and the GraphQL
`addComment` mutation failed, and the driver hit the same fault on its ledger
write. Retries were made only after a title existence check, so no duplicate
issue or comment was created. Posting resumed on the first retry after
recovery.

## WIP

Nothing is uncommitted. Lane evidence lives on `310-provision-plan-seam` at
`7d438330` (`328c937e`, `7d438330`: batch-4 records, filings and gate receipts).

## NEXT

1. #683 batch 5: rows 49-60 against `main`.
2. Then the queue behind it: #649, #650, #651, #652, then #703.
3. Read the rail at `7d438330` one context at a time until it is green or red.

## BLOCKERS

- CircleCI queue depth: contexts stay `pending` for tens of minutes, so the
  green read at a new head is slow, not absent. GitHub Actions `ci` remains a
  runner-start failure on unrelated heads and is not read as a signal.

## DIRECTIVES

No new directive from oversight was found on #295 or #683 at this read. The
newest authoritative filing still governs, and the lane continues the burndown
under it without loosening the execute-once, 60-second freshness re-read or
episode-state checks.
