# #683 batch 6 - rows 61-72 verified against main

This is a disposition comment for the #683 tracker. It closes nothing and takes
no completion credit.

## Method

Each row was checked by reading the exact code path the finding names in
`origin/main` at `8fc28a0e`, on 2026-11-25. A row is FIXED only when the shipped
code now does what the finding asked; it is STILL PRESENT when the path the
finding describes is still reachable. No repository code changed in this act, so
every verdict is a code read and no new test was run. Where a finding's requested
fix was delivered by a redesign rather than a patch, the FIXED note names the
shipped code that replaced the defective path.

## Result: 5 FIXED, 7 STILL PRESENT, 0 NOT APPLICABLE

| Row | File | Finding | Verdict |
| --- | --- | --- | --- |
| 61 | evidence/lane-sessions/sergeant-2026-11-19/gates_620.py | Run Lucas Gate before the Jev decision evaluation | STILL PRESENT |
| 62 | evidence/lane-sessions/sergeant-2026-11-19/gates_624.py | Bind each receipt to the head actually being assessed | STILL PRESENT |
| 63 | evidence/lane-sessions/sergeant-2026-11-19/gates_620.py | Read the decision signals using their returned field names | STILL PRESENT |
| 64 | evidence/lane-sessions/w2-2026-11-20/gates-turn15.json | Regenerate the gate receipt for the committed turn-15 filings | STILL PRESENT |
| 65 | harness/_http.py | Preserve wire attempts across chat-level retries | FIXED |
| 66 | harness/jev.py | Isolate the strict Jev call from previous wire traces | FIXED |
| 67 | docs/found-in-use.md | Verify the vocabulary endpoint before recording a contract gap | FIXED |
| 68 | harness/session.py | Pass the run ledger when assembling the MCP router | STILL PRESENT |
| 69 | harness/router.py | Normalize ledger paths before calling the trace reader | FIXED |
| 70 | harness/spend.py | Distinguish post-dispatch overruns from calls refused before dispatch | STILL PRESENT |
| 71 | harness/spend.py | Include the binding scope's budget in scope-refusal events | STILL PRESENT |
| 72 | harness/flush_loop.py | Handle trace initialization failures without aborting campaigns | FIXED |

## The fixed rows

- **65** The mutable per-transport wire collection the finding names no longer exists: `harness/_http.py:417-421` emits one `provider_http_attempt` event per wire attempt with `request_id` and a per-POST `wire_attempt` counter, and `:460-462`/`:484-486` emit each response status as its own event. A second `transport.post()` from a chat-level retry therefore adds its own attempt events instead of resetting a collection, so a real [400, 200] sequence reaches the stream as both attempts; `harness/_http.py` no longer defines any `_WIRE` accumulator (`git grep` for `_WIRE` at 8fc28a0e matches nothing).
- **66** `harness/_http.py` has no shared wire buffer for a strict Jev call to inherit: `post_once` (`:523-545`) emits `provider_http_attempt` rows with `wire_attempt=1, max_wire_attempts=1` under the per-call `request_id` from `current_provider_request()`, and `harness/jev.py:950-955` opens a fresh `provider_request_context(request_id, ...)` with a new `uuid4()` for `evaluate_once`. `record_call` does not exist at this head (`git grep record_call 8fc28a0e -- harness/jev.py` is empty), so a preceding chat POST's attempts cannot be consumed by the strict assessment.
- **67** The false row is withdrawn and the mis-probe is corrected: `evidence/lane-sessions/w2-2026-11-20/filings/413-correction-t14.md` withdraws `driver-vocabulary-keyless-claim-false`, records that `POST /api/driver/step` never reads `action` and returns byte-identical envelopes with and without it, and re-probes the real route. `docs/found-in-use.md` at 8fc28a0e has no `vocab` row (`git show 8fc28a0e:docs/found-in-use.md | grep -i vocab` is empty), and the keyless route it names exists: `harness/server.py:1901` dispatches `GET /api/driver/vocabulary`.
- **69** `harness/decision_trace.py:198-199` now returns `paths = [source]` for a string, so `harness/router.py:36-47` `read_rotations("/path/to/ledger.jsonl")` reads the file instead of raising `TraceError("reader needs a ledger or a path")`; the raise the finding reproduced is gone. The archive half of the same sentence is a different defect already filed from row 55 as #762, which owns the retained-segment gap, so this row adds no second sub-issue for it.
- **72** `harness/flush_loop.py:665-674` wraps `AutonomyLedger(str(trace_path), caller="flush-campaign")` in `try/except Exception` and returns `None`, with the comment naming exactly the finding's cases (unreadable file, a directory in its place, invalid UTF-8) and stating that `DecisionTrace.record` cannot absorb a failure that precedes the writer. An unavailable trace sink now leaves the campaign running with no trace instead of aborting it.

