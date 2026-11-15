# Cloud burndown census — 2026-11-15 (82 open issues)

**Why this file exists.** The cloud lane has no GitHub API credential: REST is
rate-limited to 60 requests/hour for an unauthenticated client and this VM's
address has already spent that budget, so no issue list, PR body or comment can
be read or written from here. The census below was taken from the public issue
list HTML (`https://github.com/Treystu/harness/issues?q=is%3Aissue+is%3Aopen`,
five pages, parsed for `number`/`title`), which needs no credential and returns
the same 82 rows the last count named. A census that cannot be re-read the same
way tomorrow is not a census, so the method is recorded with it.

**In flight at census time.** PR #547 (`freebuff/harness-assist-lane-burndown-mission`,
head `c048c83`) carries the never-defer bundle for #538, #539, #540, #541, #542,
#544. #543's cure is already on `main` (#545). Those six issues stay open until
#547 lands; they are not independent work items tonight.

**Disposition vocabulary.**

| Tag | Meaning |
| --- | --- |
| IN-FLIGHT | carried by PR #547; do not open a second cure |
| HERMETIC-NOW | cure is code plus tests inside this repository; no live key, no rail read, no GUI needed |
| NEEDS-LIVE | the acceptance criterion is a live provider, browser, GUI or installed-client run this lane cannot perform |
| NEEDS-RULING | an operator decision (defer, scope, spend) must precede any code |
| TRACKER | an index issue; closes when its children close |

## Ordered next slice (hermetic, smallest first)

1. #428 `[economics] Reject negative endpoint override and cache prices` —
   input validation with a named refusal; the suite can drive it directly.
2. #425 `[driver-core] Refuse append when an existing audit chain is invalid` —
   the chain verifier already exists; the append seam must consult it.
3. #429 `[audit] Refuse or recover truncated JEV judgment state before append` —
   same seam as #425 for the JEV judgment record.
4. #427 `[mission] Surface malformed receipt and Jev-evaluation records` —
   the malformed records are currently dropped silently.
5. #430 `[lifecycle] Stop repeated retries after validated restart or consent refusal`.
6. #346 `[planning] Exclude completed planning calls from the remaining execution allowance`.
7. #344 `[lifecycle] Bind resumed web context to the current request and retrieval decision`.
8. #343 `[web] Reject unrelated hits individually instead of accepting a mixed target-site result batch`.
9. #335 `[mcp][LOW] tool annotations inaccurate`.
10. #329 `[cli] polish: shared --out/--quiet/--events/--no-color flags`.
11. #419 `[desktop] Separate local server health from backend and request status`.
12. #424 `[docs] Align System One feature claims with shipped status`.

Every item above is code, tests and docs in this tree. Nothing in the list
needs a key, a rail status or a browser to become mergeable, which is why they
are ordered ahead of the rest.

## The census

