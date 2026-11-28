# #683 batch 3 - rows 25-36 verified against main

Verified at `2026-11-25T15:45Z` against `main` `8fc28a0e`. Each row is a read of
the code path the finding names, in this tree, at that head.

## Result: 0 FIXED, 12 STILL PRESENT, 0 NOT APPLICABLE

| Row | File | Finding | Verdict |
| --- | --- | --- | --- |
| 25 | driver_core/mission_executor.py | Require receipt-write capability before executing | STILL PRESENT |
| 26 | driver_core/mission_executor.py | Handle unreadable payloads in the refusal path | STILL PRESENT |
| 27 | driver_core/mission_executor.py | Validate inbox directories against the root | STILL PRESENT |
| 28 | harness/answer_plot_consistency.py | Resolve bar positions before a tick-unit mismatch | STILL PRESENT |
| 29 | harness/answer_plot_consistency.py | Preserve branch conditions for argparse attributes | STILL PRESENT |
| 30 | harness/answer_plot_consistency.py | Compare titles with the effective final scale | STILL PRESENT |
| 31 | harness/server.py | Exclude live requests from recovery | STILL PRESENT |
| 32 | harness/run_recovery.py | Honor the lifecycle's resumability flag | STILL PRESENT |
| 33 | harness/server.py | Probe the connected backend, not a local MCP process | STILL PRESENT |
| 34 | harness/server.py | Supply the MCP auth token to the probe | STILL PRESENT |
| 35 | harness/state_report.py | Require request-specific evidence to confirm | STILL PRESENT |
| 36 | harness/ledger_compaction.py | Cross consecutive signed drop runs | STILL PRESENT |

## Evidence per row

- **25** `process_next` claims and calls `self.execute(mission)` with no capability
  check; `write_receipts` is required only inside `MissionInbox.write_receipt`
  (line 276). A read-only token executes, then fails to file, and the claim stays
  `claimed`.
- **26** `payload = self.inbox.read(filename)` (line 508) runs before the `try`
  that catches `MissionRefused`.
- **27** `_directory()` (line 208) joins and creates with no root or symlink
  check; `os.path.islink` at line 224 tests the file only.
- **28** every named bar-position argument reaches `plain_bar_positions`
  (lines 219, 299) without its value being resolved; finding (3) at line 419
  reports a mismatch whenever power ticks exist.
- **29** `_flag_of` (line 148) resolves `ast.Name` and aliases only, so
  `args.log` yields `None` and both argparse branches share one condition.
- **30** lines 384-397 compare each title with every consistent setter instead of
  the final effective scale.
- **31** `recovered_requests()` (line 1431) passes no live-owner set to
  `discover_requests`, and the status surface merges live and recovered without
  excluding live request ids (line 2130).
- **32** `deferred` is in `_INTERRUPTED` (line 55) and line 133 derives
  `resumable` from `payload["stage"]`, not from the lifecycle's persisted
  `data.resumable`.
- **33** `_default_backend_probe()` (line 113) returns `doctor.check_mcp_stdio`,
  a fresh local `python -m harness.mcp` subprocess.
- **34** line 117 returns the bare probe, so `settings.mcp_auth_token` never
  reaches it.
- **35** `state_report.py:198` sets `confirmed: reachable` for every record when
  the probe is OK, and the probe queries no request id.
- **36** `crosses_gap` (line 431) needs one run spanning the whole gap;
  `_coverage_runs` (line 242) splits runs when the reason changes, so contiguous
  signed runs cannot compose.

Machine-readable: `evidence/lane-sessions/lane1-2026-11-22/683-batch3.json`
(each row carries its `verdict`, `evidence`, finding body and discussion url).

## Running totals for #683

Rows 1-36 of 89: **12 FIXED, 24 STILL PRESENT, 0 NOT APPLICABLE**, 53 not yet
verified. The tracker is not closeable on this subset.

## Next for this issue

One sub-issue per still-present row in this batch, gated the same way as
#725-#736, then rows 37-48.
