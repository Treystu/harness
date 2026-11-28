# Authenticate the evidence claim before accepting statistics

Part of #683, finding 43 (P1). Verified against `main`
`8fc28a0e` on 2026-11-25: still present.

## Current evidence

harness/public_share.py:740 requires only `chain_verified is True`, a boolean build_report copies from its own local claim (:676), and :745 checks evidence_digest for hex format only. Replacing stats with a recomputed commitment and stats_digest leaves no check to fail, and no bounds test stops successes exceeding tasks.

## The finding

Authenticate the evidence claim before accepting statistics

An eligible contributor can replace the shared statistics, recompute the unkeyed commitment and `stats_digest`, and leave the evidence claim unchanged; intake accepts the altered values because `chain_verified` is only a caller-controlled boolean and `evidence_digest` is never verified against anything. I confirmed that a report with 103 successes out of three tasks passes validation. This permits arbitrary poisoning of figures advertised as verified, even if operator uniqueness is fixed. Require a verifiable evidence-to-statistics proof or trusted attestation, and enforce the statistic bounds and consistency constraints at intake.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `harness/public_share.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/619#discussion_r4621137064