## The still-present rows

- **61** evidence/lane-sessions/sergeant-2026-11-19/gates_620.py:47 calls `policy.evaluate_decision(...)` and `:63` runs `run_typed_track(...)`; the module docstring at `:1` still says 'Product Jev first, Lucas Gate v2 second'. All 32 `gates_*.py` drivers in that lane keep the same order (for example `gates_624.py` jev=48 lucas=64, `gates_406`-era `gates_482.py` jev=47 lucas=63), so the AGENTS.md sequence is still reversed.
- **62** evidence/lane-sessions/sergeant-2026-11-19/gates_624.py:24-31 `ACTION` names head `6c90298b0bb962862567955601fc89e8dc2a4e6a`, `:38-44` builds the category evidence from 'PR #canon1 at exact head dbb54a7', and `:96-98` writes `_meta.head = "dbb54a7f50216ef537fef71f3d88b2e807d09e45"`. The #624 receipt is therefore still bound to the CANON-1 head and CANON-1 scorecard evidence.
- **63** evidence/lane-sessions/sergeant-2026-11-19/gates_620.py:77-79 serializes `verdict.get("lead")`, `verdict.get("advanced")`, `verdict.get("destructive")`, but `harness/jev_packs.py:2641-2652` (returned verbatim by `harness/jev_policy.py:1730-1732`) composes `disposition_lead`, `advances_goal` and `is_destructive`. `evidence/lane-sessions/sergeant-2026-11-19/gates-620.json` records all three as null under `product_jev`.
- **64** `evidence/lane-sessions/w2-2026-11-20/gates-turn15.json` still records `413-head-currency` sha256 `7fef1693...` and `295-status-15` sha256 `fd707573...`; the committed filings at main hash to `4182bb8647b7e52c820ed74d08e0e754ec1a5be05adb2f7f583f39d258fb68a0` (`filings/413-head-currency-t15.md`) and `a1e6b710d679e02d83d03b2e3da4b6a61b098320729ceea1fb331e545e8f1c5e` (`filings/295-status-15.md`), both computed here from the blobs at 8fc28a0e. The receipt still cannot verify the published filings.
- **68** `harness/mcp.py:1831-1837` builds `ledger = composition.ledger_for(settings, caller="mcp")` and then calls `composition.router_for(settings)` with no `ledger=`; `harness/session.py:243-245` turns that argument into `trace = DecisionTrace(ledger) if ledger is not None else None`, so the MCP-built router still carries `trace=None` and `harness/router.py:152-153` writes no `router.rotation` row. The serve path does pass it (`harness/session.py:303` `router_for(settings, ledger=ledger)`), so only the MCP assembly is unrecorded.
- **70** `harness/spend.py:1103-1104` still calls `_record_refusal(site="record_actual", ...)` when an already-billed response pushes `spent + outstanding + actual` over the ceiling, and `_record_refusal` (`:418`) hardcodes `"outcome": REFUSAL_OUTCOME`, which `:51-53` defines as 'the refused call's outcome: it did not run'. `record_actual` also reaches `_refuse_over_scope` (`:1122-1126`), whose refusal rows carry the same outcome. Executed, billed calls are still classified as refused before dispatch.
- **71** `harness/spend.py:406-411` builds every refusal envelope from `dual_budget_envelope(self.max_cost, self.spent, self.terminal_reserve, ...)` -- the global governor -- and `:436-437` adds only `"scope": str(scope)`. `_refuse_over_scope` (`:453-458`) passes `requested=amount, scope=target.label` and nothing else, so a task-allowance refusal still records the session ceiling and balances with no scope allowance, scope spent or scope outstanding.

Machine-readable: `evidence/lane-sessions/lane1-2026-11-22/683-batch6.json`,
where each row carries its verdict, evidence, finding body and discussion url.

## Running totals for #683

Rows 1-72 of 89: **22 FIXED, 50 STILL PRESENT, 0 NOT APPLICABLE**, 17 not yet
verified. The tracker is not closeable on this subset.

## Next for this issue

One sub-issue per still-present row in this batch (61, 62, 63, 64, 68, 70, 71),
gated the same way as #749-#767, then rows 73-84 and 85-89.

