# Run Lucas Gate before the Jev decision evaluation

Part of #683, finding 61 (P1). Verified against `main`
`8fc28a0e` on 2026-11-25: still present.

## Current evidence

evidence/lane-sessions/sergeant-2026-11-19/gates_620.py:47 calls `policy.evaluate_decision(...)` and `:63` runs `run_typed_track(...)`; the module docstring at `:1` still says 'Product Jev first, Lucas Gate v2 second'. All 32 `gates_*.py` drivers in that lane keep the same order (for example `gates_624.py` jev=48 lucas=64, `gates_406`-era `gates_482.py` jev=47 lucas=63), so the AGENTS.md sequence is still reversed.

## The finding

Run Lucas Gate before the Jev decision evaluation

This driver calls `policy.evaluate_decision` before `run_typed_track`, as do the other gate drivers added here. That reverses the explicit `AGENTS.md` lane requirement, “Lucas Gate v2 first, Jev for decisions/dispositions,” so these receipts do not demonstrate the required gate sequence. Move the Lucas assessment ahead of the Jev call in the drivers and distinguish the historical receipts from evidence produced under the corrected sequence.

AGENTS.md reference: [AGENTS.md:L122-L122](https://github.com/Treystu/harness/blob/f0957d647e60b017ef792b5718cb016a0b277441/AGENTS.md#L122-L122)

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `evidence/lane-sessions/sergeant-2026-11-19/gates_620.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/634#discussion_r4646946203
