## Lane 1 - #343 acceptance re-verified bullet by bullet, and the final-URL line landed

**Base:** `main` `eabe34b820001946a4dbeb28fc96d021fbd7ca5f`, zero open PRs before this landing.
**Landing:** PR #658, head `d6a9d14b407c21a9e27dc912b28482e51a70cec4`, merged as `4fa960ce7e5ecd08125fa317e0fff70cee615b65` on 16/16 `ci/circleci:` contexts `success`, zero pending, zero failing, read at that exact head immediately before the merge. Lucas Gate v2 `pass` (`360b203e`); product Jev `investigate` / `proceed` (0.05, `jev-1.14.0`).

The issue stays **open**. Two acceptance lines are still not implemented, so no
closure credit is taken.

| # | Acceptance line (issue text) | State | Where |
|---|---|---|---|
| 1 | Enforce accepted target-domain requirements on each candidate and its final fetched URL; one matching hit cannot admit unrelated neighbours | **covered** | `web.admit_candidates` (per candidate, #647 `fecc469`) + `web._final_page_matches_subject` / `gather_web_context` (#658 `d6a9d14b`): the page a candidate resolves to is judged on the final URL, title and delivered text, so a redirect is judged where it lands, and a page that never names the subject keeps only the admitted snippet |
| 2 | Use the shared native result reviewer for semantic relevance where needed; uncertain/rejected content must not become answer evidence | **not covered** | `harness/web.py` has no reviewer call; relevance is the case-insensitive subject-label test only |
| 3 | Preserve source/provenance and explicit insufficient-evidence behaviour; snippets cannot stand in for rendered/interacted-page evidence | **partial** | provenance is kept per source (`kind` fetch/search, url, title) and an all-off-subject batch still refuses with `off_subject_results`; a snippet is still delivered as `kind: "search"` text with no statement that it is unrendered |
| 4 | Cover the recorded mixed calculator/Microsoft case through a request entry point, with actual filtering assertions and no fabricated live-model proof | **covered** | `tests/test_agent.py::TestWebCapabilityDisclosure::test_recorded_mixed_search_case_is_filtered_at_the_request_entry` drives the real chat request path (`run_prompt(..., web=True)`) with the real parser and gate; only the HTTP seam is patched, and the delivered system prompt is asserted to carry the calculator source and neither `Exchange` nor `mailbox` |

**Verification at the landing head:** `tests/test_web.py`, `tests/test_agent.py`,
`tests/test_architecture.py`, `tests/test_request_lifecycle.py`,
`tests/test_checkpoint_context_binding.py` -> 300 passed, 29 subtests passed;
`ruff check` clean on the changed files.

**What remains, named:** (a) the shared native result reviewer for semantic
relevance, with rejected/uncertain content barred from evidence; (b) making the
snippet-versus-rendered distinction explicit in what the model is given. Those
are what this issue now means; the target-domain lines are closed as behaviour,
not by dismissing them.
