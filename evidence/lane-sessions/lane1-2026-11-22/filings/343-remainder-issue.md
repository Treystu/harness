## Context

`#343` was closed by the operator at 2026-11-22T08:43:02Z with no close
comment, immediately after the acceptance matrix was filed (`7076706727`).
Two acceptance sentences were still unbuilt at that close. An operator close
does not erase unbuilt acceptance work, and this lane takes no completion
credit for them; per the tick-775 decision they are filed here verbatim, with
their own home.

Landed on the #343 line before the close, for the record:

- PR #647 (`fecc4692`): per-candidate admission of search hits.
- PR #658 (`4fa960ce`): the fetched page is judged by its final URL's subject,
  not only the candidate snippet, on the search-enrichment path.

## Unbuilt acceptance lines (verbatim from `7076829057`)

1. the shared native **result reviewer** for semantic relevance, with
   rejected/uncertain content barred from evidence;
2. an explicit **snippet-versus-rendered-evidence** distinction in what the
   model is given.

## What "built" means for each line

1. **Shared native result reviewer.** A single reviewer, in the same seat for
   every retrieval path rather than per-call ad hoc filtering, takes a fetched
   result (candidate plus final page) and returns a typed relevance verdict.
   Content judged rejected or uncertain is excluded from the evidence handed to
   the answer model, not merely down-ranked. An uncertain verdict must not
   silently become admission.
2. **Snippet-versus-rendered evidence.** What the model receives names which
   part it is reading: a search snippet, or the rendered/extracted page body.
   The answer path must not present snippet text as if it were page content, and
   a claim sourced from a snippet must be distinguishable from one sourced from
   the page.

## Acceptance

- A typed reviewer verdict exists for every admitted result, recorded with its
  reason, and rejected/uncertain results are absent from the evidence passed to
  the model.
- Every evidence item carries its provenance kind (snippet or rendered page) to
  the model, and a test pins that a snippet is never labelled as rendered
  content.
- Focused tests cover: a rejected result excluded; an uncertain result excluded
  rather than admitted; a snippet item labelled as a snippet; a rendered item
  labelled as rendered.
- Existing #343 behaviour is preserved: the mixed-target batch case and the
  final-URL subject gate still hold at the merge head.

## Scope

Retrieval admission and evidence labelling only. Freshness/lifecycle binding is
#344. Claim-level provenance is #422. No schema inventing: if a checkpoint or
ledger field is required and absent, the gap is named rather than assumed.

## References

- #343 (closed by operator, no close comment)
- Lane 1 amendment `7076829057`; oversight decision `7076933398`
- `docs/jev-roadmap.md` register rows for #343 and #344
