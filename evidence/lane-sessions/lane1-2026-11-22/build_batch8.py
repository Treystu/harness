"""Build the batch-8 verdict records (rows 85-89) from the fetched bodies."""
import json
import pathlib

ROOT = pathlib.Path('.')
BASE = ROOT / 'evidence/lane-sessions/lane1-2026-11-22'
src = json.load(open(BASE / '683-batch8-source.json', encoding='utf-8'))

EVIDENCE = {
    85: (
        'harness/conversation_lifecycle.py:574-585 binds `fetch_url_fn=_web.fetch_url` '
        'into `gather_web_context`, whose plan branch (harness/web.py:867-875) forwards it '
        'to `execute_plan` as the plan `fetch_fn`; `harness/research_plan.py:798-803` then '
        'calls `fetch_fn(url)` positionally while `harness/web.py:616-617` requires '
        '`allowed_hosts`. The hourglass seam at harness/hourglass_lifecycle.py:216-223 '
        'catches the resulting `TypeError` and continues with a `web tools error` note. '
        'This is the same integration failure row 81 files as #783.'),
    86: (
        'harness/hourglass_lifecycle.py:181-186 validates the accepted plan against the '
        'original `prompt`, then :216 gathers with `web_prompt or prompt`, and :1129-1133 '
        'builds `web_prompt` as `f"{prompt}\\nTarget site: https://{resolved_site}"` for a '
        'referential follow-up. `execute_plan` re-validates with that augmented text '
        '(harness/research_plan.py:749-751) and compares it to the plan hash bound at '
        'proposal time (:405-407), so the run ends `request_hash` with zero search and zero '
        'fetch; `plan_authorizes_url` (:815-822) also declines the renderer because a '
        'search-query proposal names no URL.'),
    87: (
        'Same call site as row 85 from the chat lane: '
        'harness/conversation_lifecycle.py:574-585 passes the production '
        '`harness.web.fetch_url` into `gather_web_context`, the plan branch forwards it to '
        '`execute_plan` (harness/web.py:867-875), and `_fetch_source` calls it with one '
        'positional argument (harness/research_plan.py:798-803) although `fetch_url` '
        'requires `allowed_hosts` (harness/web.py:616-617). The failure is caught by the '
        'chat lane web-tools handler (:293-296) and reported as a generic web-tools error. '
        'Filed once as #783, from row 81.'),
    88: (
        'harness/research_plan.py:686-697 wraps the plan evaluation in '
        '`except Exception`, re-raising only `ToolCancelled`, and records '
        '`state="unavailable"` with `reason=f"reviewer_error: {type(exc).__name__}"` while '
        '`record["cost"]` stays 0.0. `JevPolicy.evaluate_research_plan` '
        '(harness/jev_policy.py:2172-2174) re-raises `ProviderUsageUnknown` precisely so the '
        'known spend and unresolved liability are not discarded, so this handler converts '
        'billed-unknown usage into an ordinary outage and lets the lane continue.'),
    89: (
        'harness/research_plan.py:656-658 validates a saved receipt with `now=now`, and '
        '`decide_research_plan` defaults `now` to `None` (:616-619). `_approval_check` '
        'enforces expiry only when `now is not None` (:449-451), so a matching receipt with '
        '`expires_at=1` is accepted with `reused=True` and the reviewer is never called.'),
}

out = []
for r in src:
    r = dict(r)
    r['verdict'] = 'STILL PRESENT'
    r['evidence'] = EVIDENCE[r['row']]
    if r['row'] in (85, 87):
        r['filed_as'] = 783
        r['note'] = ('Same defect as row 81, already filed as #783; recorded here as a '
                     'cross-reference and no second issue is opened for it.')
    out.append(r)

json.dump(out, open(BASE / '683-batch8.json', 'w', encoding='utf-8'),
          indent=1, ensure_ascii=False)
print(len(out), 'rows')
for r in out:
    print(r['row'], r['verdict'], r.get('filed_as', ''))
