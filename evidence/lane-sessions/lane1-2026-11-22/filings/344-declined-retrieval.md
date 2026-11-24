# #344: a resumed request that declines retrieval cannot inherit saved web evidence

Head: `eb811806d86db9bba72d036cff18a360c6529f59` (branch
`lane1/344-declined-retrieval`, base `main` `32f8f84`).

## The defect this closes

`_checkpoint_context_reusable` bound a resumed checkpoint to the request
identity, the workspace inventory and a 300 s freshness window. It did not bind
it to the *retrieval decision*. So a checkpoint that held live web evidence
could be resumed by a turn that declined retrieval (`web=False`, e.g. an
operator who turned web off before continuing) and still hand the answer model
the old sources: `request-changed` did not fire because the request text was
unchanged, and `evidence-stale` did not fire because the evidence was fresh.
The answer then cited material the current request never asked for. This is the
declined-retrieval case named in #344's acceptance list.

## The change

`harness/hourglass_lifecycle.py`

- `_checkpoint_context_reusable(checkpoint, prompt, *, retrieval_allowed=True)`
  now returns `(False, "retrieval-declined")` when the checkpoint carries web
  sources and the current effective turn does not allow retrieval. The reason is
  recorded on the `chat_context` event like every other why-not.
- The call site passes the effective decision (`retrieval_allowed=web`), which is
  resolved *after* the workspace and no-tools overrides and the native
  web-research route promotion, so the gate sees the decision actually in force
  rather than the raw argument.
- Context without web evidence is unaffected: a declined turn still continues
  from its saved local context, because there is nothing web-specific to be
  incompatible with.

No checkpoint schema change: the decision is already recorded per turn, and the
predicate reads the current one.

## Controls, through the public adapter

`tests/test_jev_answer_lifecycle.py` drives `run_hourglass_request` (the adapter
external local drivers call), not the predicate in isolation:

- `test_declined_retrieval_on_resume_rebuilds_instead_of_reusing_evidence`: a
  fresh checkpoint holding web evidence, resumed with `web=False` and a native
  answer route. Context is rebuilt, the answer judge receives the fresh context,
  and the result carries no sources and `web_used` false.
- `test_changed_request_on_resume_rebuilds_context_through_public_adapter`: the
  changed-request case through the same adapter; the old evidence is replaced by
  the new request's sources.

`tests/test_checkpoint_context_binding.py` pins the predicate directly: the
declined case returns the named reason, and a declined turn with no web evidence
still reuses its local context.

## Verification at this head

- `uv run --no-project --with pytest --python 3.12 pytest
  tests/test_checkpoint_context_binding.py tests/test_jev_answer_lifecycle.py
  tests/test_shared_lifecycle.py -q` -> 115 passed, 6 subtests passed.
- `ruff check harness/hourglass_lifecycle.py tests/test_checkpoint_context_binding.py
  tests/test_jev_answer_lifecycle.py` -> clean.
- CI is read at this exact head from the CircleCI commit statuses; the merge
  follows only that read.

## Not in this change, still named on #344

- Approved-plan/receipt binding: the checkpoint has no plan-hash or
  Jev-approval-receipt field, and this change does not invent one.
- Saved native-route reuse across a changed request: the resumed request still
  inherits `checkpoint["route_preflight"]` when the caller supplies none. That
  is a routing-decision change, not an evidence-reuse one, and it is left named
  rather than smuggled in here.

The #343 remainder (shared native result reviewer, snippet-versus-rendered
distinction) is filed as #660 and is not touched by this PR.
