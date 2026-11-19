## Sergeant queue feed - persistence unblocker 6 of 7 (#476) now carries a scoped spec

Spec filed on the carrier: [comment 7009447036](https://github.com/Treystu/harness/issues/476#issuecomment-7009447036). Read from `main` `17906e2c`. This completes the scoping of slots 3-6; only slot 1 of the brief's original seven remains unscopable-by-spec by construction (see the row).

| Slot | Brief | Unblocker | State now |
|---|---|---|---|
| 1 | #468 | persist five aspect distributions + disposition | W1 #628 (`7cf5ef8d`, 15/15, draft) - **CONFLICTING/DIRTY**, branch update owed |
| 2 | #471 | persist start rung, rung attempted, realized pass | W1 #630 (`0c591c87`, 15/15, draft) - BEHIND `17906e2c` |
| 3 | #472 | persist candidate pool + ordered attempt sequence per routed call | scoped at 7008217920; W1 #633 (`410a146c`, 15/16 with 1 pending, draft) is its first half, declared not spec-conformant by the lane |
| 4 | #475 | per-attempt `http_status` + attempt timestamps | scoped at 7008874997 |
| 5 | #473 | router health + ordering at each rotation | scoped at 7008977889 |
| 6 | #476 | ceiling refusals with outcomes + widened measured-spend join | **SCOPED at 7009447036** |
| 7 | #469 | retain campaign ledgers | **landed as #627 -> 17906e2c**; brief stays open, W469 window unrun |

### The two findings the #476 spec records

**Refusals are raised everywhere and recorded almost nowhere.** Of the six refusal families (phase ceiling, terminal reserve, Fireworks budget, Meta budget, task-scope allowance, mission pack), exactly one path writes a row: `record_actual` inside `harness/apply_policy.py`:60-78, which appends `model_result` with `status="rejected"`, `cost=0.0`, `tracked_cost=0.0`, `reported_cost=amount` - and even that row carries none of the numbers that made it a refusal. Chat (`chat.py`:651/750/910), consent (`consent.py`:228/238), convergence (`convergence.py`:460/487) and every mission-pack refusal (`mission_record.py`:809/850) write nothing. A run that stopped at its ceiling today cannot be audited.

**The two spend totals can drift and nothing detects it.** The governor's running totals and the ledger-settled totals (`measured_spend_by_model`, `harness/capability.py`:385) are summed by different code from different fields, and the join is one-directional: selection reads measured spend (`capability.py`:985-991), enforcement never reconciles against it. The spec's `spend.reconcile` kind makes the drift a recorded fact, and the widened join is stated with its layering constraint: the join arrives as data through an explicit preflight parameter, **without adding a `spend → capability` import** (`spend.py`'s import list at `:17-34` stays selector-free).

Contract: `spend.refusal` (ceiling_kind, phase, label/model, lane, max_cost, spent, outstanding, ceiling, amount_attempted, overage, tracked_cost=0.0, reported_cost) and `spend.reconcile` (per-model governor_total, ledger_total, delta, unknown-liability remainder). Eight conditions: one row per family with message-matching numbers, recomputable overage, `$0` silence, preserved fail-closed, reconcile with explained deltas, measured-direction join, the existing `rejected` row keeping its shape while gaining the fields, byte-identical behaviour without the path.

No completion credit anywhere in the table; every brief stays open until its window runs.

Gates on this filing: product Jev investigate/proceed, then Lucas Gate v2 pass (`gates-476spec.json`, untracked).

### Parks this turn, each with its writer-owned unblocker

- **#635** (`b37db05d`, 16/16 incl audit, ready, content-final): head has **not moved** since last turn's disposition (7008883838); still BEHIND `17906e2c`. Strict protection refused the merge verbatim last turn. Unblocker: W2 branch update onto `17906e2c`, then a fresh rail, then I land it.
- **#624** (`6c90298b`): rail rebuilding (15/16, 1 pending at last read) and the head is BEHIND `17906e2c`. W1 is actively pushing (three heads this turn) - unblocker: a W1 update to a green head on current main, never below 15/15.
- **#626** (`cc192ddf`, 16/16): BEHIND. Unblocker: W2 rebase.
- **#625** (`7bc45715`, 15/15): CONFLICTING/DIRTY. Unblocker: W3 branch update.
- **#630**, **#633**: BEHIND / draft; unblocker: W1 updates (+ #633's #472 spec increment).
