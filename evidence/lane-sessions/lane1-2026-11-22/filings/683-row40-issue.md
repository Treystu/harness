# Enforce eligibility before issuing a token voucher

Part of #683, finding 40 (P1). Verified against `main`
`8fc28a0e` on 2026-11-25: still present.

## Current evidence

harness/public_share.py:594 voucher() HMACs any caller-supplied string; no credential, model or round is checked, and the token itself is computed client-side by eligibility_token (:600) inside build_report (:687). Vouchers for arbitrary tokens therefore verify.

## The finding

Enforce eligibility before issuing a token voucher

A client can obtain vouchers for arbitrarily many tokens because `voucher()` accepts only a caller-supplied string, without checking a credential or its derivation for the model and round. I verified that copying one report, replacing its eligibility block with ten arbitrary tokens signed by this issuer, and submitting those copies publishes all four metrics. No additional credentials are needed. The issuer must enforce one eligible token per credential/model/round rather than relying on clients to call `eligibility_token()` honestly.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `harness/public_share.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/619#discussion_r4621137026