| # | Title | Disposition |
| --- | --- | --- |
| 275 | Hourglass/HUL: integrate Freebuff mission-mode findings (full dossier) | NEEDS-RULING (external dossier, owner decides scope) |
| 277 | dogfood: structured round 2 - checklist pass with filed report | NEEDS-LIVE (filed report is a rail/GUI artifact) |
| 280 | [efficiency] Calibration-driven first-rung selection + earlier rotation | HERMETIC-NOW |
| 281 | [bench] Published benchmark evidence via Proof Bench pipeline | NEEDS-LIVE (published run) |
| 283 | [gui-tests] Jest tests for IPC handlers / main-process logic | HERMETIC-NOW (node test surface) |
| 284 | [mcp] Tool-description lint: When/What-in/What-out formula | HERMETIC-NOW |
| 285 | [mcp] Agent-eval layer: tool selection/chaining scored by pass-rate | HERMETIC-NOW |
| 286 | [mcp] Structured file logging + additive-only tool versioning policy | HERMETIC-NOW |
| 289 | [build] Migrate dependency management to uv | HERMETIC-NOW (CI config, no network at test time) |
| 291 | [refine] Execute the Phase 0 pilot: 20 cycles | NEEDS-LIVE (spends provider calls) |
| 292 | [driver-core] Sync vendored driver_core + CI drift check | HERMETIC-NOW |
| 294 | [provider-onboarding] 50 live key validations + verifier sweep | NEEDS-LIVE (50 paid keys) |
| 295 | [burndown] TRACKER: full completion burndown | TRACKER |
| 302 | harden(apply): screen refusal/non-code output at intake | HERMETIC-NOW |
| 308 | [planning] Split waist.py by planning responsibility | HERMETIC-NOW (large refactor; needs its own PR) |
| 309 | [jev] Separate domain evaluators from shared policy dispatch | HERMETIC-NOW |
| 310 | [provision] Split admission, approval, execution by trust boundary | HERMETIC-NOW |
| 311 | [local-fit] Exercise training and export extra in hermetic CI | HERMETIC-NOW |
| 313 | eval(models): evaluate Inception Mercury 3 | NEEDS-LIVE (paid model eval) |
| 314 | feat(jev): offline Jev-like judge modules | HERMETIC-NOW |
| 318 | route(selection): continuous recursive self-improving selection | NEEDS-RULING (design first; one PR cannot hold it) |
| 319 | route(models): automated model intake pipeline | NEEDS-RULING (needs catalog access + ruling) |
| 325 | [jev][MED] v1 assessment gate has no code counterpart | HERMETIC-NOW |
| 329 | [cli] polish: shared output flags | HERMETIC-NOW |
| 335 | [mcp][LOW] tool annotations inaccurate | HERMETIC-NOW |
| 336 | ledger: self-pruning via anchored compaction | HERMETIC-NOW (chain semantics; needs care) |
| 337 | ledger: validated criteria-prompt library | HERMETIC-NOW |
| 342 | [research] shared model-proposed ResearchPlan + Jev review lifecycle | HERMETIC-NOW (large) |
| 343 | [web] Reject unrelated hits individually | HERMETIC-NOW |
| 344 | [lifecycle] Bind resumed web context to the current request | HERMETIC-NOW |
| 346 | [planning] Exclude completed planning calls from allowance | HERMETIC-NOW |
| 380 | [tracking, low priority] Jev-free judgment backend | NEEDS-RULING (tracking) |
| 381 | [tracking, low priority] Calibrate Fusion Lite panels | NEEDS-RULING (tracking) |
| 382 | [tracking, low priority] Session-start model picker | NEEDS-RULING (tracking) |
| 407 | [visibility-site] public receipt-backed model statistics | NEEDS-RULING (publishes data publicly) |
| 412 | [gui] Verify first-use auth handoff live UX | NEEDS-LIVE (GUI) |
| 413 | [driver] Verify loopback-browser round-trip | NEEDS-LIVE (browser) |
| 414 | [mcp] Verify installed MCP runtime identity | NEEDS-LIVE (real client) |
| 415 | [gui] Live model/Jev semantic approvals via GUI | NEEDS-LIVE (GUI) |
| 416 | [docs] GUI first-use acceptance doc + serve/auth doc corrections | HERMETIC-NOW |
| 418 | [desktop] Preserve and recover long-running requests after restarts | HERMETIC-NOW (large) |
| 419 | [desktop] Separate local server health from backend status | HERMETIC-NOW |
| 420 | [site] Use the TypeSafe System One contract for route judgments | HERMETIC-NOW |
| 422 | [research] Verify citation metadata and claim-to-source support | NEEDS-LIVE (citations need fetches) |
| 423 | [audit] Add a resumable full-source Jev audit command | HERMETIC-NOW (the resumable surface; the run it drives is live) |
| 424 | [docs] Align System One feature claims with shipped status | HERMETIC-NOW |
| 425 | [driver-core] Refuse append when an existing audit chain is invalid | HERMETIC-NOW |
| 427 | [mission] Surface malformed receipt and Jev-evaluation records | HERMETIC-NOW |
| 428 | [economics] Reject negative endpoint override and cache prices | HERMETIC-NOW |
| 429 | [audit] Refuse or recover truncated JEV judgment state before append | HERMETIC-NOW |
| 430 | [lifecycle] Stop repeated retries after validated restart/refusal | HERMETIC-NOW |
| 432 | [proposal] Voice workstream | NEEDS-RULING (explicit deferral decision pending) |
| 434 | [verification] Overlay-style verification has no named surface | HERMETIC-NOW (large) |
| 448 | [desktop] Honor read-only workspace audits + preflight full scope | HERMETIC-NOW |
| 451 | [found-in-use] INDEX | TRACKER |
| 452 | [driver] Vision driver readiness | NEEDS-LIVE (supervised browser test) |
| 454 | [hardening] Environment-true checks | IN-FLIGHT (part landed in #501; residue tracked by the issue) |
| 455 | [flush] Saturation-loop mode | NEEDS-RULING (spec, register-closed) |
| 463 | [found-in-use:submission] harness-oc MCP server fails over ssh stdio | NEEDS-LIVE (ssh transport) |
| 466 | TRACKER — Champion Audit | TRACKER |
| 467 | Champion Audit: Jev decision-gate composition | HERMETIC-NOW |
| 468 | Champion Audit: V1 assessment gate (band aggregation) | HERMETIC-NOW |
| 469 | Champion Audit: Flush-loop stop bar and oscillation breaker | HERMETIC-NOW |
| 471 | Champion Audit: Jev-directed escalation rung mapping | HERMETIC-NOW |
| 472 | Champion Audit: Capability pool ordering | HERMETIC-NOW |
| 473 | Champion Audit: Router dynamic ranking | HERMETIC-NOW |
| 474 | Champion Audit: Panel convergence tally | HERMETIC-NOW |
| 475 | Champion Audit: Failure retry and circuit breaking | HERMETIC-NOW |
| 476 | Champion Audit: Spend ceilings and terminal reserve | HERMETIC-NOW |
| 480 | [driver] Perception bridge — full, extraction-first | NEEDS-LIVE (browser screenshots) |
| 481 | [driver] Input targeting model + Windows backends | IN-FLIGHT (landed in #508; residue is Windows execution) |
| 482 | [driver] launch_app action | NEEDS-LIVE (desktop launch) |
| 483 | [driver] GitHub-driving local executor + approval binding | NEEDS-RULING (credentials and approvals) |
| 489 | [jev] External Jev calibration draft: do not integrate as written | NEEDS-RULING (scoped residue per the ruling) |
| 517 | Fusion Light protocol | NEEDS-RULING (protocol decision) |
| 530 | [driver-core] Sync vendored driver_core v3.5.0 -> v3.6.0 | NEEDS-LIVE (upstream tree, not in this checkout) |
| 538 | [routing] Never defer on a provider failure | IN-FLIGHT (PR #547) |
| 539 | [routing] Availability-aware selection | IN-FLIGHT (PR #547) |
| 540 | [chat] Ordinary-answer path availability selection | IN-FLIGHT (PR #547) |
| 541 | [plan] Decomposition parse failure bounded repair | IN-FLIGHT (PR #547) |
| 542 | [plan] Artifact requests must not divert into research | IN-FLIGHT (PR #547) |
| 544 | [desktop] Workspace-folder gate at the first needing operation | IN-FLIGHT (PR #547) |

## What the census changes about the burndown

- Six of the 82 are already in flight in one PR, so the actionable count for new
  lanes is 76, of which 12 are TRACKER/NEEDS-RULING and 13 are NEEDS-LIVE.
- The hermetic remainder is roughly 45 issues. None of them is blocked on
  tonight's rail; each one can reach READY-TO-MERGE as a branch with local
  evidence, which is the only delivery state this lane can produce.
- #454 and #481 are listed IN-FLIGHT because their accepted cure already merged
  (#501, #508); they close on their own residual acceptance, not on new code
  this lane can add.
