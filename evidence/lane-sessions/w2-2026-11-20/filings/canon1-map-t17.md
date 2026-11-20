## CANON-1 SUPPORT — ten brief numbers against nine named mechanisms, with the "eight mechanisms" figure reconciled (W2, steering 6996071450 item 2)

**Inventory only.** No brief, bar, order, frozen program or classification is
changed here; no completion credit is taken; no window is scheduled or re-ruled.
Mechanism **rules** live at #466 and are cited by number only — every mechanism
cell below is a module-site citation plus the brief's own words, never a
restatement of how the mechanism works.

**Revision read at:** `origin/main`
`51e208a542b7dc28a11ce120d01113bfd44b2585` (this turn). Every mechanism site
named below was confirmed to resolve at that SHA by `git grep -l <symbol>
51e208a5 -- "harness/*.py"` — the citation is not inherited from an earlier
turn's read.

### 1. One row per brief number — the brief's own governing text, quoted

Each quotation is the brief's **Current mechanism** opening clause, i.e. the
sentence that names the code that its frozen program replays. The **Decision**
line is quoted with it because that is what ties the brief to that code rather
than to its neighbours.

| Brief | Governing mechanism (site verified at `51e208a5`) | The brief's own words | Decision, as the brief states it |
|---|---|---|---|
| **#467** | `harness/jev_packs.py::compose_decision_verdict`, pack `decision-gate-v3` | "`jev_packs.py::compose_decision_verdict` (pack `decision-gate-v3`) composes a verdict in fixed rule order" | "Whether a proposed action proceeds, is revised, is investigated, or escalates to the operator." |
| **#468** | `harness/jev_assessment.py::assess` (+ its disposition ladder) | "`jev_assessment.py::assess` judges five fixed aspects … over three bands" | "A lane-workflow disposition: pass, pass-with-note, investigate, block, or stop." |
| **#469** | `harness/flush_loop.py` stop bar, with `GapRegister` and `OscillationBreaker` | "`flush_loop.py` stops a campaign only at `STOP_COMBINED = 95.0` … and a clean-expansion streak of `CLEAN_EXPANSION_STREAK = 2`" | "Whether an audit/flush campaign stops, continues expanding, parks one aspect on a missing record, or escalates an oscillation." |
| **#470** | `harness/sliding_scale.py::classify_task_tier` | "`sliding_scale.py::classify_task_tier` starts at score 0.20 and adds asserted increments" | "Which capability tier (and therefore which models and spend) a task is routed to before any work happens." |
| **#471** | `harness/escalation.py::confidence_to_start_rung` | "`escalation.py::confidence_to_start_rung` maps Jev confidence … to a ladder start" | "After a failure: retry cheap, step up one rung, jump near the top, or spend nothing (abstain)." |
| **#472** | `harness/capability.py` — `capability_score`, `composite_reliability`, `order_pool` | "`capability.py` scores each model by `capability_score` … then `composite_reliability` … `order_pool` sorts free tier by reliability descending" | "The order in which pool models are tried for panel, apply, and judge lanes." |
| **#473** | `harness/dynamic_allocation.py::rank_models_dynamically` + `harness/router.py::Router._rotation_ordered` | "`dynamic_allocation.py::rank_models_dynamically` scores each model from 100.0 … `router.py::Router._rotation_ordered` pins `pool[0]` first unconditionally" | "Rotation order when the router walks a pool after failures." |
| **#474** | `harness/convergence.py::tally_convergence` | "`convergence.py::tally_convergence` counts per-claim votes from panelists' structured JSON" | "Whether a panel's verdict is coverage-complete and converged enough to act on, or must defer." |
| **#475** | three sites: `harness/convergence.py` constants used by `harness/panel.py`; `harness/jev.py::CircuitBreakers`; the `harness/chat.py` reasoning-param retry | "Two independent mechanisms. (a) Panel 429 handling … (b) Jev circuit breaker … a third, separate retry rule." | "On a transient failure: retry in place (and how long to wait), rotate to another model, or stop calling a failing endpoint for a cooldown window." |
| **#476** | `harness/config.py` caps, `harness/spend.py` dual envelope, tier ceilings from `harness/dynamic_allocation.py`, `harness/token_budget.py::TokenBudget` | "Hard caps in `config.py` … `spend.py` enforces a dual envelope … Tier ceilings … `TokenBudget.for_model` instead derives the allowance as context window × `safe_ratio`" | "How much money and how many tokens each call, task, tier, and phase may commit before dispatch." |

