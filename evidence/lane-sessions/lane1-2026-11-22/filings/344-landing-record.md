## Declined-retrieval control landed: PR #661 -> `03306b0e`

The declined-retrieval remainder named in this issue (`7076708495`) is closed by
PR **#661**, head `eb811806d86db9bba72d036cff18a360c6529f59`, merged as
`03306b0e6cfc8ea7d4d8bdd383c48e26f699cd32` on **16/16** `ci/circleci:`
contexts `success` at the exact head. Lucas Gate v2 `pass` (`53a37c65`); product
Jev `investigate` / `proceed` (0.06).

### What changed

`_checkpoint_context_reusable(checkpoint, prompt, *, retrieval_allowed=True)`
now returns `(False, "retrieval-declined")` when the checkpoint carries web
sources and the current effective turn does not allow retrieval. The call site
passes the decision after the workspace-inspection and no-tools overrides and
after a native web-research route promotion, so the gate reads the decision in
force rather than the raw argument. Context with no web evidence still reuses,
because there is nothing web-specific to be incompatible with. No checkpoint
schema field was added.

### Controls, through the public adapter

`run_hourglass_request` (what external local drivers call), not the predicate
alone:

- declined retrieval on resume: context rebuilt, answer judge receives the fresh
  context, result carries no sources and `web_used` false;
- changed request on resume: the old evidence is replaced by the new request's
  sources.

Plus predicate tests for the named reason and for declined turns with no web
evidence retaining their local context. 115 focused tests passed; ruff clean.

### Still named on this issue

- Approved-plan/receipt binding: the checkpoint has no plan-hash or
  Jev-approval-receipt field. Not invented here.
- Saved native-route reuse across a changed request: a resumed request with no
  caller preflight still inherits `checkpoint["route_preflight"]`. That is a
  routing-decision change and is left named rather than folded into an
  evidence-reuse PR.

The #343 remainder now lives in #660; this landing does not touch it.
