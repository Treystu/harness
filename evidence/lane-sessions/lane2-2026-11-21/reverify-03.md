# LANE 2 — landing re-verification 03 + FED-UNIFICATION census (2026-11-21)

**Lane:** LANE 2 (verification only). No product code, no merges, no Lane 1
edits. Ledger STATUS unreachable (private repo); API writes blocked —
verbatim #295 text at the bottom for oversight execution. Filed + pushed the
same turn.

**Head state this turn:** `main` = `280ee3d4f99bf3d33645ddde21b243cebe0b191b`
(`git ls-remote`, unchanged since census 01). **No new landings since
`280ee3d`** — the re-verification below covers every Lane 1 claimed landing
through this turn (their turn-2 filings, read from
`standup/lane1-2026-11-21` at `edf8b2c`).

## 1. Landing re-verification at exact heads

Method: `git merge-base --is-ancestor` for landing ancestry, `git show
280ee3d4:<path>` for exact-head content (worktree `harness/` + `tests/` are
byte-identical to `280ee3d4`, verified by empty `git diff 280ee3d4 -- harness
tests`, so local execution runs the exact head), `git grep 280ee3d4` for the
call-site absence, `uv run pytest` for reproduced runs.

| Lane 1 claim (turn2-filings.md) | Independent re-read at `280ee3d4` | Verdict |
|---|---|---|
| #467 record: artifact on main by PR #626 (`3816a65`), ancestor of main | `3816a65` IS ancestor of main; `evidence/lane-sessions/w2-2026-11-18/467_live_calibration.json` present at `280ee3d4`, blob `6fdc1c4` (matches ruling 7023544526); content parses (28 cases) | **CORROBORATED** |
| #644 cured `campaign-trace-writer-unwired`: product entry injects writer (`flush_loop.py:1299`), default sink (`:642`), test `:385` drives the entry | `a4dd345` IS ancestor of main; `:1299` = `EventLedger(chosen_ledger, trace=campaign_trace(trace_path))`; `:642` = `def campaign_trace`, `:660` = `load_settings().ledger_path` default; `test_a_product_campaign_run_retains_its_events` at test line 385; Lane 1's intake cure row quotes these exact lines | **CORROBORATED** |
| Same, executed: 30/30 in `tests/test_decision_trace_469.py` | Reproduced: `uv run pytest tests/test_decision_trace_469.py -q` → **30 passed** (incl. the :385 test, stop-row, disable, fail-open cases) | **CORROBORATED (executed)** |
| #645/#422: resolver landed BUT no product call site — acceptance rightly withheld | `git grep 280ee3d4 citation_resolver/CitationResolver/DoiResolver` → sole importer is `tests/test_citation_resolver.py:9`; #645 message itself says "no call site is added"; reproduced `pytest -k citation` → **66 passed, 7552 deselected** | **CORROBORATED as a negative finding** |
| #413 host-side block (no listener :8791, no driver-core, no DISPLAY) | Lane 1-seat environment condition; this host is a different machine — not reproducible or refutable from here | **NOT EVIDENCED here (named, not doubted)** |
| #646 count correction waits on live census | No claim filed; wait is as-directed by the register's own two-method rule | **NO CLAIM — nothing to verify** |

No new pass/fail beyond corroboration; scoring-02 stands unchanged.

## 2. FED-UNIFICATION served-UI census: PENDING (blocking surface named)

Result: **no census run — surfaces not reachable from any record this seat
can read.** Searched: full repo (`FED-UNIFICATION|fed.unification|
fed_unification` hits only this lane's own prior filings), `site/` tree
(`data/public/worker`, no FED refs), `docs/issue-plans` (one unrelated
"fed" hit in `276.md`). The #295 tail (where surface URLs would live) is
unreadable from here (core API quota 0; HTML extractor truncates bodies);
no oversight mirror has relayed surface coordinates. **Blocking surface:**
the FED-UNIFICATION served-UI URLs/coordinates themselves — needed from
oversight relay or from the surfaces coming up with published URLs. The
census runs the turn they arrive.

## 3. Gates, in order — recorded exactly as returned, not normalized

Verdict artifact text (exact — sha reproducibility):

> LANE 2 landing re-verification 03 (2026-11-21): main 280ee3d4 unchanged,
> no new landings since census. Re-verified Lane 1 turn-2 claims at exact
> head 280ee3d4: (1) #467 artifact present (467_live_calibration.json, blob
> 6fdc1c4), #626 (3816a65) ancestor of main, CORROBORATED; (2) #644 wiring
> present (flush_loop.py:1299, :642, :660) with driving test at :385, #644
> (a4dd345) ancestor of main, executed 30/30 pass on a head-identical tree,
> CORROBORATED; (3) #422 has no product call site
> (only tests/test_citation_resolver.py imports harness.citation_resolver),
> 66 citation tests pass, CORROBORATED as a negative finding, acceptance
> rightly withheld; (4) #413 host block and #646 census wait are Lane 1-seat
> conditions, NOT EVIDENCED here. No new pass/fail beyond corroboration;
> scoring-02 stands. FED-UNIFICATION served-UI census: PENDING, no surface
> coordinates in any reachable record.

**Lucas Gate v2 (typed track): PASS** — deterministic runner, no model
called. Applicable `["5"]` (9.5), ten others N/A with recorded reasons,
bias floors all met, `failing_categories: []`,
`failing_bias_checks: []`,
`artifact_sha256: 6864a511dafeb3dc01b0b47eb0d1493aebd2caf4f3fdc10f35dbd7292e42222e`.

**Product Jev: UNRUNNABLE from this seat — exact output, not smoothed:**

```
keyed: False | governor: False | ledger: True
BLOCKER: keyed Jev needs key + shared spend governor + ledger
```

Oversight may re-run Jev over the artifact text above from authenticated tools.

## 4. INTENDED #295 POST — verbatim, for oversight execution (API blocked)

> LANE 2 re-verify 03: main still 280ee3d4 — no new landings. Lane 1 turn-2
> claims re-verified at exact head: #467 artifact present (blob 6fdc1c4),
> #626 ancestor — CORROBORATED; #644 wiring present (:1299/:642/:660, test
> :385), #644 ancestor, reproduced 30/30 — CORROBORATED (executed); #422 no
> product call site (only its own test imports it), 66 citation tests pass —
> CORROBORATED as negative finding, acceptance rightly withheld; #413/#646
> are Lane-1-seat conditions — NOT EVIDENCED here. Scoring-02 unchanged.
> FED-UNIFICATION served-UI census: PENDING — no surface coordinates in any
> reachable record (repo/site/ search empty; #295 tail unreadable); runs the
> turn URLs arrive. Gates: Lucas v2 PASS (sha 6864a511…); product Jev BLOCKED
> (no key/governor in cloud). Full receipt:
> `evidence/lane-sessions/lane2-2026-11-21/reverify-03.md` (branch
> `freebuff/dd7daf0d70253bde4832d672`).
