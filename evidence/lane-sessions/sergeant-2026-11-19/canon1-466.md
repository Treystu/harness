## CANON-1 MAP OF RECORD - verified brief-to-mechanism map (sergeant filing, 2026-11-19)

Filed as the sergeant's own cure of steering 6996071450 item 2. It records W2's verified evidence (this issue, CANON-1 SUPPORT) as the map of record and settles the denominator conflict. Inventory only: no frozen brief, bar, order or classification changes here, and no completion credit is taken or removed by it.

Read basis: every brief body at `main` `699f677b` plus the register rows at register commit `bce8a04`; live state re-read at `main` `dbb54a7f`, where the register reference landed as PR #632 (`d2e724ba`).

### Map - one row per brief ID

| Brief | Mechanism (module site) | Order slot | Live obligation |
|---|---|---|---|
| #476 | `spend.py` dual envelope + `config.py` caps + tier ceilings + `token_budget.py` | Champion 1st | yes - unblocker: record each ceiling refusal with the refused run's outcome, widen the measured-spend join |
| #474 | `convergence.py` panel tally | Champion 2nd | yes - measured, no change (6973565344) |
| #468 | `jev_assessment.py::assess` + disposition ladder | Champion 3rd | yes - unblocker: persist five aspect distributions + disposition (W1 draft PR #628, `7cf5ef8d`) |
| #475 | three components, one decision: panel 429 retries, `jev.py::CircuitBreakers`, chat reasoning-param retry | Champion 4th | yes - unblocker: record per-attempt `http_status` + attempt timestamps |
| #469 | `flush_loop.py` stop bar + `GapRegister` + `OscillationBreaker` | Champion 5th | yes - unblocker: retain campaign ledgers (carried by W1 PR #627, `43891d83`) |
| #471 | `escalation.py::confidence_to_start_rung` | Champion 6th | yes - unblocker: persist start rung, rung attempted, realized pass (W1 draft PR #630, `0c591c87`) |
| #472 | `capability.py` score + `composite_reliability` + `order_pool` | Champion 7th | yes - unblocker: persist candidate pool + ordered attempt sequence per routed call |
| #473 | `dynamic_allocation.py::rank_models_dynamically` + `Router._rotation_ordered` | Champion 8th | yes - unblocker: persist router health + ordering at each rotation |
| #467 | `jev_packs.py::compose_decision_verdict`, pack `decision-gate-v3` | Champion LAST | yes - measured at `699f677b` (27 receipted rows, 6991530885); count provisional until W2 PR #626 is on main |
| #470 | `sliding_scale.py::classify_task_tier` | not a W2 slot | **no** - documented other role: CLOSED 2026-11-14 on a published no-change measurement (HAR-SAMS Cluster A); component of program history, not a live obligation |

### The three figures, reconciled and settled

- **Ten** - brief numbers `#467`-`#476`, every one listed in this tracker's Component issues section. Reproducible.
- **Nine** - live champion-brief obligations: the nine rows above with a live obligation. Reproducible from the register's W2 table.
- **Eight** - not reproducible from any current record (filed = 10; live = 9; distinct top-level decision sites = 10; closed = 1). Recorded here as **stale**, so no future row or filing may cite it as a denominator.

**The stable statement, which supersedes all three loose figures: nine live champion-brief obligations across ten brief numbers, one closed (#470).**

The reason the loose figures drifted is recorded so it cannot recur: a brief is not a mechanism. #475 names three mechanisms and #469 names three components under one stop decision, so any denominator equating mechanisms with briefs drifts. This map counts briefs and names mechanisms separately, which is why it is the one that reconciles.

### Register reference

`docs/jev-roadmap.md` now carries the citation: the register section holds a "Champion brief-to-mechanism map (CANON-1)" subsection pointing at this comment, landed as PR #632 (`d2e724ba`) at 2026-11-19T11:35:27Z after CircleCI 16/16 incl audit at exact head `1dbad46`.

### Gates, in order

Product Jev (keyed `jev-1.14.0`, caller `sergeant-canon1`, site `audit_admissibility`): verdict `investigate`, disposition `proceed` - a non-proceed that authorizes no content change, which is what an inventory filing is. Lucas Gate v2 (typed track, artifact `9c91777c844780c574bc9229ba51f48e7004c6e1e74ecaf9c3bd14c702922585`, untracked receipt `gates-canon1.json`): `pass`. Nothing was pushed to any writer branch; the gate helpers stay untracked.
