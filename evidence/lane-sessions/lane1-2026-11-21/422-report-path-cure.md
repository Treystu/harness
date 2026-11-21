# #422 report-path cure - the resolver now has a product importer

**Branch:** `lane/422-report-citation`, cut from `main`
`280ee3d4f99bf3d33645ddde21b243cebe0b191b`.
**Issue:** #422 (citation verification) / PR #645 (the resolver).
**Class:** product wiring, not measurement. No window was run and no credit is
claimed for #422's acceptance; the acceptance can now be exercised because
the path exists.

## 1. The gap this closes, precisely

At `280ee3d4` the deterministic gate and the registry adapter both existed and
neither had a product importer:

```
$ grep -rn "citation_resolver\|CitationResolver\|DoiResolver" --include=*.py harness/ tests/ \
    | grep -v "^harness/citation_resolver.py"
tests/test_citation_resolver.py:9:from harness.citation_resolver import (
```

So a report could not resolve a DOI, and the register's own line - "the
report-path call site is the remaining product wiring" - described the whole
remaining defect.

## 2. What was wired, and where

The report path is the web-augmented answer the conversation lane returns
(`harness/conversation_lifecycle.py::_handle_conversation`): it is the lane that
retrieves sources, puts them in front of the model as `SOURCE (...)` evidence,
and returns the `web_sources` provenance a report carries. That is the path
#422's acceptance describes.

| Piece | Home | What it does |
| --- | --- | --- |
| product importer | `harness/conversation_lifecycle.py` | `from .citation_resolver import REPORT_CITATION_TIMEOUT, RegistryResolver, audit_report_citations` - a static import, so the import census now shows the product |
| resolver seam | `_report_citation_resolver()` | returns `RegistryResolver(timeout=REPORT_CITATION_TIMEOUT)`; a module seam so a test answers as a registry without the network |
| report audit | `_report_citation_audit()` | runs the gate over the turn's own sources before the result is built, and fails open with a recorded reason |
| artifact field | result `citation_audit` | the audit travels with the report: per-citation status, canonical DOI, `metadata_source`, unresolved list, summary, `report` counts, and a `label` the gate decides |
| record mapping | `harness/citation_resolver.py::citation_records` | maps gathered web sources onto `citation_verify`'s `citation`/`claim`/`source` records |
| audit entry | `harness/citation_resolver.py::audit_report_citations` | calls `audit_citations(..., resolver=...)` and adds the `report` counts plus the gate's `label` |

No new behaviour was invented: the adapter is #645's, the gate is the existing
`citation_verify`, and every refusal path is the gate's own. What is new is
that something in the product calls them.

### The rules the wiring keeps

- **Only what the retrieval returned is supplied.** The DOI comes from the
  source URL (`https://doi.org/10.x/y`) or a DOI the source explicitly carries;
  bibliography fields are passed only when the source carries them. An absent
  field stays absent, so the gate records `metadata_absent` instead of a
  guessed title.
- **The label stays the gate's.** `citation_verified` is never set by the
  report path; `audit_report_citations` copies `may_label_citation_verified`
  into a display `label`, and an unassessed claim keeps the gate closed with
  `semantic_support_unassessed`.
- **Failures are evidence.** A rate-limited registry is
  `resolver_rate_limited`; a raising resolver is `resolver_error: ...`; an
  audit that cannot be built at all is `citation_audit_unavailable: ...`. None
  of them fails the turn and none of them promotes a citation.
- **Bounded.** At most `MAX_REPORT_CITATIONS = 3` citations per report and a
  5-second resolver timeout, so one slow registry cannot turn a chat turn into
  a wait.

## 3. The test, driving the product entry (not the resolver in isolation)

`tests/test_report_citation_422.py` drives `run_prompt(..., web=True,
force_conversation=True)` - the product entry that routes into
`_handle_conversation` - with the fetch seam and the resolver seam replaced, so
nothing touches the network:

```
$ uv run --no-project --with pytest --python 3.12 pytest tests/test_report_citation_422.py -q
....                                                                     [100%]
4 passed in 0.21s
```

| Test | What it proves |
| --- | --- |
| `test_report_ships_a_citation_audit_resolved_by_the_product_resolver` | the registry the product builds is the one that answers (`registry.calls == [DOI]`); the citation is `supported` with `canonical_doi` and `metadata_source` on the report; `report.doi_citations == 1`; the label is `not_verified` because the claim has no semantic assessment |
| `test_a_resolution_failure_is_recorded_not_promoted` | `rate_limited` becomes `not_verifiable` with `resolver_rate_limited`, not a promotion |
| `test_a_raising_registry_never_costs_the_report` | a transport exception is recorded as `resolver_error: RuntimeError: ...` and the turn still returns `ok` |
| `test_a_report_without_a_doi_still_carries_its_audit` | a report with no DOI source still ships the audit, with `doi_citations == 0` and the resolver never called |

## 4. Verification at the exact head

```
$ ruff check harness/conversation_lifecycle.py harness/citation_resolver.py tests/test_report_citation_422.py
All checks passed!
```

Focused and neighbouring suites, at this head:

```
pytest tests/test_report_citation_422.py -q                       -> 4 passed
pytest tests/test_citation_resolver.py tests/test_citation_verify.py \
       tests/test_web.py tests/test_d12cov_audit_evidence.py -q   -> 184 passed, 5 subtests passed
pytest tests/test_agent.py -q                                     -> 114 passed, 2 subtests passed
```

Full suite, run in three file chunks because a single run exceeds this host's
five-minute command ceiling:

```
chunk 1: 2069 passed, 402 subtests passed
chunk 2: 2196 passed, 42 skipped, 370 subtests passed, 1 failed
chunk 3: 2413 passed, 2 skipped, 307 subtests passed, 1 failed
```

The two failures, each read and named rather than waved past:

| Failure | Cause | Evidence it is not this change |
| --- | --- | --- |
| `tests/test_jev_chaos.py::ChaosTests::test_roomy_budget` | a latency assertion (`24.803 not less than 20`) tripped while three suites ran concurrently on this VM | passes in isolation at the same head: `3 passed in 2.43s`; the test measures wall-clock latency, and neither touched file is imported by it |
| `tests/test_release_driver.py::ReleaseDriverContractTests::test_interpreter_matrix_covers_ci_versions` | the interpreter matrix expects 3.9/3.11/3.13, which this host does not have | pre-existing and already recorded on this repo in `evidence/lane-sessions/harness-core/2026-11-13-session.md`; unrelated to citations |

## 5. What this does NOT do

- It does not run #422's end-to-end acceptance window and does not close #422;
  the register's close test is still the acceptance receipt.
- It does not claim a landing. The branch is pushed, unmerged, ungated by a
  CircleCI read (which this session cannot perform).
- It does not touch #469's window, #475's disposition, or the register count.
