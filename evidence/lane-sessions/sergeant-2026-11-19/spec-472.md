## Persistence unblocker SPEC for #472 - candidate pool and ordered attempt sequence per routed call (sergeant feed, queue item 3)

Queue position: D5 persistence queue, third item (after #468 delivered as W1 PR #628 and #471 delivered as W1 PR #630). Register order and unblocker text are from #466 comment 6995807908; this filing supplies the scope and acceptance condition, which is what the queue was missing for this row. Read from `origin/main` `d2e724ba`, not from memory.

### 1. The exact mechanism site (read at that head)

| Element | Site | Line |
|---|---|---|
| Routed-call producer, the one seam that already holds everything | `harness/capability.py::ordered_pool` | 814 |
| The ordering decision itself | `harness/capability.py::order_pool` | 715 |
| Callers that route | `harness/apply.py:172`, `harness/panel.py:239` | - |

`ordered_pool` already computes, in order: the hard capability gate (`info["capability"] <= 0` -> the model is dropped, never ordered), the demotion tier from `ledger.participation_report()` (`unusable_outputs + consent_unusable + minority_dissent + gate_wasted_runs`, strike threshold 2), the scored tuple `(model, reliability, capability, price, is_paid)`, the free-tier vs paid sort keys, and the direct-provider re-insertion that holds a caller-named backend at its given index. None of it is recorded: after the function returns, only the final list survives. That is precisely the trace #472 names as missing.

### 2. What to persist - one event per routed call

One `capability.order` event per call to `ordered_pool`, carrying:

- `task`, `free_tier`, `call_lane`, and the pool source (`apply` or `panel`) - the inputs that select the sort rule;
- `pool_given`: the caller's pool, in the caller's order (so a reader can see what was offered before any gate);
- `scored`: one row per surviving candidate with `model`, `reliability`, `capability`, `price`, `is_paid`, `demotion_tier` - unrounded, as computed;
- `dropped`: one row per hard-gated model with its `capability` value and the reason string `hard_capability_gate`;
- `direct_reinserted`: one row per direct-provider id with its caller index and the index it was re-inserted at;
- `ordered`: the final list, in the order returned;
- `advisory`: the local-fit advisory's state (`off` / `observe` / `influence`) and, when active, which models it moved - a flag, not a duplicated decision.

### 3. Acceptance condition (observable, no prose)

1. **Replayable from rows alone.** A reader given only the event can recompute `ordered` from `pool_given`, `scored`, `dropped` and `direct_reinserted` - demotion tier ascending first, then free-tier reliability descending / paid price ascending - and the recomputation equals the recorded `ordered` for every row the tests exercise.
2. **Behaviour identical without the path.** With the write path absent, the returned order and the ledger rows are byte-identical to `d2e724ba`'s, asserted for a free pool, a paid pool, a demoted model, and a hard-gated model.
3. **Refusals write nothing.** An empty pool, an all-hard-gated pool (the `return list(pool), None` branch), and the exception path (`[capability] unavailable`) write no event.
4. **No new sink, no new segment.** The event goes through the ledger the call already holds; `ordered_pool` opens nothing and defines no segment.
5. **Same inputs, same order.** Two runs with identical inputs and identical trace state produce identical `ordered` and identical `scored`, so a diff of two events means a real difference in the inputs.

### 4. Dependency, stated so it is not discovered late

The trace writer family (`DecisionTrace` over `AutonomyLedger`, `read_trace_events`) is **not on `main`** at `d2e724ba` - it is carried by W1 PR #627 (`43891d83`), with #628 stacked on it. This spec therefore does **not** build a second writer; it names the write as a call into that family, and the row stays parked until #627 lands. If #627 lands with a different seam, the spec's fields and acceptance condition stand unchanged and only the call site moves.

**Nothing here takes completion credit.** #472 stays open and unmeasured until its admissibility window is run; this filing is scope plus acceptance only, and it changes no brief, bar or frozen order.

**Gates, in order.** Product Jev (keyed `jev-1.14.0`, caller `sergeant-472-spec`, site `audit_admissibility`): verdict investigate, disposition proceed - a non-proceed that authorizes no content change. Lucas Gate v2 (typed track, artifact recorded in the untracked receipt `gates-472spec.json`): pass.
