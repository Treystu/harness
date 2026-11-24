## Champion set closure - the replay inputs that are not on this machine

Order item 5's second half is the closure of #475 (failure retry and circuit breaking) and #469 (flush-loop stop bar and oscillation breaker). Both briefs are evaluation-first: replay the champion from logged decisions and compare it against the stated comparators, with "no change, here is the measurement" as a valid close. This note records what the inputs are and which of them exist here, measured on 2026-11-24, so the closure is tracked as a data wait rather than left looking unstarted.

### #475 - what it needs

The brief compares the current constants (panel 429 retries 2, backoff base 0.5 s; breaker 3 failures / 30 s cooldown) against retry and breaker comparators, on recovery rate per retry, added latency per recovered call, and wasted spend on retries that never recover.

Each of those needs per-call retry position or a breaker state transition. The home ledger here (`~/.config/harness/ledger.jsonl`, 3156 rows) contains **2864 `jev_eval`** rows, whose full key set is `caller, confidence, cost, decision_advances_goal, decision_confidence, decision_destructive, decision_disposition, decision_lead, decision_margin, decision_pack, decision_threshold, decision_verdict, discarded, event, fallback_reason, hash, input_tokens, is_fallback, model, node_id, output_tokens, prev_hash, seq, site, supported`. There is **no retry index, no attempt number, no breaker state, no 429 marker** in any of them, and the ledger holds **zero panel rows** and zero `model_request_start` / `request_end` rows.

So a #475 replay from this ledger would have to invent the retry position and the breaker history. It cannot be run here, and no partial number is offered in its place.

### #469 - what it needs

The brief compares the current stop bar (95 / floor 85 / absolute 60, clean-expansion streak 2, tail promotion at 5, oscillation breaker 3) against bar 90 + streak 3 and bar 95 + streak 1, on escapes found after stop and tokens spent per campaign, from `record_stop` rows.

Those rows live in campaign histories (`<campaign>.events.jsonl`), not in the home ledger. This checkout and home contain **no campaign history** with a `record_stop` row: the only `*.events.jsonl` files present are dogfood phase artifacts under `.harness/site-query-preview/audits/self/dogfood/` and the extracted PR-head copies, whose rows carry neither a `kind` nor an `event` field and are not campaign stop records.

### What closes it

Either of these, and only these:

- the ledgers and campaign histories from the machines that ran the campaigns are brought into reach (they are the data; this checkout is not), or
- the lanes that own those campaigns publish the stop/retry records as fixtures at a named SHA, so the replay runs offline as the briefs require.

Until one of those happens, #475 and #469 stay open on inputs, not on code, and this lane reports them that way. No comparator is run, no champion is declared measured, and no close is taken.

### What was actually delivered from item 5

The persistence verification: `filings/466-step0-trace-counts.md`, posted here on 2026-11-24. Two independent counts of `decision_trace` rows agree with the writer's own answer on the product persist seam, over a ledger whose `prev_hash` chain verifies (2 rows, seq 1-2, ids `9f3c3f6b...` and `b8e4140d...`). The order's "one live brief run" leg is withheld there for the stated key reason; this note withholds the replay half for the stated data reason. Both gaps are named in the filings, neither is papered over.

**GATE RECEIPT.** Lucas Gate v2 typed track: **pass**, artifact sha256 `1d0622e65e1afb0c12e2359a66a28119e716fd0b063b03fef26fcd4de9fe2a95` (`filings/receipt-466-champion-inputs.json`). Product Jev: label **investigate**, disposition **proceed** (supported 0.04, margin 0.20, model jev-1.14.0). The investigate label is answered from the data itself: the `jev_eval` key set and the event census above were both printed from this machine's ledger in this act, and the absence claims (no retry index, no breaker state, no 429 marker, no panel or campaign rows) are read off those same prints rather than asserted from memory. The filing takes no close, no comparator and no number it did not measure.

Refs #466, #475, #469.
