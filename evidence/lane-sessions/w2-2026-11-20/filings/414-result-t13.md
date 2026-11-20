## W2 verification at 6ea96c29 - #414 MCP runtime identity: PASS, 33 tools, `ledger_status` present, one read-only call OK

**Revision under test.** Working tree HEAD **`6ea96c29fed9373e8a591085ca3173d18c9edd1b`**, product code identical to `main` **`4618b5f9`** (operator-head diff is evidence-only, 0 product paths). **Hermetic**: real MCP stdio client in-process, no provider call, no key, no network.

### Run

`python evidence/lane-sessions/w2-2026-11-18/probe_mcp_main.py .` - one process, `initialize` -> `notifications/initialized` -> `tools/list` -> `tools/call ledger_status`; **exit 0**. The probe is unchanged from the `583120b4` receipt, so this result is comparable row for row.

| Acceptance item | Result |
|---|---|
| stdio initialize from a real client | **PASS** - `protocol 2025-06-18`, `serverInfo {"name": "harness", "version": "0.5.1"}` |
| exact tool count recorded (not the prior 30) | **PASS** - **33** tools |
| `ledger_status` present | **PASS** |
| one read-only tool call run and recorded | **PASS** - `call_isError: false`, payload keys `['chain', 'entries', 'verified']` |

Tool list (33, verbatim from the run): apply_edit, ask, continue_work, defer_work, dogfood, driver_health, driver_step, driver_verify, driver_vocabulary, economics_report, flush_run, generate_brief, host_provision_plan, host_provision_probe, issue_sort, jev_calibration, jev_freeze, jev_phase, ledger_status, log_judgment, lucas_gate_v2, mission_status, offer_work, panel_verify, participation_report, plan_and_execute, repo_cards, route_query, script_run, site_check, source_audit, spend_status, trust_status.

### Verdict

**PASS**, unchanged from `583120b4` and consistent with the earlier `9741066` / `ef7c297` / `966cf26` receipts. No regression from the landings between those heads. **Dependency tag: HERMETIC** - it does not park beside #415.

No product code changed; no new symptom to route, so this receipt adds no intake row. The issue stays open for its owner to close.
