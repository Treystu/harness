"""Generate the batch-7 sub-issue bodies from the verified verdicts."""
import json
import pathlib

ROOT = pathlib.Path('.')
BASE = ROOT / 'evidence/lane-sessions/lane1-2026-11-22/filings'
rows = json.load(open(ROOT / 'evidence/lane-sessions/lane1-2026-11-22/683-batch7.json',
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
    73: {
        'scope': (
            'Read the parent type before assigning a version, and omit `version` when the '
            'registry does not establish a classification this gate can stand behind. The '
            'subtype may still refine a published record; it must not upgrade a '
            'posted-content record to published.'),
        'not_claimed': [
            'Not claimed: that every Crossref type missing from the current tuple needs its '
            'own version string. The fix is to stop promoting posted-content, not to '
            'enumerate the registry.',
            'Not claimed: any change to how a missing `version` is scored elsewhere; omitting '
            'it is the registry saying it does not know.'],
        'acceptance': [
            'A record with `type: "posted-content"` and a subtype of working_paper, report or '
            'other is not stamped published.',
            '`verify_citation` no longer returns supported for a citation claiming '
            '`version: "published"` over such a record.',
            'A hermetic test injects the working-paper record the finding describes.'],
    },
    74: {
        'scope': (
            'Namespace the answer and review receipts by the context/request generation that '
            'produced them when a resume invalidates the checkpoint context, so round 1 of the '
            'new generation dispatches instead of replaying. Accounting history stays: the '
            'earlier receipts remain in the lifecycle usage and in known and unknown cost.'),
        'not_claimed': [
            'Not claimed: that every provider call must be invalidated. Route review, Jev '
            'review and the answer each decide reuse separately; this row is the answer '
            'receipt.',
            'Not claimed: that the old answer cost should be released. It was billed and stays '
            'billed.',
            'Not claimed: a tested reproducer in this filing; the finding own `run_prompt()` '
            'sequence is the reproduction to encode.'],
        'acceptance': [
            'A resume whose instruction changes the checkpoint request generation invokes the '
            'answer provider again for round 1.',
            'The previous generation receipts remain visible in the lifecycle accounting.',
            'A hermetic test runs the apples request, interrupts the review, and resumes with '
            'the changed instruction, asserting two provider invocations.'],
    },
    75: {
        'scope': (
            'Compare the IDs in the report claims against the IDs in citation_claims before '
            'granting the report-level label, and leave any uncovered claim unresolved with '
            'its own reason. The coverage check belongs beside the audit, not in the caller.'),
        'not_claimed': [
            'Not claimed: that citation_claims entries absent from claims are errors; the '
            'coverage requirement is one-directional.',
            'Not claimed: any change to the claim-support bands.',
            'Not claimed: that the fixture c2 must be assessed by a semantic judge; unresolved '
            'is the honest outcome when it has no assessment.'],
        'acceptance': [
            'A report whose claims section contains an ID missing from citation_claims cannot '
            'be labeled citation_verified.',
            'The uncovered claim appears in the unresolved list with a reason naming the gap.',
            'A hermetic test adds an unsupported claim to the report claims and asserts a '
            'non-zero exit from lint-claims.'],
    },
    76: {
        'scope': (
            'Use `_settle_cancelled(reservation, exc)` on the reviewer cancellation path, as '
            'the other evaluation methods do, so a known charge is booked and unknown '
            'liability is retained. No other path in `evaluate_result_relevance` changes.'),
        'not_claimed': [
            'Not claimed: that the reviewer outage handling changes; a cancellation still '
            'propagates to the caller.',
            'Not claimed: that unknown liability blocks later calls forever; it is retained, '
            'subject to the existing reconciliation.',
            'Not claimed: any behaviour for the spend-limit path, which already routes through '
            '`_release_after_provider_limit`.'],
        'acceptance': [
            '`evaluate_result_relevance` books known cost and retains unknown liability when '
            'it raises ProviderUsageUnknown or a post-dispatch ToolCancelled.',
            'The governor spent, outstanding and unknown figures reflect that liability after '
            'the raise.',
            'A hermetic test drives each exception through the reviewer and asserts the '
            'governor figures.'],
    },
    77: {
        'scope': (
            'Route an absent reviewer through the same withholding and outage disclosure the '
            'fail-closed path uses, instead of returning the gathered evidence unchanged. A '
            'reviewer that could not be constructed is an outage, not the supported no-key '
            'case, which keeps its explicit local verdict path.'),
        'not_claimed': [
            'Not claimed: that the no-key path changes; the local fallback in '
            '`evaluate_result_relevance` still admits with a named method.',
            'Not claimed: that reviewer construction must succeed. The requirement is that its '
            'failure withholds results rather than admitting them.',
            'Not claimed: any change to the pinned admission rule for pages the request '
            'named.'],
        'acceptance': [
            '`apply_result_review` with a reviewer that lacks `evaluate_result_relevance` '
            'withholds the unpinned results and appends the outage disclosure entry.',
            'The caller evidence block reads the outage rather than seeing the results as '
            'simply absent.',
            'A hermetic test passes a `None` policy and asserts no unpinned result survives.'],
    },
    78: {
        'scope': (
            'Return the review receipt beside the sources and accumulate it into the caller '
            'cost accounting, including billed outage responses. The sources list stays the '
            'shape every consumer already reads; the cost travels with it.'),
        'not_claimed': [
            'Not claimed: that the reviewer settlement changes; it already books the charge in '
            'the governor. The gap is that the request lifecycle never learns it.',
            'Not claimed: a schema for every retrieval result; only the review receipt cost is '
            'carried.',
            'Not claimed: that the hourglass continuation is the only consumer; conversation '
            'result cost is the other.'],
        'acceptance': [
            'A billed relevance review contributes to conversation result cost and to the '
            'hourglass total cost and checkpoint known cost.',
            'An hourglass continuation reconstructing its governor from the checkpoint does not '
            'regain that spend.',
            'A hermetic test bills one review and asserts the recorded cost.'],
    },
    79: {
        'scope': (
            'Bind the route-review provider-call identity to the binding the judgment was made '
            'under: the request generation and, when a plan is in play, the plan hash. A '
            'rejected reuse predicate must produce a fresh review, not the cached decision. '
            'The plan half is the same defect the census files separately as row 83, so this '
            'issue owns both and no second issue is filed for it.'),
        'not_claimed': [
            'Not claimed: that an unchanged continuation must pay for a second review; reuse '
            'for an identical request and plan stays.',
            'Not claimed: that `evaluate_request_workflow` changes.',
            'Not claimed: any behaviour for a checkpoint with no completed route receipt, '
            'which already reviews fresh.'],
        'acceptance': [
            'A changed request against a persisted lifecycle containing a completed '
            'route-review receipt runs a fresh route evaluation.',
            'A changed plan does the same, and the saved route preflight is recorded under the '
            'plan that was actually judged.',
            'A hermetic test persists a lifecycle with a completed route receipt and resumes '
            'with a different request, asserting two evaluations.'],
    },
    80: {
        'scope': (
            'Build the receipt from the binding fields the judgment carries and verify them '
            'against the plan, instead of restamping the supplied plan. A judgment that does '
            'not name the plan it judged cannot become an accepting approval.'),
        'not_claimed': [
            'Not claimed: that `validate_plan` needs a second gate; it already compares the '
            'receipt to the plan. The gap is that the receipt was manufactured from the plan '
            'in the first place.',
            'Not claimed: any change to the question pack or the bands.',
            'Not claimed: that a judgment carrying no binding fields must still be usable; '
            'unavailable is the honest result.'],
        'acceptance': [
            '`approval_from_judgment` cannot produce an accepting approval whose binding '
            'differs from the judgment.',
            'An acceptance for one plan no longer authorizes a different plan execution.',
            'A hermetic test passes a judgment for plan A with plan B and asserts a declining '
            'or unavailable approval.'],
    },
    81: {
        'scope': (
            'Pass an adapter that supplies the configured fetch policy, so the default '
            'transport receives the allowlist, the any-public exemption and the named hosts '
            'exactly as the legacy path does. One-argument test doubles stay valid, which is '
            'why the adapter is the fix rather than a second required parameter.'),
        'not_claimed': [
            'Not claimed: that the `fetch_url` signature changes; the legacy seam keeps its '
            'shape.',
            'Not claimed: that every injected fetcher must accept policy arguments. An '
            'injected callable that already binds policy is left alone.',
            'Not claimed: any behaviour for a plan with no URL query.'],
        'acceptance': [
            'An accepted URL plan executes with the default transport without raising '
            'TypeError.',
            'The fetch it performs applies the configured allowlist and the any-public and '
            'named-host exemptions.',
            'A hermetic test runs a URL plan through the default path with a stubbed transport '
            'and asserts the policy reached it.'],
    },
    82: {
        'scope': (
            'Enforce the plan max_sources across search and fetch results, so the sources '
            'returned never exceed the budget the reviewed plan carried. The per-query '
            'max_results stays as it is.'),
        'not_claimed': [
            'Not claimed: that the plan validation changes; max_sources is already banded '
            'there.',
            'Not claimed: that a truncated run must report insufficient evidence; the bound is '
            'a ceiling, not a target.',
            'Not claimed: any behaviour for a single-query plan whose max_results already '
            'fits.'],
        'acceptance': [
            'A plan whose queries would produce more than max_sources sources returns at most '
            'max_sources.',
            'The bound applies across search and fetch sources together.',
            'A hermetic test uses two searches with max_results 3 and max_sources 1 and '
            'asserts one source.'],
    },
    84: {
        'scope': (
            'When the live request carries the identical plan and no replacement approval, '
            'keep the receipt the checkpoint already holds instead of serializing an empty '
            'non-native one. A receipt the predicate rejected is not preserved as approval '
            'evidence.'),
        'not_claimed': [
            'Not claimed: that a rejection should be preserved as if it were an acceptance; '
            'only a receipt that already justified reuse survives.',
            'Not claimed: that `saved_plan_approval` gets looser; its strict rebuild is what '
            'keeps adoption honest.',
            'Not claimed: any behaviour for a non-resume call, which has no saved receipt to '
            'preserve.'],
        'acceptance': [
            'Resuming with the same plan and no plan approval leaves the recorded receipt '
            'intact.',
            'The next continuation of that unchanged plan still passes the route binding '
            'instead of failing plan-receipt-not-native.',
            'A hermetic test resumes twice and asserts the second continuation reuses the '
            'original receipt.'],
    },
}

for row in [73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 84]:
    r = by[row]
    e = EXTRA[row]
    lines = ['# ' + r['title'], '']
    cp = ('Part of #683, finding {} ({}). Verified against `main` `8fc28a0e` on'
          .format(row, r['priority']))
    if row == 79:
        cp += ('\n2026-11-25: still present. This issue also covers finding 83, the\n'
               'same unbound route-review key under a changed plan.')
    else:
        cp += '\n2026-11-25: still present.'
    lines += [cp, '']
    lines += ['## Method', '',
              'Code read of the named path at `8fc28a0e`: `{}` and the code it calls,'.format(r['file']),
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
