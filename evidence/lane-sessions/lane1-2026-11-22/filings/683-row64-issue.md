# Regenerate the gate receipt for the committed turn-15 filings

Part of #683, finding 64 (P2). Verified against `main`
`8fc28a0e` on 2026-11-25: still present.

## Current evidence

`evidence/lane-sessions/w2-2026-11-20/gates-turn15.json` still records `413-head-currency` sha256 `7fef1693...` and `295-status-15` sha256 `fd707573...`; the committed filings at main hash to `4182bb8647b7e52c820ed74d08e0e754ec1a5be05adb2f7f583f39d258fb68a0` (`filings/413-head-currency-t15.md`) and `a1e6b710d679e02d83d03b2e3da4b6a61b098320729ceea1fb331e545e8f1c5e` (`filings/295-status-15.md`), both computed here from the blobs at 8fc28a0e. The receipt still cannot verify the published filings.

## The finding

Regenerate the gate receipt for the committed turn-15 filings

Both artifact hashes in this receipt differ from the filings committed here: `413-head-currency-t15.md` hashes to `4182bb86…` rather than `7fef1693…`, and `295-status-15.md` hashes to `a1e6b710…` rather than `fd707573…`. `harness/lucas_gate.py` hashes the exact UTF-8 artifact text, so these passes cannot verify the published versions, even though both filings cite this receipt as their gate evidence. Re-run the gates against the final filings, or preserve the exact evaluated versions with their corresponding receipt, so the required per-comment verification is auditable.

AGENTS.md reference: [AGENTS.md:L122-L122](https://github.com/Treystu/harness/blob/29d02a52238dafc2f9a2d0eace8e383792d863f7/AGENTS.md#L122-L122)

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `evidence/lane-sessions/w2-2026-11-20/gates-turn15.json`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/637#discussion_r4633756041
