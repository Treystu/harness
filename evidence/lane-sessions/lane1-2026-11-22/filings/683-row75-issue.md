# Require citation assessments to cover the report's actual claims

Part of #683, finding 75 (P2). Verified against `main` `8fc28a0e` on
2026-11-25: still present.

## Method

Code read of the named path at `8fc28a0e`: `harness/citation_resolver.py` and the code it calls,
on 2026-11-25. No repository code changed in that act, so this is a read
of the shipped path, not a run and not a test.

## Result

harness/citation_resolver.py:196-199 passes only `report.get("citation_claims")` into `audit_citations`, which labels the report from exactly the claims it was given (harness/citation_verify.py:417-421), and harness/cli.py:486-492 publishes that label as `citation_verified`. Nothing compares `citation_claims` against the report's `claims`, so a claim omitted from the audited list is never assessed and the report-level label still passes.

## The finding

When `claims` contains entries omitted from `citation_claims`, this wrapper audits only the latter and still lets `lint-claims` label the entire report `citation_verified: true`. Using the new test fixture, adding an unsupported `c2` to `claims` while leaving `citation_claims` unchanged produces exit 0, an empty unresolved list, and a verified label despite never assessing `c2`. Validate that the citation assessments cover the report's actual claim IDs, and leave missing assessments unresolved before granting the report-level label.

## Scope of this issue

Compare the IDs in the report claims against the IDs in citation_claims before granting the report-level label, and leave any uncovered claim unresolved with its own reason. The coverage check belongs beside the audit, not in the caller.

## Not claimed

- Not claimed: that citation_claims entries absent from claims are errors; the coverage requirement is one-directional.
- Not claimed: any change to the claim-support bands.
- Not claimed: that the fixture c2 must be assessed by a semantic judge; unresolved is the honest outcome when it has no assessment.

## Acceptance

- A report whose claims section contains an ID missing from citation_claims cannot be labeled citation_verified.
- The uncovered claim appears in the unresolved list with a reason naming the gap.
- A hermetic test adds an unsupported claim to the report claims and asserts a non-zero exit from lint-claims.

Provenance: https://github.com/Treystu/harness/pull/657#discussion_r4657065312

