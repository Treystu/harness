# Found in use

Symptom-keyed index of findings observed while the Harness was actually being
used. This file routes; it does not own a mechanism's rules and it does not fix
anything. Each row points at the owner issue that carries the evidence. The
Champion Audit register home is #466.

Add a row when a finding is observed in use and dedupe first against the open
set. Never close an owner issue from this file; closure happens on the owner.

| Symptom key | First seen | Observed at | Owner | Disposition |
|---|---|---|---|---|
| `citation-no-identity-resolution` | 2026-10-27 | `9741066` | #422 | open â€” capability gap; fabricated DOI passes `lint_claims` with `ok True` |
| `billed-judgment-no-ledger-row` | 2026-11-17 | `9741066` | #588 | open â€” 5 billed chat turns, 0 `jev_eval` rows in the window; PR #608 parked red |
| `driver-decision-tier-unkeyed` | 2026-11-18 | `9741066` | #413 | open â€” DOM read agrees 2/2, then `decision_not_usable` without `DRIVER_JEV_API_KEY` |
| `panel-outcome-labels-absent` | 2026-11-18 | `9741066` | #474 | open â€” 42 defer-to-converge flips cannot be scored for false-convergence |
| `audit-traces-not-persisted` | 2026-11-18 | `9741066` | #468, #469, #471, #472, #473, #475, #476 | open â€” each frozen Champion Audit program names a trace the system does not record |
| `auth-connect-duplicate-label` | 2026-11-18 | `9741066` | #412 | open â€” two controls labelled "Connect browser"; the one in `auth-pair-panel` (`display:none`) is still in the accessible tree and clicking it issues no request and shows no feedback |
| `assessment-gate-writes-nothing` | 2026-11-18 | `699f677` | #468 | open - `harness/jev_assessment.py` has no persistence path (its only match for a write pattern is an in-memory list append), so no assessment's aspect distributions can ever be replayed and the Champion Audit comparison has no corpus |
| `flush-campaign-ledgers-uncommitted` | 2026-11-18 | `699f677` | #469 | open - `harness flush --campaign` writes `<campaign>.events.jsonl` beside the campaign file and nothing retains or archives it, so no campaign pass history accumulates for the frozen replay |
| `spend-key-remaining-stale` | 2026-11-18 | `9741066` | #415 | open â€” the serve prints `key_remaining=$1.500000` on three consecutive key reads while every billed call in that run is refused with provider HTTP 402 `spend limit exhausted`; the surface reports headroom it does not have |
| `gate-labels-live-drift` | 2026-11-18 | `9741066` | #467 | open â€” the shipped 28-case decision-gate label set scores 14/28 exact against live Jev answers (false-proceeds 0); labels were authored 2026-09-27 and live `advances_goal` lands 0.84-0.99 where the set authors 0.95-0.98 |
| `freelane-reasoning-in-answer` | 2026-11-20 | `583120b4` | #415 | open — high: the answer field carries the free-lane model's scratchpad ("Defer message: ...", "Final decision: ...") with the required `HARNESS_DEFER:` line only at the end, so a user reads reasoning as the answer (run `add821eb7c09`) |
| `web-records-before-plan` | 2026-11-20 | `583120b4` | #415, #342 | open — high: five web records (fetch/search/browser) for an MCP-specification question, zero on-query, produced before any approved query-bound plan record (run `add821eb7c09`) |
| `citation-gate-unwired` | 2026-11-20 | `583120b4` | #422 | open — medium: `harness/citation_verify.py` implements the deterministic gate, but no resolver is supplied anywhere and the module has no call site outside itself, so no user path reaches it |

## Transfer entry (#451)

The Harness-in-use filings previously tracked only as GitHub issues are
transferred into this file as their symptom-keyed rows. The disposition record
is `6971091862` on #451. #451 closes as transferred once this file is on `main`;
it is not a duplicate of any row above.
