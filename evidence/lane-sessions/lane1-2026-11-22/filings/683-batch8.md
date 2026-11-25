# #683 batch 8 - rows 85-89 verified against main (census complete)

This is a disposition comment for the #683 tracker. It closes nothing and takes
no completion credit.

## Method

Each row was checked by reading the exact code path the finding names in
`origin/main` at `8fc28a0e`, on 2026-11-25. A row is FIXED only when the shipped
code now does what the finding asked; it is STILL PRESENT when the path the
finding describes is still reachable. No repository code changed in this act, so
every verdict is a code read and no new test was run.

Rows 85 and 87 describe the same integration failure as row 81, which is
already filed as #783. They are recorded here as STILL PRESENT with that
cross-reference and get no new issue; filing them again would create three
issues for one call site.

## Result: 0 FIXED, 5 STILL PRESENT, 0 NOT APPLICABLE

| Row | File | Finding | Verdict |
| --- | --- | --- | --- |
| 85 | harness/conversation_lifecycle.py | Bind the fetch policy before passing the real fetch function | STILL PRESENT (#783) |
| 86 | harness/hourglass_lifecycle.py | Keep the request binding unchanged when resolving a remembered site | STILL PRESENT |
| 87 | harness/conversation_lifecycle.py | Bind fetch policy arguments before executing chat plans | STILL PRESENT (#783) |
| 88 | harness/research_plan.py | Propagate unknown provider usage instead of treating it as an outage | STILL PRESENT |
| 89 | harness/research_plan.py | Check receipt expiry when the caller omits now | STILL PRESENT |

## The still-present rows

- **85** `harness/conversation_lifecycle.py:574-585` binds
  `fetch_url_fn=_web.fetch_url` into `gather_web_context`, whose plan branch
  (`harness/web.py:867-875`) forwards it to `execute_plan` as the plan's
  `fetch_fn`; `harness/research_plan.py:798-803` then calls `fetch_fn(url)`
  positionally while `harness/web.py:616-617` requires `allowed_hosts`. The
  hourglass seam at `harness/hourglass_lifecycle.py:216-223` catches the
  resulting `TypeError` and continues with a `web tools error` note. Same
  integration failure as row 81, filed as #783.
- **86** `harness/hourglass_lifecycle.py:181-186` validates the accepted plan
  against the original `prompt`, then `:216` gathers with
  `web_prompt or prompt`, and `:1129-1133` builds `web_prompt` as
  `f"{prompt}\nTarget site: https://{resolved_site}"` for a referential
  follow-up. `execute_plan` re-validates with that augmented text
  (`harness/research_plan.py:749-751`) and compares it to the hash bound at
  proposal time (`:405-407`), so the run ends `request_hash` with zero search and
  zero fetch. `plan_authorizes_url` (`:815-822`) also declines the renderer,
  because a search-query proposal names no URL.
- **87** The same call site as row 85 from the chat lane:
  `harness/conversation_lifecycle.py:574-585` passes the production
  `harness.web.fetch_url` into `gather_web_context`, the plan branch forwards it
  to `execute_plan`, and `_fetch_source` calls it with one positional argument.
  The chat lane's web-tools handler catches the failure and reports a generic
  error. Filed once as #783, from row 81.
- **88** `harness/research_plan.py:686-697` wraps the plan evaluation in
  `except Exception`, re-raising only `ToolCancelled`, and records
  `state="unavailable"` with `reason=f"reviewer_error: ..."` while
  `record["cost"]` stays `0.0`. `JevPolicy.evaluate_research_plan`
  (`harness/jev_policy.py:2172-2174`) re-raises `ProviderUsageUnknown` precisely
  so known spend and unresolved liability are not discarded, so this handler
  turns billed-unknown usage into an ordinary outage and the lane continues.
- **89** `harness/research_plan.py:656-658` validates a saved receipt with
  `now=now`, and `decide_research_plan` defaults `now` to `None` (`:616-619`).
  `_approval_check` enforces expiry only when `now is not None` (`:449-451`), so
  a matching receipt with `expires_at=1` is accepted with `reused=True` and the
  reviewer is never called.

Machine-readable: `evidence/lane-sessions/lane1-2026-11-22/683-batch8.json`,
where each row carries its verdict, evidence, finding body, discussion url and,
where it applies, the issue that already owns the defect.

## Not claimed

- Not claimed: that the census severities were re-derived. They are the
  census's.
- Not claimed: any runtime reproduction; every verdict is a code read at
  `8fc28a0e`.
- Not claimed: that #783's fix reaches rows 86-89. Those three are separate and
  get their own issues.

## Running totals for #683

The census is complete: rows 1-89 of 89 are verified.
**22 FIXED, 67 STILL PRESENT, 0 NOT APPLICABLE.**

Every still-present row has a filed sub-issue except the two this batch records
as duplicates of #783 (rows 85 and 87), so the tracker is closeable only when
those issues land, not before. Each one names the path, the line and the
acceptance a fix must meet.

## Next for this issue

Sub-issues for rows 86, 88 and 89, gated like #749-#785: #786 (row 86), #787
(row 88), #788 (row 89). Rows 85 and 87 are covered by #783. Next: the
reviewed-PR queue (#649, #650, #651, #652, then #703) and the O1 efficiency
package.
