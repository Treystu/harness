## Lane 1 - #344 acceptance re-verified bullet by bullet

**Base:** `main` `eabe34b820001946a4dbeb28fc96d021fbd7ca5f`.
**Prior landing:** PR #648 (`6602e00d`), `_checkpoint_context_reusable` + `_request_identity` in `harness/hourglass_lifecycle.py`.

Read at the code, not from the PR description. #344 stays **open**: two
acceptance sentences have no implementation to point at.

| Acceptance line (issue text) | State | Evidence |
|---|---|---|
| Reuse research evidence only when bound to the same effective request | **covered** | `_checkpoint_context_reusable` requires `_request_identity(saved_prompt) == _request_identity(prompt)`; legacy checkpoints bind to their saved `prompt`; a checkpoint with no identity fails closed (`request-changed`) |
| ... approved plan/receipt ... | **not covered** | the checkpoint schema has no plan hash and no Jev approval receipt field; nothing binds reuse to an approved plan |
| ... and freshness policy | **covered** | web sources older than `_CONTEXT_REUSE_MAX_AGE_S` (300 s) are refused on **every** route, including a non-web answer route (`evidence-stale`); an unreadable age fails closed |
| A changed/declined research decision cannot inherit incompatible or stale web evidence | **partial** | changed request is refused; declined retrieval has no control - there is no declined-route/decision path in the reuse predicate at all |
| ... or stale native routing | **not covered** | `route_preflight` reuse (`hourglass_lifecycle.py:525-526` at the issue's line reference) is unchanged; a saved native route is still reused across a resume |
| Preserve legitimate continuation reuse | **covered** | `test_unchanged_request_with_fresh_evidence_is_reusable`, `test_evidence_just_inside_the_window_is_reusable`, `test_legacy_checkpoint_binds_to_its_saved_prompt`; the existing `tests/test_agent.py` battery still passes |
| ... and once-only known/unknown usage accounting | **not re-verified here** | untouched by #648; its accounting tests pass, but no new control was added for this line |
| Add focused changed-request, declined-retrieval and unchanged-request controls through the relevant lifecycle/public adapters | **partial** | `tests/test_checkpoint_context_binding.py` (10) covers changed-request and unchanged-request at the lifecycle predicate. There is **no declined-retrieval control**, and the controls exercise the predicate directly rather than a public adapter entry |

**What remains, named:** (a) a declined-retrieval control - a turn whose
research is declined must not reuse saved web evidence; (b) binding reuse to an
approved plan hash and Jev approval receipt (schema fields that do not exist
yet); (c) not reusing a saved native route across a changed request; (d) at
least one control driven through a public lifecycle adapter rather than the
predicate.
