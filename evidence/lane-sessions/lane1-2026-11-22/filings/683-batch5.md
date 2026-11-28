# #683 batch 5 - rows 49-60 verified against main

This is a disposition comment for the #683 tracker. It closes nothing and takes
no completion credit.

## Method

Each row was checked by reading the exact code path the finding names in
`origin/main` at `8fc28a0e`, on 2026-11-25. A row is FIXED only when the shipped
code now does what the finding asked; it is STILL PRESENT when the path the
finding describes is still reachable. No repository code changed in this act,
so every verdict is a code read and no new test was run.

## Result: 4 FIXED, 8 STILL PRESENT, 0 NOT APPLICABLE

| Row | File | Finding | Verdict |
| --- | --- | --- | --- |
| 49 | driver_core/bridge_battery.py | Pass the selected freshness window into the live reader | FIXED |
| 50 | driver_core/bridge_battery.py | Include the capture output environment in the live runbook | FIXED |
| 51 | harness/flush_loop.py | Wire the durable trace into the campaign entry point | FIXED |
| 52 | harness/decision_trace.py | Accept filesystem paths in the trace reader | FIXED |
| 53 | harness/decision_trace.py | Preserve immutable segment contents when pinning a window | STILL PRESENT |
| 54 | harness/cli.py | Handle an unrecorded trace before accessing its event ID | STILL PRESENT |
| 55 | harness/decision_trace.py | Include retained segments when reading a ledger path | STILL PRESENT |
| 56 | evidence/lane-sessions/w2-2026-11-20/gates_turn9.py | Run Lucas Gate before the Jev disposition | STILL PRESENT |
| 57 | evidence/lane-sessions/w2-2026-11-20/rerun_415.py | Poll the run result endpoint | STILL PRESENT |
| 58 | harness/escalation.py | Record paid attempts that exceed the actual task budget | STILL PRESENT |
| 59 | harness/apply_policy.py | Preserve the configured pool before capability ordering | STILL PRESENT |
| 60 | harness/apply_policy.py | Record paid BYOK attempts in the routing trace | STILL PRESENT |

## The fixed rows

- **49** driver_core/bridge_battery.py:404 `live_reader` now accepts `max_age` and passes it to `bus_capture_backend` (:423-424); the CLI passes `args.max_age` at :533, so a non-default window reaches the backend instead of its `DEFAULT_MAX_AGE`. The probe still dates its own envelope at receipt (:152-155), but the gate it depends on now enforces the requested window, so the two-second frame under `--max-age 1` is refused.
- **50** driver_core/bridge_battery.py:61-80 `LIVE_RUNBOOK` now states that `DRIVER_SCREEN_OUT` must name a writable PNG path the driver can read (for example `<root>/frame.png`) and repeats it in step 1 before the hand starts; the runbook no longer omits the capture output the Windows reader requires.
- **51** harness/flush_loop.py:1299 `run_campaign_file` constructs `EventLedger(chosen_ledger, trace=campaign_trace(trace_path))`, and `campaign_trace` (:675) returns `DecisionTrace(durable)`. The production campaign entry point now mirrors events into the durable ledger, not only the sidecar.
- **52** harness/decision_trace.py:198 returns `paths = [source]` for a `str`, so `read_trace_events(ledger.path)` reads the file instead of raising `TraceError`; the documented string-path interface now works. (`Path` objects are still not normalized, which the finding did not name.)

## The still-present rows

- **53** harness/decision_trace.py:243-246 builds the manifest by hashing each segment file where it sits and recording only basename, sha256 and size. The active file is mutable, so one append after `pin_window` makes the recorded hash disagree, and rotation then moves those bytes away from the recorded basename.
- **54** harness/decision_trace.py:128-134 returns `{"unrecorded": True}` with no `event_id` when the append fails and `audit_enabled` is false. `harness/cli.py:2151` reads `entry["event_id"]` outside its try block, and `record_disposition` is called without `audit_enabled`, so a failed append still raises `KeyError` instead of the JSON error and exit 2.
- **55** harness/decision_trace.py:198-199 treats a string source as exactly one path and never calls `_segment_paths`, so a path-based read silently excludes retained segments after rotation, despite the reader's documented active-plus-archive behaviour.
- **56** evidence/lane-sessions/w2-2026-11-20/gates_turn9.py:54 calls `policy.evaluate_decision` before `run_typed_track` at :68, so the Jev disposition still precedes Lucas Gate v2 in that filing script.
- **57** evidence/lane-sessions/w2-2026-11-20/rerun_415.py:70 requests `/api/runs/` + run_id, while harness/server.py:2022 dispatches only `RUN_SUB_RE` (`result`, `events`, `cancel`); the bare run URL has no handler, so the poll cannot see a terminal status.
- **58** harness/escalation.py:389-394 calls `governor.record_actual` and then raises `HarnessError` when actual spend exceeds `task_max_cost`; no `_record_attempt` call happens before the raise, so an over-budget paid rung leaves no attempt trace.
- **59** harness/apply.py:175 sets `ordered, profiles = ordered_pool(...)`, so `req.ordered` is already the ranked output. harness/apply_policy.py:369 passes it as `pool_order` and :79-84 records it as `configured_pool`, which therefore cannot show which candidates capability ordering removed.
- **60** harness/apply_policy.py:470-483 the paid-BYOK branch appends `model_result` directly and rotates without calling `_record_billable`, whose call at :148 is the only `_record_attempt` site; that attempt is absent from the routing trace.

Machine-readable: `evidence/lane-sessions/lane1-2026-11-22/683-batch5.json`,
where each row carries its verdict, evidence, finding body and discussion url.

## Running totals for #683

Rows 1-60 of 89: **17 FIXED, 43 STILL PRESENT, 0 NOT APPLICABLE**, 29 not yet
verified. The tracker is not closeable on this subset.

## Next for this issue

One sub-issue per still-present row in this batch, gated the same way as
#749-#759, then rows 61-72.
