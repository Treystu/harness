Line-by-line landing record for this issue. Line 2 is built; line 1 is not.

**DONE - line 2, snippet versus rendered evidence** (PR #663, merged as
`75fe2a8ada93983bbb913f5d7fd29e67acc112a1` at head
`c7262c238d2f9361ddbadb118b36117588102813`, 16/16 CircleCI at the exact head).

The producer now records what it actually read: `harness/web.py` tags every
admitted search hit `evidence: snippet` and every fetched page
`evidence: rendered`, including the search path that is enriched with the page
it was admitted to fetch. `evidence_provenance(source)` returns that recorded
part, falling back to the kind only for sources persisted before the field
existed; a recorded value that is not a part it knows returns `None` rather
than a guess, so an unrecognised producer label can never be upgraded to
`rendered`. `source_label(source)` is the one label both model-facing
formatters use, so the hourglass answer path and the conversation path cannot
drift apart.

What the model reads now: `SOURCE (search snippet):`, `SOURCE (fetch rendered
page):`, and a legend on the block stating that a snippet is the search
engine's excerpt and not the page, and that a snippet-only claim must not be
stated as page content. The retained-context path, which used to write a bare
`WEB EVIDENCE:` body with no source identity, now names the source and its
provenance. A failed source keeps its plain kind: it read nothing, so it has no
evidence part to name.

Acceptance for line 2, from the filing:

- provenance on every evidence item - `source_label` at both formatters plus
  the legend.
- a snippet is never labelled rendered - `test_a_snippet_is_never_labelled_rendered`,
  and the recorded-field test that keeps a fetch-labelled snippet a snippet.
- snippet labelled as a snippet, rendered labelled as rendered -
  `test_search_hit_is_a_snippet`, `test_fetched_page_is_rendered`,
  `test_search_only_path_records_snippets`, `test_enriched_page_records_rendered`.
- both kinds distinguished in what the model reads -
  `test_snippet_and_rendered_are_distinguished_in_the_system_prompt`.

The #343 behaviour that landed before the close is still asserted at this head:
the mixed-target batch case and the final-URL subject gate in
`tests/test_web.py`.

Verification: `pytest tests/test_evidence_provenance.py tests/test_web.py
tests/test_jev_answer_lifecycle.py tests/test_agent.py -q` -> 286 passed, 6
subtests passed; `ruff check` over the four touched modules and the new test
file -> clean.

**WIP - line 1, the shared native result reviewer.** Not started, and no
completion credit taken. The design is filed on this issue below so the build
does not invent it: the seat already exists as `evaluate_file_triage` in
`harness/jev_policy.py` (one preflighted pack call, per-item noul answers, a
refusal fallback, structural accounting), and the slice mirrors it for fetched
results with three typed bands on the noul - `>= 0.70 relevant`,
`<= 0.30 rejected`, else `uncertain` - recorded with probability and reason,
with rejected and uncertain results absent from the evidence rather than
down-ranked, at one point shared by both retrieval paths.

**One question the issue does not answer, for a ruling rather than a guess.**
The acceptance text fixes what a rejected or uncertain verdict does. It does
not say what admission does when the reviewer cannot answer at all - evaluator
refusal, spend limit, transport error. Excluding everything is safe against
fabricated relevance and costs the whole web detour while Jev is down;
admitting items labelled `unreviewed` protects against silent evidence loss and
risks passing unrelated content, which is the thing line 1 exists to prevent.
Until ruled, the build will exclude and disclose the outage in the run record
and in the evidence block, which is the narrower reading and cannot
misrepresent an item as reviewed.

Register: `docs/jev-roadmap.md` records the line-2 landing at merge `0e041435`
(PR #664), with this issue still OPEN and line 1 named as unbuilt.
