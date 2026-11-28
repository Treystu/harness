# Refresh the authoritative mirror instead of adding a second register

Part of #683, finding 47 (P1). Verified against `main`
`8fc28a0e` on 2026-11-25: still present.

## Current evidence

docs/jev-roadmap.md:220 and :255 still label #311 and #407 OPEN inside the retired REGISTER_MIRROR, whose header (:25-26) still claims 'This section, not the dated filings below, is the live count and order'; AGENTS.md:23-33 still generates the 60-open mission pointer against that mirror instead of the 2026-11-19 register.

## The finding

Refresh the authoritative mirror instead of adding a second register

The new 41-issue register sits outside `REGISTER_MIRROR`, but the roadmap introduction still explicitly makes that mirror—not subsequent tables—the live count and execution order. `AGENTS.md` likewise directs incoming agents to the unchanged 60-issue mirror, and `RegisterMirrorParityTests` only examines the marked section. Consequently, this refresh leaves the authoritative entry points advertising the old queue, including #407 and #311 as OPEN despite their CLOSED dispositions here. Update the existing mirror and regenerate the mission pointer together so readers and contract checks consume the refreshed register rather than a competing plan.

AGENTS.md reference: [AGENTS.md:L27-L29](https://github.com/Treystu/harness/blob/0f9532e24b6029d8ddbc48e9885f56a17e558184/AGENTS.md#L27-L29)

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `docs/jev-roadmap.md`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/622#discussion_r4628005985