Each pairing is the brief's own sentence naming its own module, not an
inference from issue title or from a neighbour's comparator line. #473 is the
only row that names a second site in its own first clause (`Router._rotation_ordered`),
and it does so because its decision is the rotation order itself.

### 2. The nine named mechanisms, stated as nine

The nine are the nine mechanism cells the register's W2 table carries — briefs
#467, #468, #469, #471, #472, #473, #474, #475, #476 — each naming one decision
and its own code:

1. decision-gate composition — #467
2. assessment band aggregation — #468
3. flush-loop stop bar and oscillation breaker — #469
4. escalation rung mapping — #471
5. capability pool ordering — #472
6. router dynamic ranking — #473
7. panel convergence tally — #474
8. failure retry and circuit breaking — #475
9. spend ceilings, terminal reserve and sizing — #476

**#470 is the tenth brief number and the reason "ten" and "nine" coexist.** It
is closed (2026-11-14), its mechanism (`sliding_scale.py::classify_task_tier`)
is live code but is not a live Champion obligation: it was discharged as a
no-change measurement under the HAR-SAMS Cluster A lane and is recorded in the
map of record as a documented other role. Nothing in #470's row is reopened by
this inventory, and its closure is not disputed here.

### 3. Why "eight mechanisms" also appears — reconciled, not left as drift

The figure is a count of **unsettled obligations**, and the record supports it
by exactly one rule:

- **nine live mechanism obligations minus #474 = eight.** #474's Champion
  measurement is published and complete (`6973565344`: fidelity 276/276,
  champion stands), so it is live but no longer *unsettled*. Removing it from
  the unsettled set leaves eight: #467 (count explicitly provisional), #468,
  #469, #471, #472, #473, #475, #476. That was the state when the figure was
  written, and my earlier inventory (`7010350007`, section 2) verified it was the
  only rule that produced eight.
- **What moved since, stated so the coincidence cannot be misread.** Main
  `51e208a5` landed #630, and **#471 closed at 2026-11-19T22:23:10Z**. At today's
  head the live set is therefore **eight briefs** (#467, #468, #469, #472, #473,
  #474, #475, #476) and the unsettled set is **seven**. "Eight" therefore now
  happens to equal the live count as well, by a different rule from the one that
  produced it on the record. The two must not be conflated: the recorded "eight"
  is *unsettled at the freeze*, while today's eight is *live after #471's
  closure*.
- **The stable statement.** Ten brief numbers; nine named mechanisms at the
  freeze; #470 closed with a documented other role; of the nine, eight were
  unsettled when the figure was written; at `51e208a5`, eight briefs remain live
  and seven of those carry unsettled measurement work.

### 4. Where a row does not pair one-to-one — stated as a gap, not inferred

**GAP-CANON-1-475 (mapping granularity).** #475's frozen text opens "Two
independent mechanisms" and adds "a third, separate retry rule". Its governing
mechanism therefore **cannot** be established as a single mechanism from the
frozen text as written: the frozen clause deliberately bundles three code sites
under one decision. I record the pairing as **1 brief → 3 mechanism components**,
quote the brief's own sentence, and infer nothing further — in particular I do
not nominate one of the three as "the" governing mechanism, because the brief
does not.

**Same shape, recorded but not a gap.** #469 (three components under one stop
decision), #472 (three functions in one ordering decision), #473 (two sites in
one rotation decision), #476 (four sites in one sizing decision) each name a
component group whose members are all named in the brief's own first clause and
all resolve at the head. These pair 1 brief → N components with **one** decision
each, so their governing mechanism is establishable; only #475's text withholds a
single one.

**No row is left unestablished.** For every brief above, the module site named
in its own "Current mechanism" clause exists at `51e208a5`, so no pairing here
rests on a site that has moved or vanished.

### 5. What this filing is not

It is not an admissibility re-ruling (#468/#469 rows stand as filed,
`7019523023` / `7019523607`), not a completion claim for any brief, not a
register edit (the register's own rows belong to its owner), and not a product
change. It counts briefs and names mechanisms; it never equates the two.

Gates on this filing, in fence order: product Jev (keyed `jev-1.14.0`, caller
`w2-champion-audit`, site `audit_admissibility`) returned verdict
**`investigate`** on a non-change inventory filing, destructive well below the
0.15 band; Lucas Gate v2 (typed track) returned **`status: pass`**. Both recorded
as returned in `gates-turn17.json`.
