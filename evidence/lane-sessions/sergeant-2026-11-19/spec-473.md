## Persistence unblocker SPEC for #473 - router health and the ordering produced at each rotation (sergeant feed, queue item 5)

Queue position: D5 persistence queue, fifth item. Slots 1-4: #468 delivered as #628, #471 as #630, #472 scoped at 7008217920, #475 scoped at 7008874997. Read from `origin/main` `17906e2c`, so it builds on the `trace_v1` writer family that #627 landed.

### 1. The mechanism, at file:symbol:line

| Element | Site at `17906e2c` | What it does |
|---|---|---|
| rotation decision | `harness/router.py::Router._rotation_ordered`:91-111 | pins the declared head, ranks only the tail, and returns the declared pool untouched unless something in the tail has been observed |
| the four rotation surfaces | `harness/router.py`:112 `panel_pool`, 120 `apply_pool`, 128 `specialist_pool`, 136 `escalation_pool` | each property is a separate ordering decision, re-evaluated on every access |
| health writer | `harness/router.py::Router.note_model_result`:64-82 | the **only** writer of `_model_health` (declared in `__init__`:51); success decrements the error count toward a floor of 0, failure increments, `latency_ms` stored only when measured |
| health reader | `harness/router.py::Router.model_health`:84-90 | returns a copy of the registry |
| ranker | `harness/dynamic_allocation.py::rank_models_dynamically`:253-286 | score starts at `100.0`; `-20.0 * errors`; `-min(30.0, latency_ms / 100.0)`; if `prefer_paid` and the model is free, `-15.0`; if not `prefer_paid` and the model is paid, `-min(25.0, input_cost_per_million * 10.0)`; then `sorted(..., reverse=True)` - a stable sort, so ties keep declared order |
| ranker callers | `harness/router.py:106` (the only caller in `harness/`) | passes `tail`, the health registry and `prefer_paid=not self.use_free` |
| health callers | `harness/apply_policy.py::_note_model_health`:285, forwarding to `note_model_result` at 292; invoked at 171, 178, 394, 413, 426, 443, 464, 497 | every observed apply attempt, pass or fail |

### 2. The gap, stated as code rather than as an impression

`rank_models_dynamically` computes a full `scores` dict and **returns only the ids** (`:286`), so the reason an order came out as it did is discarded at the point it is known. `_rotation_ordered` returns silently - no event, no row, and it does not even reach `harness/events.py::emit`:223 (which is itself a no-op when no sink is registered, the finding #475 records). `_model_health` lives in a plain dict on the instance (`:51`), so a restart erases every observation and the rotation reverts to declared order with no record that it ever ranked.

One correction the record owes the brief: #473 says "only three configured pools". The code at this head exposes **four** rotation surfaces - panel, apply, specialist and escalation - each a separate ordering decision. Three was a snapshot of configured pools, not of surfaces; the spec below makes the surface a recorded field so a count is derivable from rows instead of from memory.

### 3. The contract

Two event kinds in the existing `trace_v1` family, written through `harness/decision_trace.py::DecisionTrace.record`:112 and read with `read_trace_events`:190.

**`router.health`** - one row per `note_model_result`, carrying `model`, `ok`, `errors_before`, `errors_after`, `latency_ms` (null when unmeasured), and `surface` when the caller knows it.

**`router.rotation`** - one row per ordering decision that actually changes the order, carrying: `surface` (`panel` | `apply` | `specialist` | `escalation`), `pool_declared`, `pool_returned`, `head_pinned` (bool) and `head_model`, `health_snapshot` (the `{model: {errors, latency_ms}}` entries the ranker actually saw, for the tail), `scores` (the exact floats the ranker computed, unrounded), `config` (`prefer_paid`, `error_weight`, `latency_divisor`, `latency_cap`, `free_penalty`, `cost_weight`, `cost_cap`), and `rank_rule` (`declared` when the early return fired, `observed` otherwise).

Dedupe rule, because these properties are read often: one row per (surface, call id). A second access with unchanged health and the same call id writes nothing.

### 4. Acceptance conditions a reviewer can falsify

1. **Order is recomputable from the row.** Given `pool_declared`, `health_snapshot` and `config`, a reader applying the documented formula reproduces `pool_returned` exactly - including a tie case, where the stable sort must preserve declared order.
2. **Head pin is absolute.** For any pool where the declared head would rank last by score, `pool_returned[0] == pool_declared[0]` and `head_pinned` is true.
3. **Unobserved pools write nothing.** The early return (`not any(m in health for m in tail)`) produces zero `router.rotation` rows, and the returned order equals the declared order.
4. **Health is replayable across a restart.** From the `router.health` rows alone, a fresh process rebuilds `_model_health` such that the next rotation for the same pool returns the same order the live instance would - asserted by reconstructing in a new instance and comparing.
5. **Sink-independence.** All rows above exist with **no** event sink registered (the default CLI path), which is the same defect class #475 records and the reason this cannot be satisfied by adding `emit` calls.
6. **Byte-identical without the path.** With the trace absent, each surface's returned order and the ledger's pre-existing row sequence are unchanged, and no new kind appears.
7. **Dedupe holds.** Repeated property reads under an unchanged health snapshot and the same call id add no rows; a changed snapshot or a new call id adds exactly one.
8. **Surface coverage.** With all four pools configured and each observed enough to reorder, four distinct `surface` values appear - the count the brief could not state is now derivable.

### 5. What this does not license

No new sink or envelope: two kinds in the existing family. No change to the ranking policy, the head pin, or `prefer_paid` semantics - this records the decision that is already made. No product behaviour gated on the trace. **No completion credit**: #473 stays open and unmeasured until its own admissibility window runs; this filing is scope plus acceptance only.

**Gates, in order.** Product Jev (keyed `jev-1.14.0`, caller `sergeant-473-spec`, site `audit_admissibility`): verdict investigate, disposition proceed. Lucas Gate v2 (typed track, untracked receipt `gates-473spec.json`): pass.
