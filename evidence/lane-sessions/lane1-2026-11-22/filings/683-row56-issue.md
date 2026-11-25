# Run Lucas Gate before the Jev disposition

Part of #683, finding 56 (P1). Verified against `main`
`8fc28a0e` on 2026-11-25: still present.

## Current evidence

evidence/lane-sessions/w2-2026-11-20/gates_turn9.py:54 calls `policy.evaluate_decision` before `run_typed_track` at :68, so the Jev disposition still precedes Lucas Gate v2 in that filing script.

## The finding

Run Lucas Gate before the Jev disposition

For every filing processed here, `policy.evaluate_decision()` runs before `run_typed_track()`, reversing the explicit requirement in `AGENTS.md` that Lucas Gate v2 run first on comments and dispositions. Consequently, these receipts do not demonstrate the repository-mandated gate sequence. Move the Lucas evaluation ahead of the Jev decision; apply the same correction to `gates_413.py`, which repeats this ordering.

AGENTS.md reference: [AGENTS.md:L122-L122](https://github.com/Treystu/harness/blob/f3ab9b8b20028ea5d63e68878ec69846cac6ba22/AGENTS.md#L122-L122)

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `evidence/lane-sessions/w2-2026-11-20/gates_turn9.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/629#discussion_r4646550830
