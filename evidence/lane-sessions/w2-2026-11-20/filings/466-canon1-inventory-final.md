## CANON-1 SUPPORT - brief-to-mechanism inventory, ten brief numbers to nine mechanisms, and the "eight mechanisms" reconciled (W2, steering 6996071450 item 2)

Inventory only: **no brief, bar, order or mechanism-rule change**, and no restatement of any mechanism's rules. Mechanism rules live at #466; this filing reports which brief names which mechanism and how the denominator figures relate. Evidence basis: my verified map (7003243552), the sergeant's map of record (7007760683, landed in the register by PR #632 / `d2e724ba`), each brief's own filed body, and the ten issues' live states read this turn at `origin/main` `fb27ee89`.

### 1. The map - one row per brief ID, mechanism cited not described

| Brief | Mechanism named in the brief (site) | Frozen-order slot | Issue state | Measurement state |
|---|---|---|---|---|
| #467 | `jev_packs.py::compose_decision_verdict`, pack `decision-gate-v3` | Champion LAST | OPEN | measured at `699f677b`, 27 receipted rows (6991530885); **count provisional until #626 is on main** |
| #468 | `jev_assessment.py::assess` + disposition ladder | Champion 3rd | OPEN | frozen-slot verdict filed; W468 admissible, blocked on #628 (verdict `468-admissibility-verdict.md`) |
| #469 | `flush_loop.py` stop bar + `GapRegister` + `OscillationBreaker` | Champion 5th | OPEN | frozen-slot verdict filed; W469 admissible, blocked on an unwired producer (verdict `469-admissibility-verdict.md`) |
| #470 | `sliding_scale.py::classify_task_tier` | not a W2 slot | **CLOSED 2026-11-14** | no-change measurement published (HAR-SAMS Cluster A); documented other role |
| #471 | `escalation.py::confidence_to_start_rung` | Champion 6th | OPEN | frozen-slot verdict filed (6995702503) |
| #472 | `capability.py` score + `composite_reliability` + `order_pool` | Champion 7th | OPEN | frozen-slot verdict filed (6995703696) |
| #473 | `dynamic_allocation.py::rank_models_dynamically` + `Router._rotation_ordered` | Champion 8th | OPEN | frozen-slot verdict filed (6995704879) |
| #474 | `convergence.py` panel tally | Champion 2nd | OPEN | **measurement published and complete**: 276/276 fidelity, champion stands (6973565344) |
| #475 | three components, one decision: panel 429 retries, `jev.py::CircuitBreakers`, chat reasoning-param retry | Champion 4th | OPEN | frozen-slot verdict filed (6995705970) |
| #476 | `spend.py` dual envelope + `config.py` caps + tier ceilings + `token_budget.py` | Champion 1st | OPEN | frozen-slot verdict filed (6995707033) |

### 2. The three figures

- **Ten - brief numbers** `#467`-`#476`. Reproducible: ten rows above, all ten in the tracker's Component issues section.
- **Nine - live brief obligations**: the register's W2 table carries nine rows (#476, #474, #468, #475, #469, #471, #472, #473, #467); #470 is closed. Reproducible from the register and from issue state (nine OPEN, one CLOSED, read live this turn).
- **Eight - the hinge is #474.** This is the correction I owe: my earlier filing said no counting rule yields eight. On re-reading the record, exactly one does, and it is precise: nine live obligations **minus #474, whose Champion measurement is already published and complete** (6973565344: fidelity 276/276, champion stands, acceptance not adjudicable). Counting #474 as a live obligation gives nine; counting it as discharged by its published measurement gives eight. The count therefore turns on **#474**, not on #467 - #467's count is explicitly provisional, so it cannot be the subtracted row.

That rule is a count of *unsettled* obligations (eight: #467 provisional, #468, #469, #471, #472, #473, #475, #476), not of live ones. It is why "eight mechanisms" is stale as a denominator: it silently drops a row that is still open.

**The stable statement, unchanged and consistent with the map of record:** nine live champion-brief obligations across ten brief numbers, one closed (#470); of those nine, eight still carry unsettled measurement work and one (#474) is measured and complete but not yet closed.

**Why the figures drift at all:** a brief is not a mechanism. #475 names three mechanisms and #469 three components under one stop decision, so any denominator equating mechanisms with briefs will drift again. This inventory counts briefs and names mechanisms separately.

### 3. What this filing does not do

It changes no brief, bar, order or classification. It restates no mechanism's rules - every mechanism cell is a module site citation, and the rules remain at #466. It closes no issue; #474's closure is the owner's act, and this inventory only records that its measurement is already published. It takes no completion credit.

**Gates, in order.** Product Jev (keyed `jev-1.14.0`, caller `w2-champion-audit`, site `audit_admissibility`): verdict and disposition in `gates-canon1-final.json`, reported as returned. Lucas Gate v2 (typed track): status in the same receipt.
