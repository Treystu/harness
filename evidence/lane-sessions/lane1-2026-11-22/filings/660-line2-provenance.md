Code change for line 2 of the two unbuilt #343 acceptance sentences, filed as
#660. Line 1 (the shared native result reviewer) is untouched here.

## The defect

The answer path handed the model `SOURCE (search)` and `SOURCE (fetch)` and
nothing else. Neither label said which part of the source the text was, so a
search engine's excerpt arrived looking exactly like a page body, and a claim
found only in a snippet could be repeated as page content. The labels were also
the only provenance the model got: the retained-context path wrote
`WEB EVIDENCE:` with the bare body and no source identity at all.

## The change

One owner for the distinction, in `harness/web.py`, where the source schema
already lives:

- `EVIDENCE_SNIPPET` / `EVIDENCE_RENDERED` and an `evidence` field recorded by
  the producer: a search hit is a snippet, a fetched page is its rendered body.
  All three successful producer sites are tagged, including the search path that
  is enriched with the page it was admitted to fetch.
- `evidence_provenance(source)` returns the recorded part, and only falls back
  to the kind for sources persisted before the field existed. A recorded value
  that is not a part it knows returns `None` rather than a guess: an
  unrecognised producer label must not be upgraded to "rendered".
- `source_label(source)` is the single label both model-facing formatters now
  use: `search snippet`, `fetch rendered page`, and the plain kind for sources
  that carry no evidence part (`browser`, `detour`) and for failures.

`harness/hourglass_lifecycle.py` and `harness/conversation_lifecycle.py` both
label every item through `source_label`, and the block header now carries a
legend (`_EVIDENCE_LEGEND`) telling the model that a snippet is an excerpt and
not the page, and that a snippet-only claim must not be stated as page content.
The retained-context path names the source too, instead of a bare body.

A failed source keeps its plain kind: it read nothing, so it has no evidence
part to name.

## Acceptance evidence (#660 line 2)

| Required | Where |
| --- | --- |
| Every evidence item carries its provenance to the model | `source_label` used at both formatters, legend in the header |
| A test pins that a snippet is never labelled rendered | `test_a_snippet_is_never_labelled_rendered` |
| A snippet item labelled as a snippet | `test_search_hit_is_a_snippet`, `test_search_only_path_records_snippets` |
| A rendered item labelled as rendered | `test_fetched_page_is_rendered`, `test_enriched_page_records_rendered` |
| Both kinds distinguished in what the model reads | `test_snippet_and_rendered_are_distinguished_in_the_system_prompt` |

The #343 behaviour landed before the close is preserved and still asserted at
this head: the mixed-target batch case and the final-URL subject gate
(`tests/test_web.py`), both green.

## Verification

- `pytest tests/test_evidence_provenance.py tests/test_web.py
  tests/test_jev_answer_lifecycle.py tests/test_agent.py -q` -> 286 passed,
  6 subtests passed.
- `ruff check` over the four touched modules and the new test file -> clean.

No checkpoint, ledger, or response-schema field is added or assumed. The one
field this adds is on the in-memory web-source dict, which the checkpoint
already stores whole, so resumed sources carry it and older ones fall back.

This advances #660 line 2 only. Line 1 (the shared native result reviewer) remains unbuilt and open on #660.
