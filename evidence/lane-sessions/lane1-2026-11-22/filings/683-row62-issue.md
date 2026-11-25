# Bind each receipt to the head actually being assessed

Part of #683, finding 62 (P1). Verified against `main`
`8fc28a0e` on 2026-11-25: still present.

## Current evidence

evidence/lane-sessions/sergeant-2026-11-19/gates_624.py:24-31 `ACTION` names head `6c90298b0bb962862567955601fc89e8dc2a4e6a`, `:38-44` builds the category evidence from 'PR #canon1 at exact head dbb54a7', and `:96-98` writes `_meta.head = "dbb54a7f50216ef537fef71f3d88b2e807d09e45"`. The #624 receipt is therefore still bound to the CANON-1 head and CANON-1 scorecard evidence.

## The finding

Bind each receipt to the head actually being assessed

For the #624 merge, `ACTION` names head `6c90298b0bb962862567955601fc89e8dc2a4e6a`, but this metadata records the unrelated CANON-1 head `dbb54a7…`; `gates-624.json` contains the same incorrect association. The category evidence also describes CANON-1 rather than #624. This copied provenance occurs in several other drivers, including #627, #631 and #635, making their passes appear backed by another artifact's evidence. Replace the copied head and scorecard evidence with the assessed action's actual provenance so the receipts satisfy `AGENTS.md`'s exact-head verification requirement.

AGENTS.md reference: [AGENTS.md:L122-L122](https://github.com/Treystu/harness/blob/f0957d647e60b017ef792b5718cb016a0b277441/AGENTS.md#L122-L122)

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `evidence/lane-sessions/sergeant-2026-11-19/gates_624.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/634#discussion_r4646946208
