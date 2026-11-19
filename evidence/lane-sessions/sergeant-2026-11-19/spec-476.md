## Persistence unblocker SPEC for #476 - ceiling refusals with outcomes, and the widened measured-spend join (sergeant feed, queue item 6)

Queue position: D5 persistence queue, sixth item. Slots 1-5: #468 delivered as #628, #471 as #630, #472 scoped at 7008217920, #475 scoped at 7008874997, #473 scoped at 7008977889. Read from `origin/main` `17906e2c`.

### 1. The refusal machinery, at file:symbol:line

| Element | Site at `17906e2c` | What it does |
|---|---|---|
| preflight refusals | `harness/spend.py::assert_spend_allowed`:108-139 | `$0` never refuses (`:121-124`); otherwise "…would eat terminal_reserve…" (`:126-132`) or "…would exceed phase ceiling…" (`:133-138`), each message carrying the exact numbers |
| actuals refusals | `harness/spend.py::SpendGovernor.record_actual`:967-1023 | "…would exceed ceiling … by eating terminal_reserve … Aborting." (`:1001-1004`) or "…would exceed ceiling … Aborting." (`:1005-1009`); Fireworks (`:985-989`) and Meta (`:993-997`) budget refusals; scope overages via `_refuse_over_scope` (`:360`) |
| mission-pack refusals | `harness/mission_record.py`:809 (`preflight_spend`), `:850` (`record_spend`), plus "refusing to unlock terminal_reserve early" at :805-808 and :847-849 | pack-budget refusals before any attempt spend is recorded |
| the one path that records a refusal today | `harness/apply_policy.py`:60-78 | catches the governor `HarnessError`, writes a `model_result` row with `status="rejected"`, `cost=0.0`, `tracked_cost=0.0`, `reported_cost=amount`, and re-raises |
| every other refusal path | `harness/chat.py`:651/750/910, `harness/consent.py`:228/238, `harness/convergence.py`:460/487, all mission-record calls | **no durable row** - the numbers in the message die with the exception |
| the measured-spend sum | `harness/capability.py::measured_spend_by_model`:385-415 | provider-settled spend per canonical model from `model_result` rows (`billable_cost` else `cost`); zero-cost rows contribute nothing |
| the only consumer of that sum | `harness/capability.py`:985-991 | `measured_spend` feeds `measured_usd_per_success` at :1009-1011 for selection |
| what enforcement never consults | `harness/spend.py` imports (`:24-34`: config, errors, provider_errors, output, tokens, validation - **no capability import**) | the join is one-directional today: selection reads measured spend, enforcement never reconciles `_cost_by_model`/`spent` against provider-settled ledger totals |

### 2. The gap, stated as code

**Refusals are raised everywhere and recorded almost nowhere.** Of the six refusal families (phase ceiling, terminal reserve, Fireworks budget, Meta budget, task-scope allowance, mission pack), exactly one (`record_actual` inside `apply_policy`) writes a row - and that row carries none of the numbers that made it a refusal. A past run that stopped at its ceiling cannot be audited: there is no durable answer to "what was attempted, against what ceiling, with what overage".

**The two spend totals can drift and nothing detects it.** The governor's running totals (`spent`, `_cost_by_model`, `_cost_by_lane`, `_unknown_liability`, at `SpendGovernor.__init__`:165-183) and the ledger-settled totals (`measured_spend_by_model`) are summed by different code from different fields, and no check compares them. Billed-but-unusable responses (`$0` → unknown liability by design, `:390-404` doc at the `measured_spend_by_model` docstring), estimate/settle mismatches, and BYOK routing are all legitimate reasons the two differ - which is precisely why the difference must be recorded rather than assumed away.

### 3. The contract

Two event kinds in the existing `trace_v1` family, written through `harness/decision_trace.py::DecisionTrace.record`:112 and read with `read_trace_events`:190.

