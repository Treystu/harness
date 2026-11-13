REPORT-JOB DISPOSITION + TIER-SNAPSHOT CURE PROPOSAL (owner steering 2026-11-02, item 2) - 2026-11-03

Disposition: root-caused, and it is the SAME defect as #446. One cure carries both. The cure is decidable and is proposed below with its blast radius; it is not owner-reserved prose.

ROOT CAUSE (evidence, reproduced on main 0780ea74's tree today)
- .github/workflows/rankings.yml, job "report", step "Rankings candidate report (no probes)" runs `harness economics --check-fresh --out rankings/tier-snapshot-freshness.json`. That subcommand exits 2 whenever packs/tiers.snapshot.json is outside its window (harness/cli.py:1141-1146). The step's exit status fails the job before the rankings call and before the artifact upload, so the weekly evidence artifact is absent whenever the snapshot is stale.
- Local repro, same tree: `harness economics --check-fresh --json` -> {"ok": false, "fresh": false, "captured_at": "2026-10-18T00:00:00Z", "age_days": 16.142, "max_age_days": 14.0, "warning": "tiers.snapshot.json is 16.1 days old (exceeds max_age_days=14); refresh via `harness economics --report`."}, exit 2.
- #446 is the same path from the other side: tests/test_economics_cli.py::EconomicsReportAndExportTests::test_check_fresh_emits_tier_snapshot_freshness calls the same CLI with --check-fresh and asserts payload["ok"], so the suite errors (SystemExit: 2 at cli.py:1145) once the committed artifact ages out. Reproduced locally with the repo venv: 1 failed in 0.56s, SystemExit: 2.
- Timeline fits: captured 2026-10-18 + 14 days = expiry 2026-11-01T00:00Z, which is why PRs merged before Oct 31 were green and every head after that is red.

WHY IT RECURS: THE GATE'S ADVERTISED CURE DOES NOT EXIST
- The warning says "refresh via `harness economics --report`". The --report branch (cli.py:1148 onward) computes freshness and emits a payload; it writes no snapshot. `routing_table.generate_tier_snapshot` (routing_table.py:173) has zero production callers - only tests/test_routing_table.py. So nothing in the repo can refresh packs/tiers.snapshot.json, and the gate can only ever go red.
- Drift against canon: docs/jev-roadmap.md DF-EV-5 says .github/workflows/rankings.yml "commits docs/MODEL_RANKINGS.md and packs/tiers.snapshot.json with an explicit delivery check". The workflow has no commit step and no snapshot write. The delivery check was lost; the artifact is only uploaded.

WHAT THE SNAPSHOT IS AND WHAT CONSUMES IT
- routing_table.load_tier_snapshot reads it at import and supplies TIER_MODELS, TASK_CLASS_TIERS, classify_model_tier and get_tier_route, which feed harness economics, ledger analytics, site_export, the MCP economics tool and the server economics surface.
- Freshness gates only the economics --check-fresh/--report path (exit 2). Runtime routing never refuses: load_tier_snapshot falls back to the bootstrap literal on any load error. A stale snapshot therefore changes no runtime routing decision; it only makes the data-freshness check and its dependents red.

DECIDABLE PROPOSAL (recommended cure)
1. Add the missing refresh path: `harness economics --refresh-snapshot`. It must (a) require a governor catalog read (GET /models, $0.00, no chat call), (b) refuse if any tier id is absent from the live catalog - no silent drop, same contract as the check-shipped path, (c) rebuild price_table from the catalog's per-token prices, (d) stamp captured_at=now and keep max_age_days=14, (e) write atomically and refuse on any catalog gap.
2. Tests with a catalog double: refresh preserves tier membership when the catalog agrees, drops nothing (refuses) when it disagrees, stamps a fresh captured_at that check_tier_snapshot_freshness accepts at a pinned now, and refuses without a key.
3. Restore the delivery loop in .github/workflows/rankings.yml: after the report, run the refresh and commit docs/MODEL_RANKINGS.md + packs/tiers.snapshot.json through a PR (the DF-EV-5 contract), so the artifact cannot silently age out again.
4. Land the refreshed artifact in the same PR that adds the command. That single PR greens #446's test, the audit leg's D12 battery and this workflow.

WHAT REGENERATION REWRITES, AND WHAT IT CANNOT CHANGE
- Rewrites: captured_at; price_table values to the live catalog's; tier membership only to ids the catalog actually offers. The existing generate_tier_snapshot copies tiers/task_classes/price_table from the current snapshot, so a timestamp-only call would change nothing else - but it would assert price currency it never checked, which is why proposal step 1 validates against the catalog instead of just bumping the stamp.
- Cannot change: routing code, pools, escalation ladders, gates, thresholds or any test contract. The artifact is data; the diff is a single reviewable JSON file.

HOW ITS EFFECT IS VERIFIED
- `harness economics --check-fresh --json` -> ok true, age_days < 1.
- The #446 test passes unchanged, and ``python -m pytest tests/test_economics_cli.py -q`` is green.
- The audit job's D12 battery exits 0 (it exits 1 on any suite error), so the audit leg is green.
- The rankings workflow produces and uploads its artifact on a run, and the commit step's PR shows only the expected JSON keys changed.

DETERMINISTIC HALF THAT CAN LAND NOW (no key needed)
#446's own text allows "cure it, or re-scope the test with the reason recorded here". The test's contract is wall-clock-dependent by construction: it asserts the shipped data is fresh rather than that the CLI emits freshness. Splitting the contracts - hermetic test against a fixture snapshot with a pinned now, plus a deterministic check that the shipped snapshot parses and carries a valid ISO captured_at - keeps the CLI-wiring assertion intact while moving the data-currency assertion to the scheduled workflow, which is exactly where it belongs. That half is implementable and verifiable in this session; the artifact refresh itself is the keyed step.

BLOCKER ON THE KEYED HALF: OPENROUTER_API_KEY is absent from this session (env unset; ~/.config/harness/config.json carries no key field). The lane can implement and test the command offline, but the artifact refresh and the workflow's commit step need a keyed run - which the restored weekly job performs itself once it lands.

Gate: Lucas Gate v2 never-rule check on this text: clean - no data rewritten, no merge, no workflow change executed. Jev decision gate (jev-latest): NOT RUN, authentication blocker as recorded; no Jev pass is claimed.
