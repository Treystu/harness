## #422 call site landed: the citation gate now has a product path, and it refuses a fabricated DOI

**PR:** #657, head `33c53d05df067de9eba06045da78d4ee51f8aa2d`, **merged** as
`eabe34b820001946a4dbeb28fc96d021fbd7ca5f`.
**Rail at that exact head, read in the same command immediately before the
merge:** 16 of 16 `ci/circleci:` contexts `success`, zero pending, zero failing.
**Gates:** Lucas Gate v2 `pass` (artifact `a6021ee8`), product Jev `investigate` /
`proceed` (supported 0.06, `jev-1.14.0`), receipt `gates-422-landing.json`.

### The gap this closes

The gate and its resolver both existed with no product caller. `grep -rn
"citation_verify|citation_resolver" harness/` returned only the two modules, so
a report could carry a DOI nobody can resolve and still pass `lint-claims` with
`ok: true` - the rows `citation-gate-unwired` and `citation-no-identity-resolution`
in `docs/found-in-use.md`.

### What landed

- `harness/citation_resolver.py:audit_report_citations` - the product entry to
  the network half. Resolver omitted means the real Crossref registry;
  `resolver=None` means audit with no network at all. It returns the same
  `citation_verified` flag `audit_citations` computes, so no caller can make a
  weaker claim than the gate.
- `harness/cli.py:_cmd_lint_claims` - calls it whenever the manifest declares a
  `citations` section, and exits 2 unless the gate returns `citation_verified`,
  printing every unresolved item with its closed-set reason. `--no-network`
  audits offline. A manifest with no citation section behaves exactly as before.
- `harness/claims.py` - `load_manifest_document` / `parse_manifest_data`, so the
  report face reads the citation sections beside the claim half.
- `tests/test_lint_claims_citations_422.py` - 12 hermetic tests, resolver
  injected through one seam.

### Live acceptance, on the real registry, through the product entry

Driven through `harness.cli.main` (the same path the console command runs), not a
hand-built call to the gate. Receipt:
`evidence/lane-sessions/lane1-2026-11-22/citation-live-acceptance.json`.

| Case | Exit | Result |
| --- | --- | --- |
| Real DOI `10.1103/physrevlett.116.061102` with its registry title | 0 | `citation_verified: true`; title matched field by field; `metadata_source crossref:10.1103/physrevlett.116.061102` |
| The same DOI with a title Crossref denies | 2 | `contradicted`, `field_mismatch:title`, both values shown |
| `10.9999/definitely-not-a-real-doi-422` | 2 | `doi_not_found` |
| The real DOI with `--no-network` | 2 | `resolver_error: no DOI resolver was supplied` |

The fabricated-DOI case is the recorded defect, now refused.

### Verified, and what is not

- **Verified:** a report that declares a bibliography is audited against a real
  registry; identity, title/authors/year/venue/version mismatch, a nonexistent
  DOI, a registry `rate_limited`, a missing passage, a missing locator, and an
  unassessed claim all refuse the label rather than inventing verification.
- **Not claimed:** nothing yet feeds a report's bibliography into that manifest
  automatically from the research lifecycle. A report author (or a producer
  step) must declare the `citations`, `citation_claims`, `sources` and
  `semantic_by_claim` sections; the gate then judges them. That handoff from
  #342's gathered sources into an audited manifest is the remaining work, and it
  is why #422 stays open rather than being closed on this landing.

### Register

`docs/found-in-use.md`: `citation-gate-unwired` and `citation-no-identity-resolution`
moved to cured with file:line, the pinning test, and the live receipt.
`docs/jev-roadmap.md` #422 row records the call site as landed.
