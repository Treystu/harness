# #343 final-URL subject enforcement

Head `d6a9d14b407c21a9e27dc912b28482e51a70cec4`, branch `lane1/343-final-url`,
base `main` `eabe34b820001946a4dbeb28fc96d021fbd7ca5f`.

## What was still open

PR #647 (`fecc469`) admitted or rejected **search candidates** individually and
said so: validating a candidate's final URL after redirects, and semantic
relevance through the shared result reviewer, were the remaining acceptance
lines. #343 stayed open on that boundary.

## What changed

- `harness/web.py`: `_final_page_matches_subject(page, subject)` asks the
  subject question about a **fetched** page -- its final URL, its title and the
  text it would deliver -- so a redirect is judged where it lands.
  `gather_web_context` computes the subject from the query it will search and,
  when the fetched page does not name that subject, keeps the already-admitted
  snippet as the evidence instead of promoting unrelated page text. The
  rejection is emitted as `web_fetch` / `reject` / `off_subject_page`.
- With no named subject in the query the gate is inert, exactly as the
  candidate gate is, so topical searches keep their behaviour.

## Verification

- `tests/test_web.py::FinalUrlSubjectGateTests` (4): a page that never names the
  subject leaves only the admitted snippet; a page that names it still enriches
  with its text; the judgment uses the final URL the fetch landed on; a topical
  query keeps its page evidence.
- `tests/test_agent.py::TestWebCapabilityDisclosure::
  test_recorded_mixed_search_case_is_filtered_at_the_request_entry`: the
  recorded calculator/Microsoft-Exchange batch now runs through the real chat
  request path (`run_prompt(..., web=True)`) with the real parser and gate, only
  the HTTP seam patched; the delivered system prompt contains the calculator
  source and neither `Exchange` nor `mailbox`.
- Targeted suite: `tests/test_web.py tests/test_agent.py
  tests/test_architecture.py tests/test_request_lifecycle.py
  tests/test_checkpoint_context_binding.py` -- 300 passed, 29 subtests passed.
- `ruff check` clean on both changed files and both test files.

## What this does not claim

#343's acceptance also asks for the shared native result reviewer to judge
semantic relevance, and for rendered/interacted-page evidence to be
distinguished from snippets. Neither is implemented here. The issue stays open
on those lines; no closing credit is taken.
