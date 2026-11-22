# Found in use

Symptom-keyed index of findings observed while the Harness was actually being
used. This file routes; it does not own a mechanism's rules and it does not fix
anything. Each row points at the owner issue that carries the evidence. The
Champion Audit register home is #466.

Add a row when a finding is observed in use and dedupe first against the open
set. Never close an owner issue from this file; closure happens on the owner.

| Symptom key | First seen | Observed at | Owner | Disposition |
|---|---|---|---|---|
| `citation-no-identity-resolution` | 2026-10-27 | `9741066` | #422 | **cured 2026-11-22** — capability gap closed at the report face: `lint-claims` now resolves each declared DOI through `RegistryResolver` (`harness/citation_resolver.py:default_resolver`) via `audit_report_citations` (`harness/cli.py:_cmd_lint_claims`), and a fabricated DOI exits 2 with `doi_not_found`. A manifest that declares no `citations` section is unchanged, so the report author's obligation to declare the bibliography is what still gates the label (`tests/test_lint_claims_citations_422.py`) |
| `billed-judgment-no-ledger-row` | 2026-11-17 | `9741066` | #588 | open — 5 billed chat turns, 0 `jev_eval` rows in the window; PR #608 parked red |
| `driver-decision-tier-unkeyed` | 2026-11-18 | `9741066` | #413 | open — DOM read agrees 2/2, then `decision_not_usable` without `DRIVER_JEV_API_KEY` |
| `panel-outcome-labels-absent` | 2026-11-18 | `9741066` | #474 | open — 42 defer-to-converge flips cannot be scored for false-convergence |
| `audit-traces-not-persisted` | 2026-11-18 | `9741066` | #468, #469, #471, #472, #473, #475, #476 | open — each frozen Champion Audit program names a trace the system does not record |
| `auth-connect-duplicate-label` | 2026-11-18 | `9741066` | #412 | open — two controls labelled "Connect browser"; the one in `auth-pair-panel` (`display:none`) is still in the accessible tree and clicking it issues no request and shows no feedback |
| `bridge-hand-no-process-entry` | 2026-11-19 | `a7ca742` | #480 | open — BR2's hand has no process entry point: `python -m driver_core.capture_hand --root <dir> --status` exits 0 and does nothing (no `main()`, no output); cure in #625 |
| `bridge-battery-ledger-not-isolated` | 2026-11-19 | `a7ca742` | #480 | open — a second run on a named `--root` reads the first run's answers as its own (`met 1/6`, exit 1), and a failed live probe leaves a pending request the later probes can answer; cure in #625 |
| `assessment-gate-writes-nothing` | 2026-11-18 | `699f677` | #468 | open - `harness/jev_assessment.py` has no persistence path (its only match for a write pattern is an in-memory list append), so no assessment's aspect distributions can ever be replayed and the Champion Audit comparison has no corpus |
| `flush-campaign-ledgers-uncommitted` | 2026-11-18 | `699f677` | #469 | open - `harness flush --campaign` writes `<campaign>.events.jsonl` beside the campaign file and nothing retains or archives it, so no campaign pass history accumulates for the frozen replay |
| `spend-key-remaining-stale` | 2026-11-18 | `9741066` | #415 | open — the serve prints `key_remaining=$1.500000` on three consecutive key reads while every billed call in that run is refused with provider HTTP 402 `spend limit exhausted`; the surface reports headroom it does not have |
| `gate-labels-live-drift` | 2026-11-18 | `9741066` | #467 | open — the shipped 28-case decision-gate label set scores 14/28 exact against live Jev answers (false-proceeds 0); labels were authored 2026-09-27 and live `advances_goal` lands 0.84-0.99 where the set authors 0.95-0.98 |
| `freelane-reasoning-in-answer` | 2026-11-20 | `583120b4` | #415 | open — high: the answer field carries the free-lane model's scratchpad ("Defer message: ...", "Final decision: ...") with the required `HARNESS_DEFER:` line only at the end, so a user reads reasoning as the answer (run `add821eb7c09`) |
| `web-records-before-plan` | 2026-11-20 | `583120b4` | #415, #342 | open — high: five web records (fetch/search/browser) for an MCP-specification question, zero on-query, produced before any approved query-bound plan record (run `add821eb7c09`) |
| `citation-gate-unwired` | 2026-11-20 | `583120b4` | #422 | **cured 2026-11-22** — medium: `harness/citation_verify.py` had no call site outside itself. `harness/citation_resolver.py:audit_report_citations` is the product entry and `harness/cli.py:_cmd_lint_claims` calls it, supplying `default_resolver()` (Crossref) unless `--no-network` is passed; the report face exits 2 unless `audit_citations` returns `citation_verified`. Live acceptance on the real registry: `evidence/lane-sessions/lane1-2026-11-22/citation-live-acceptance.json` (true DOI verifies, wrong title contradicted, fabricated DOI refused). Hermetic pin: `tests/test_lint_claims_citations_422.py` |
| `ui-smoke-job-intermittent` | 2026-11-19 | `4c76ca09` | #295 | open - high: `ci/circleci: ui-playwright-smoke` fails and then passes on a byte-identical `tests/ui` tree (`git diff` is empty between `966de1dd`, `6c90298b`, `410a146c` and `4c76ca09`): failed at `966de1dd` and `4c76ca09`, passed at `6c90298b` and `410a146c`. The same 11 journeys pass 11/11 in 6.3s locally against that tree (`npm ci` + `npx playwright install chromium` + `npm test`), so the job's own browser/system install and served-fixture startup are the variable. Because `ci/circleci: audit` requires this job, one flake withholds the audit context and the pipeline reads 15/16 with audit absent rather than failed |

| `campaign-trace-writer-unwired` | 2026-11-20 | `17906e2c` | #469 | open - high: `harness/flush_loop.py:392-396` forwards each campaign event to `DecisionTrace.campaign_event` only when a writer is injected, and no product call site injects one (`flush_loop.py:1261-1262`, `:1050`, `:1056`); the writer is green only because `tests/test_decision_trace_469.py:235-236` constructs it by hand, so #627's campaign retention is inert in use |

| `bridge-battery-live-probe-clock` | 2026-11-19 | `d916a7bb` | #295 | open - medium: `tests/test_driver_core/test_bridge_battery.py::LiveProbeTests::test_a_live_frame_outside_the_window_is_a_failure` asserts the battery reports `failed` for a capture outside a 0s window with the clock advanced 30s, but it reports `met`; reproduces 3/3 in isolation on `d916a7bb`, and that test file plus `harness/driver_core` are byte-identical to `origin/main`, so the defect is main-side and not any lane diff |

## Transfer entry (#451)

The Harness-in-use filings previously tracked only as GitHub issues are
transferred into this file as their symptom-keyed rows. The disposition record
is `6971091862` on #451. #451 closes as transferred once this file is on `main`;
it is not a duplicate of any row above.
