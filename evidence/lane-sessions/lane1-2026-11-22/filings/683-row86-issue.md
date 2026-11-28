# Keep the request binding unchanged when resolving a remembered site

Part of #683, finding 86 (P2). Verified against `main` `8fc28a0e` on
2026-11-25: still present.

## Method

Code read of the named path at `8fc28a0e`: `harness/hourglass_lifecycle.py` and the code it calls,
on 2026-11-25. No repository code changed in that act, so this is a read
of the shipped path, not a run and not a test.

## Result

harness/hourglass_lifecycle.py:181-186 validates the accepted plan against the original `prompt`, then :216 gathers with `web_prompt or prompt`, and :1129-1133 builds `web_prompt` as `f"{prompt}\nTarget site: https://{resolved_site}"` for a referential follow-up. `execute_plan` re-validates with that augmented text (harness/research_plan.py:749-751) and compares it to the plan hash bound at proposal time (:405-407), so the run ends `request_hash` with zero search and zero fetch; `plan_authorizes_url` (:815-822) also declines the renderer because a search-query proposal names no URL.

## The finding

For a web-enabled follow-up such as “audit the same site as before,” `run_hourglass_request` proposes and approves a plan bound to the original `prompt`, then appends the remembered target to `web_prompt`. Passing that augmented text into the plan-aware gatherer makes `execute_plan` reject it with `request_hash`, so neither search nor fetch runs. The renderer also skips the remembered target because the original proposal contains only a search query, not that URL. Resolve the remembered target before drafting the plan while preserving the original request text for binding validation; otherwise the existing same-site follow-up path silently loses all retrieval.

## Scope of this issue

Resolve the remembered target before the plan is drafted, so the proposal, the approval and the execution all bind to one request text. The original prompt stays the binding source; if the target must be appended for retrieval, it is appended before `decide_research_plan` sees the text, not after.

## Not claimed

- Not claimed: that the referential-follow-up wording changes.
- Not claimed: that the plan may be re-proposed after approval; the fix moves the resolution earlier, it does not add a second judgment.
- Not claimed: any behaviour for a follow-up that names no remembered site.

## Acceptance

- A referential follow-up with a remembered site runs a plan whose `request_hash` matches the text execution validates against.
- The remembered target reaches the plan as a named URL query, so the renderer may act on it.
- A hermetic test resolves a remembered site and asserts a non-zero search or fetch count.

Provenance: https://github.com/Treystu/harness/pull/673#discussion_r4659547472

