# Found in use

Symptom-keyed index of findings observed while the Harness was actually being
used. This file routes; it does not own a mechanism's rules and it does not fix
anything. Each row points at the owner issue that carries the evidence. The
Champion Audit register home is #466.

Add a row when a finding is observed in use and dedupe first against the open
set. Never close an owner issue from this file; closure happens on the owner.

| Symptom key | First seen | Observed at | Owner | Disposition |
|---|---|---|---|---|
| `citation-no-identity-resolution` | 2026-10-27 | `9741066` | #422 | open — capability gap; fabricated DOI passes `lint_claims` with `ok True` |
| `billed-judgment-no-ledger-row` | 2026-11-17 | `9741066` | #588 | open — 5 billed chat turns, 0 `jev_eval` rows in the window; PR #608 parked red |
| `driver-decision-tier-unkeyed` | 2026-11-18 | `9741066` | #413 | open — DOM read agrees 2/2, then `decision_not_usable` without `DRIVER_JEV_API_KEY` |
| `panel-outcome-labels-absent` | 2026-11-18 | `9741066` | #474 | open — 42 defer-to-converge flips cannot be scored for false-convergence |
| `audit-traces-not-persisted` | 2026-11-18 | `9741066` | #468, #469, #471, #472, #473, #475, #476 | open — each frozen Champion Audit program names a trace the system does not record |
| `auth-connect-duplicate-label` | 2026-11-18 | `9741066` | #412 | open — two controls labelled "Connect browser"; the one in `auth-pair-panel` (`display:none`) is still in the accessible tree and clicking it issues no request and shows no feedback |
| `bridge-hand-no-process-entry` | 2026-11-19 | `a7ca742` | #480 | open — BR2's hand has no process entry point: `python -m driver_core.capture_hand --root <dir> --status` exits 0 and does nothing (no `main()`, no output); cure in #625 |
| `bridge-battery-ledger-not-isolated` | 2026-11-19 | `a7ca742` | #480 | open — a second run on a named `--root` reads the first run's answers as its own (`met 1/6`, exit 1), and a failed live probe leaves a pending request the later probes can answer; cure in #625 |

## Transfer entry (#451)

The Harness-in-use filings previously tracked only as GitHub issues are
transferred into this file as their symptom-keyed rows. The disposition record
is `6971091862` on #451. #451 closes as transferred once this file is on `main`;
it is not a duplicate of any row above.