**`spend.refusal`** - one row per refusal actually raised, carrying: `ceiling_kind` (`phase_ceiling` | `terminal_reserve` | `fireworks_budget` | `meta_budget` | `scope_allowance` | `mission_pack`), `phase`, `label`/`model`, `lane`, `max_cost`, `spent`, `outstanding`, `ceiling`, `amount_attempted`, `overage` (`spent + outstanding + amount − ceiling`), and the same cost convention the one existing refusal row uses (`tracked_cost=0.0`, `reported_cost=amount`). The refusal vocabulary stays the governor's (see `harness/repo_summary.py`:172-179); the row repeats the numbers the message already states, so message and row are checkable against each other.

**`spend.reconcile`** - one row per reconcile point, carrying per canonical model: `governor_total` (from `_cost_by_model`), `ledger_total` (from `measured_spend_by_model`), `delta`, plus the `unknown_liability` remainder and its attribution. Reconcile is a read, not a correction: it never adjusts `spent`.

**The widened join, direction stated exactly.** Enforcement must consult measured spend where a canonical model has settled history - but the join arrives as **data**, through an explicit parameter on the preflight path, **without adding a `spend → capability` import** (`spend.py`'s import list at `:17-34` stays selector-free). Layering preserved: capability already depends on the ledger; spend depends on nothing but config/errors/tokens/validation.

### 4. Acceptance conditions a reviewer can falsify

1. **Every refusal family writes exactly one row.** Trigger each family in turn (phase ceiling, reserve eating, Fireworks budget, Meta budget, scope allowance, mission pack) and assert one `spend.refusal` row per trigger, with `ceiling_kind` equal to the family and the row's numbers equal to the exception message's numbers.
2. **Overage recomputes.** From the row alone, `spent + outstanding + amount_attempted − ceiling == overage` to the rounding the message uses.
3. **`$0` never refuses and never writes.** A zero-cost attempt passes `assert_spend_allowed` (`:121-124`) and produces zero refusal rows.
4. **Fail-closed is preserved.** Every refusal still raises; the row is evidence of the refusal, not a replacement for it - asserted by expecting the raise in the same test that asserts the row.
5. **Reconcile pins the drift.** After a scripted sequence - settled spends, one unknown-liability `$0`, one estimate/settle mismatch - a `spend.reconcile` row states per-model `governor_total`, `ledger_total`, `delta`, and the separately-attributed unknown liability; settled rows reconcile to the rounding `measured_spend_by_model` uses and every delta is explained by a remainder field, none by silence.
6. **The join points the measured way.** Where a model has settled history, the preflight refusal references the measured figure: a case whose catalog estimate says "fits" while measured spend says "refuses" refuses, and the row names `measured_spend`. This is the "widened" in the brief, and it is the only behaviour change the spec licenses.
7. **The existing `rejected` row keeps its shape and gains the ceiling fields.** `harness/apply_policy.py:68-78` keeps `status="rejected"`, `cost=0.0`, `tracked_cost=0.0`, `reported_cost=amount` byte-identical, and adds the `spend.refusal` fields of condition 1.
8. **Byte-identical without the path.** With the trace absent, every refusal message is unchanged, no new kind appears, and successful paths produce zero refusal rows.

### 5. What this does not license

No new sink, no new envelope, no new import into `spend.py`. No formula change to the dual envelope (`dual_budget_envelope`:70-106), no change to phase semantics, no change to who owns the numbers (`SpendGovernor` stays authoritative for the hard ceiling; the ledger stays the spend evidence). The reconcile never writes `spent`. **No completion credit**: #476 stays open and unmeasured until its own window runs; this filing is scope plus acceptance only.

**Gates, in order.** Product Jev (keyed `jev-1.14.0`, caller `sergeant-476-spec`, site `audit_admissibility`): verdict investigate, disposition proceed. Lucas Gate v2 (typed track, untracked receipt `gates-476spec.json`): pass.
