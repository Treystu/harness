# Fail closed when reviewer initialization fails

Part of #683, finding 77 (P2). Verified against `main` `8fc28a0e` on
2026-11-25: still present.

## Method

Code read of the named path at `8fc28a0e`: `harness/web.py` and the code it calls,
on 2026-11-25. No repository code changed in that act, so this is a read
of the shipped path, not a run and not a test.

## Result

harness/web.py:798-802 handles an absent reviewer by emitting `web_result_review_unavailable` and returning `ordered` unchanged: no verdict, no withholding, and no `reviewer` evidence-block entry (that entry is only appended on the `outage` branch at :838-845). harness/conversation_lifecycle.py:155-160 leaves `web_policy = None` when reviewer construction raises, so the outage path reaches this admission branch.

## The finding

When reviewer construction fails in `_handle_conversation`, its exception handler leaves `web_policy=None` and still calls the gatherer. This branch then admits every unpinned result without a verdict or an evidence-block outage disclosure. That is a reviewer setup outage, not the supported no-key case, which already has an explicit local verdict path in `evaluate_result_relevance`. Route an absent reviewer through the withholding/outage behavior rather than returning the original evidence.

## Scope of this issue

Route an absent reviewer through the same withholding and outage disclosure the fail-closed path uses, instead of returning the gathered evidence unchanged. A reviewer that could not be constructed is an outage, not the supported no-key case, which keeps its explicit local verdict path.

## Not claimed

- Not claimed: that the no-key path changes; the local fallback in `evaluate_result_relevance` still admits with a named method.
- Not claimed: that reviewer construction must succeed. The requirement is that its failure withholds results rather than admitting them.
- Not claimed: any change to the pinned admission rule for pages the request named.

## Acceptance

- `apply_result_review` with a reviewer that lacks `evaluate_result_relevance` withholds the unpinned results and appends the outage disclosure entry.
- The caller evidence block reads the outage rather than seeing the results as simply absent.
- A hermetic test passes a `None` policy and asserts no unpinned result survives.

Provenance: https://github.com/Treystu/harness/pull/665#discussion_r4658103563

