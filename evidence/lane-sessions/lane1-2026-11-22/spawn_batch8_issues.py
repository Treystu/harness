"""Generate the batch-8 sub-issue bodies (rows 86, 88, 89)."""
import json
import pathlib

ROOT = pathlib.Path('.')
BASE = ROOT / 'evidence/lane-sessions/lane1-2026-11-22/filings'
rows = json.load(open(ROOT / 'evidence/lane-sessions/lane1-2026-11-22/683-batch8.json',
                      encoding='utf-8'))
by = {r['row']: r for r in rows}


def finding_body(body):
    keep = []
    for ln in body.splitlines():
        s = ln.strip()
        if s.startswith('**<sub><sub>!['):
            continue
        if s.startswith('Useful? React with'):
            continue
        if s.startswith('<!-- codex-code-review-finding'):
            continue
        keep.append(ln)
    return '\n'.join(keep).strip()


EXTRA = {
    86: {
        'scope': (
            'Resolve the remembered target before the plan is drafted, so the proposal, the '
            'approval and the execution all bind to one request text. The original prompt '
            'stays the binding source; if the target must be appended for retrieval, it is '
            'appended before `decide_research_plan` sees the text, not after.'),
        'not_claimed': [
            'Not claimed: that the referential-follow-up wording changes.',
            'Not claimed: that the plan may be re-proposed after approval; the fix moves the '
            'resolution earlier, it does not add a second judgment.',
            'Not claimed: any behaviour for a follow-up that names no remembered site.'],
        'acceptance': [
            'A referential follow-up with a remembered site runs a plan whose `request_hash` '
            'matches the text execution validates against.',
            'The remembered target reaches the plan as a named URL query, so the renderer may '
            'act on it.',
            'A hermetic test resolves a remembered site and asserts a non-zero search or '
            'fetch count.'],
    },
    88: {
        'scope': (
            'Re-raise `ProviderUsageUnknown` beside `ToolCancelled` instead of converting it '
            'into a zero-cost unavailable record, so the known spend and unresolved liability '
            'reach the lifecycle. An ordinary reviewer failure keeps the recoverable outage '
            'path; a billed-unknown outcome does not.'),
        'not_claimed': [
            'Not claimed: that every exception must propagate; a refusal or transport error '
            'stays a recoverable outage with retrieval closed.',
            'Not claimed: any change to how the lane records an outage.',
            'Not claimed: that the lane must fail; it must account for the unknown charge '
            'before it continues.'],
        'acceptance': [
            '`decide_research_plan` propagates `ProviderUsageUnknown` rather than returning an '
            'unavailable record.',
            'The known spend and unknown liability from that call reach the governor and the '
            'request lifecycle.',
            'A hermetic test raises `ProviderUsageUnknown` from the plan evaluation and '
            'asserts it escapes.'],
    },
    89: {
        'scope': (
            'Resolve the current time when the caller omits `now`, before validating a saved '
            'receipt, so an expired consent falls through to a fresh judgment instead of being '
            'adopted. A caller that supplies `now` keeps its value.'),
        'not_claimed': [
            'Not claimed: that `validate_plan` should invent a clock for every caller; the '
            'default resolution belongs at the decision entry that adopts saved receipts.',
            'Not claimed: any change to the expiry window or the consent lifetime.',
            'Not claimed: that a fresh judgment must be refused when consent expired; it is '
            'simply asked again.'],
        'acceptance': [
            'A saved receipt whose `expires_at` has passed is not adopted, even when the caller '
            'omits `now`.',
            'The expired case reports `consent_stale` and proceeds to a fresh evaluation.',
            'A hermetic test passes a saved receipt with `expires_at=1` and no `now` and '
            'asserts the reviewer is called.'],
    },
}

for row in [86, 88, 89]:
    r = by[row]
    e = EXTRA[row]
    lines = ['# ' + r['title'], '']
    lines += ['Part of #683, finding {} ({}). Verified against `main` `8fc28a0e` on'.format(
        row, r['priority']),
        '2026-11-25: still present.', '']
    lines += ['## Method', '',
              'Code read of the named path at `8fc28a0e`: `{}` and the code it calls,'.format(
                  r['file']),
              'on 2026-11-25. No repository code changed in that act, so this is a read',
              'of the shipped path, not a run and not a test.', '']
    lines += ['## Result', '', r['evidence'], '']
    lines += ['## The finding', '', finding_body(r['body']), '']
    lines += ['## Scope of this issue', '', e['scope'], '']
    lines += ['## Not claimed', '']
    lines += ['- ' + n for n in e['not_claimed']]
    lines += ['', '## Acceptance', '']
    lines += ['- ' + a for a in e['acceptance']]
    lines += ['', 'Provenance: ' + r['url'], '']
    p = BASE / '683-row{}-issue.md'.format(row)
    p.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('row', row, len(lines), 'lines')
