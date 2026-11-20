## #422 - PARKED at 4618b5f9: the gate works and refuses honestly, but no production call site and no resolver exist; unblocker and decision owner named

**Revision under test.** `main` **`4618b5f997a0f04331b26aa8452568835dfccf1e`**, read directly from the commit (no service needed: the module is pure and hermetic).

### What was executed

`harness/citation_verify.py` imported and run at this head against one citation with a DOIs, one claim and no retrieved sources - the shape a report would hand it. Receipt `422-probe.txt`.

| Observation | Value |
|---|---|
| module present | `harness/citation_verify.py`, 450 lines |
| API | `verify_citation`, `audit_citations`, `may_label_citation_verified` all present |
| run result | `citation_verified: false`, `may_label: false`, citation status **`not_verifiable`**, reasons `["resolver_error: no DOI resolver was supplied"]` |
| import census (all `.py` at this head) | **only tests import it**: `tests/test_citation_verify.py:5`, `tests/test_d12cov_audit_evidence.py:21,23` - **zero production importers** |
| resolver default | `resolver=None` -> `_resolve` returns `{"error": "no DOI resolver was supplied"}` |

### Verdict

**CANNOT EXECUTE END-TO-END AT THIS HEAD - parked.** The deterministic gate is real and behaves correctly on the honest-insufficiency path: with no resolver it records `not_verifiable` and refuses the `citation_verified` label rather than inventing metadata. What does not exist is any path a user can reach: no production call site, and no resolver wired anywhere, so acceptance criteria 1-6 of the issue cannot be exercised against a running build.

This matches the earlier finding filed as `citation-gate-unwired` (PR #631, row owner #422); this run re-measures it at the current head and adds the exact unit-level output.

### Unblocker and decision owner

- **Unblocker (product wiring decision, not code this lane may write):** choose and wire a DOI/metadata resolver (registry client or publisher fetch) **and** a call site in the report path that invokes `audit_citations` and honours `may_label_citation_verified`.
- **Decision owner:** the **product owner (Treystu)**, routed by the sergeant. It is a product-scope and external-dependency decision (which registry, what retry/rate behaviour, whether a paywalled or missing record blocks a report), so it is a gated oversight act, not a lane improvisation.

Parked with that unblocker named; no completion credit taken; the issue stays open.
