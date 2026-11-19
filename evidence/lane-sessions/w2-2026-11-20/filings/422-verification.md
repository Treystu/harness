## W2 — #422 verification at `583120b4`: the deterministic citation gate exists; nothing in the product calls it

Register home: #466. Nothing fixed by this lane; no product code touched.

**Revision under test.** Operator tree HEAD `583120b436ce747c40be8543c4fa8cbf686cb48b` (equals `origin/main` `a7ca742e` plus the sergeant branch). Read-only source inspection; no network calls beyond the provider probes filed separately on #415.

### What is on disk

`harness/citation_verify.py` exists at this head and implements the deterministic part of the contract:

| Contract element (#422) | Present in the module |
|---|---|
| stable citation id, closed-set statuses | `STATUSES = supported / partially_supported / contradicted / not_verifiable`; `citation_id` per source record |
| canonical DOI, field-by-field metadata comparison | `normalize_doi` strips `https://doi.org/`, `dx.doi.org/`, `doi:` and lowercases; `verify_citation` compares supplied vs resolved title/authors/year/venue/DOI/version and reports mismatches field by field |
| exact passage or hash-pinned bounded excerpt plus locator | `MAX_PASSAGE_CHARS = 2000`, passage hashing, locator carried on the claim record |
| no promotion on missing data | missing metadata, `paywalled`/`unavailable`/`rate_limited`/`http_error`/`timeout`/`blocked` retrieval statuses all resolve to `not_verifiable`; the module's own docstring states a Jev assessment cannot manufacture provenance |
| resolver failure is recorded, not guessed | `_resolve()` returns `{"error": "no DOI resolver was supplied"}` when no resolver is injected |

So the issue's 2026-10-28 finding — "no DOI resolver, Crossref/OpenAlex lookup, field-by-field bibliography check, or exact-passage locator" — is **partly cured at the library level**: the field-by-field gate and the passage/locator contract are now code-owned and hermetic.

### What is not there

- **No resolver implementation.** No Crossref, OpenAlex, DataCite or content-negotiation call exists anywhere in `harness/` (`grep -rn "crossref|openalex|doi.org|datacite" --include=*.py harness` -> no matches). The module accepts a resolver by injection and nothing supplies one.
- **No production call site.** `grep -rn "citation_verify" --include=*.py harness`, excluding the module itself, returns nothing: no import from `server.py`, `chat.py`, `research` or the report path. The gate cannot be reached by a user.
- **No report-level label.** The "a report may carry citation-verified only when every item is supported" rule is written in the module docstring but no report payload field or render path consumes it.

### Verdict

**NOT VERIFIED end to end at `583120b4`.** Deterministic identity/provenance logic is implemented and testable; the end-to-end workflow the acceptance criteria describe (resolve -> compare -> bind a claim to a passage -> refuse the label) is not wired into any path a user runs. The `citation-no-identity-resolution` intake row remains accurate as a statement about the product path, and its wording ("no metadata-registry integration in those paths") is now more precise than "no code exists".

No completion credit and no recommendation on priority: whether the module is wired, or the resolver built first, is the issue owner's call. This lane records the state and does not redesign.


**Gates, in order.** Product Jev (keyed `jev-1.14.0`, caller `w2-champion-audit`, site `audit_admissibility`, ledger seq 81519): verdict `investigate`, supported 0.03, cost $2.6544000000000002e-05. Lucas Gate v2 (typed track): `status: pass`, artifact `7a79abe6ac880646`. The Jev verdict is reported as returned, not re-run for a friendlier verdict; the disposition above rests on the observed run, not on the gate label.
