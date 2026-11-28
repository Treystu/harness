# Lane 1 check-in - status 35

This filing reports verified work only. It closes nothing and takes no
completion credit.

## DONE

- **#683 batch 5.** Rows 49-60 were read against `origin/main` at `8fc28a0e`.
  Result: **4 FIXED, 8 STILL PRESENT, 0 NOT APPLICABLE**. Fixed: 49 (the live
  reader now receives `--max-age` and passes it to the bus backend), 50
  (`LIVE_RUNBOOK` now requires `DRIVER_SCREEN_OUT`), 51
  (`run_campaign_file` builds the ledger with `trace=campaign_trace(...)`), 52
  (a string ledger path now reads instead of raising). Still present: 53, 54,
  55, 56, 57, 58, 59, 60.
- Running totals over rows 1-60 of 89: **17 FIXED, 43 STILL PRESENT**, 29 not
  yet verified.
- The batch-5 disposition is posted on #683 as comment `7168075580`.
- Eight gated sub-issues cover the still-present rows: #760 (row 53), #761
  (row 54), #762 (row 55), #763 (row 56), #764 (row 57), #765 (row 58), #766
  (row 59), #767 (row 60).
- **PR #724.** The body names the lane head that carries this evidence. The
  rail read 15 `success` / 1 `pending` (`audit`) at `a701ab9c`, and was still
  filling at the later head when this was written; no context was red at any
  read.

## WIP

Lane evidence is pushed on `310-provision-plan-seam`: `c21e0261` carries the
batch-5 record, filing, gate receipt and sub-issue bodies. Nothing is staged
but uncommitted.

## NEXT

1. #683 batch 6: rows 61-72 against `main`.
2. Then rows 73-89, and the queue behind the tracker: #649, #650, #651, #652,
   then #703.
3. Read the rail one context at a time on the final head until it is green or
   red, and report which.

## BLOCKERS

- CircleCI queue depth: the rail needs tens of minutes per head, and every
  evidence commit moves the head, so the green read always trails the newest
  evidence by one run.
- The comment API returned HTTP 500 on a subset of writes during this session;
  every post was retried after a duplicate check, and none was duplicated.

## DIRECTIVES

No new directive from oversight was found on #295 or #683 at this read. The
lane continues under the newest filing without loosening the execute-once, the
60-second freshness re-read or the episode-state check.
