## Persistence unblocker SPEC for #475 - per-attempt `http_status` and attempt timestamps, for panel and Jev calls (sergeant feed, queue item 4)

Queue position: D5 persistence queue, fourth item (slots 1-3: #468 delivered as #628, #471 as #630, #472 scoped at 7008217920). Read from `origin/main` `17906e2c`, after #627 landed the `trace_v1` writer family, so this spec builds to the seam that exists rather than to one that is coming.

### 1. The gap, and why the brief is still right after this much instrumentation

Every value the brief names is **already computed and then discarded**. That is the finding, and it is why the row cannot be closed by "we log it":

| Mechanism | Site (file:symbol:line at `17906e2c`) | What it already computes | Where it dies |
|---|---|---|---|
| shared sink | `harness/events.py::emit`:223 | envelope with `ts`, `seq`, `type`, all fields | `if not _sinks: return` - **with no registered sink (the default CLI run) nothing is emitted at all**, and no sink retains history across a process |
| panel bounded 429 retry | `harness/panel.py::_run_panel_slot`:343, retry loop 353-410, backoff 408-410 | `status`, `retry_count`, `RETRY_429_BACKOFF_SECONDS * retry_count` | `model_result` ledger rows carry `status="error"`, `cost`, `retry=True` - **no `http_status`, no attempt index, no timestamps**; the status survives only in the ephemeral `_events.emit("rotation", ... http_status=status ...)`:420-423 |
| Jev transport attempts | `harness/jev.py`:707 / 754-756 (`model_request_start` / `model_request_end` with `http_status=status`, `duration_s`) and 943-972 for `jev_once`; posts at 716-723, 947 | `http_status`, monotonic `duration_s`, `request_id` | emitted only - no durable row, so an audit of a past run cannot see them |
| Jev breaker state | `harness/jev.py::CircuitBreakers`:453, `acquire`:463-490, `record`:492-515, `would_allow`:517+; sites wired at 686/881 and 892/913 | `failures`, `opened_at`, `probing`, `generation`, the refusal reason string | **in-memory only**; a restart erases the evidence that a site was being broken |
| chat reasoning-param retry | `harness/chat.py::_chat_fireworks` post at 1018, retry decision 1019-1028; OpenRouter path 790-800 | the rejected attempt's status and error text, the decision to retry without the key | `_events.emit("rotation", reason="reasoning_param_rejected", note=...)` - **the status is not carried, no timestamps**, and `harness/chat.py::note_reasoning_param_rejection`:292 persists only the model id (not when, not with what status) |

So the unblocker is not "add logging". It is: **route these already-computed facts into the durable trace family** (`harness/decision_trace.py::DecisionTrace.record`:112, kind namespace `trace_v1`, read back with `read_trace_events`:190), so they exist with zero sinks and survive the process.

### 2. The contract - one durable event per HTTP attempt

One `attempt.record` event per attempt actually made, from all four producers (panel seat, Jev `jev`, Jev `jev_once`, chat reasoning retry), carrying:

- identity: `mechanism` (`panel` | `jev` | `jev_once` | `chat_reasoning_retry`), `model`, `request_id` where one exists, `attempt_index` (0-based within the call), and the trace envelope's own subject/call ids;
- `http_status`: the integer the transport returned; **`null` only when the transport raised** before a status existed, and in that case `transport_error` carries the exception class name;
- timing: `happened_at` (the envelope's existing field), plus `duration_ms` measured on a monotonic clock around the attempt - the same measurement Jev already takes at 709/755, reused rather than re-taken;
- `outcome`: one of `ok`, `rate_limited`, `http_error`, `transport_error`, `param_rejected`, `spend_limit`, `cancelled`;
- `retry_decision`: one of `retry` (with `backoff_ms` when a sleep was applied), `rotate`, `abort`, `none`;
- for Jev only, `breaker`: `{failures, opened, probing, generation}` as read at `record()` time, so the breaker's reasoning is reconstructible after a restart instead of vanishing with it.

### 3. Acceptance conditions a reviewer can falsify

1. **Sink-independence.** Register **no** event sink, drive one scripted panel call through `200` and one through `429, 429, 200`, and assert the durable rows exist and carry `http_status` `[429, 429, 200]`. Today this fails by construction (`emit`:223 returns immediately), which is the defect.
2. **One row per attempt, no more and no fewer.** For the scripted sequences - panel `429,429,200` (3 rows), Jev `500` then success on rotation (2 rows), chat param-rejection retry (2 rows) - the row count equals the attempts and each `attempt_index` appears exactly once.
3. **Status fidelity.** Every row whose transport returned a status carries that exact integer; no row reports a status the transport did not return, and no status-bearing row carries `null`.
4. **Timing sanity.** `duration_ms >= 0` for every row, per-attempt durations are non-overlapping within a call, and their sum does not exceed the call's measured wall time (measured in the test, not asserted from prose).
5. **Byte-identical without the path.** With the trace absent, each mechanism's pre-existing ledger row sequence is unchanged and no new kind appears - asserted per mechanism, not once globally.
6. **Refusals write nothing.** A local reservation refusal (`reservation_missing`), a cancelled call (`ToolCancelled`), and a policy abstain produce zero `attempt.record` rows.
7. **Reader re-derives the ladder.** From the rows alone, `read_trace_events(..., kinds=["attempt.record"])` reproduces the sequence of statuses and the decision taken at each step (429 -> `retry` with the applied `backoff_ms`; 400 + a `_REASONING_PARAM_ERR_HINTS` match -> `param_rejected` then a retry; 5xx -> `rotate`), matching what the mechanism did in the same test.
8. **Breaker reconstruction.** After a Jev site opens, a fresh process reading the rows can state which site was open, after how many consecutive failures, and at which generation - i.e. the `breaker` payload is enough to rebuild the state `would_allow` would have reported.

### 4. What this does not license

No new sink, no new envelope: `attempt.record` is one kind in the existing `trace_v1` family, written through the one writer. No mechanism's retry policy changes - this records decisions that are already made, it does not make them. No product behaviour is gated on the trace being present. **No completion credit is taken**: #475 stays open and unmeasured until its own admissibility window is run, and this filing is scope plus acceptance only.

**Gates, in order.** Product Jev (keyed `jev-1.14.0`, caller `sergeant-475-spec`, site `audit_admissibility`): verdict investigate, disposition proceed - a non-proceed that authorizes no content change. Lucas Gate v2 (typed track, receipt `gates-475spec.json`, untracked): pass.
