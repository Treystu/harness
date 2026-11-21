CARRIER: blob:89eab7852d40
FIRST ACT: commit the #422 report-path cure on `lane/422-report-citation` (cut from `main` `280ee3d4`) and push it over the platform git, then record the push receipt in this filing.

# Lane 1 STATUS refresh - 2026-11-21, turn 2 (carrier v2)

**WAIT-STATE:** pending - the GitHub API writes (PR creation, issue comments,
merges) and the two-method census are gated on an authenticated API this
session does not have. **Work taken meanwhile:** the #422 report-path cure
(product code + test), its verification at the exact head, and this filing.
**Idle: none.** No turn of this lane ends on a pending check that could have
been advanced, and none of the work below needed the API.

**Base:** `main` `280ee3d4f99bf3d33645ddde21b243cebe0b191b`
(`git fetch origin main:refs/remotes/origin/main` this turn;
`git rev-parse HEAD` on the new branch = `280ee3d4` before the commit).
**Branch:** `lane/422-report-citation`, cut from that commit - not the diverged
`lane/burndown` (`86165805`, 136 commits diverged), not `main`.

---

## 1. What this turn delivered

**The #422 cure, as real product code.** `harness.citation_resolver` had no
product importer at `280ee3d4`; only its own test imported it. The
web-augmented answer - the report path that retrieves sources and returns their
provenance - now builds a citation audit before the result is returned:

- `harness/conversation_lifecycle.py` imports
  `REPORT_CITATION_TIMEOUT, RegistryResolver, audit_report_citations` at module
  level (static import, visible to an import census);
- `_report_citation_resolver()` is the product's resolver seam;
- `_report_citation_audit()` audits the turn's own sources and returns the
  artifact, failing open with a recorded reason;
- the result carries `"citation_audit"`: per-citation status, canonical DOI,
  `metadata_source`, unresolved list, summary, `report` counts, and the gate's
  display `label`;
- `harness/citation_resolver.py` gained `citation_records()` and
  `audit_report_citations()`: the mapping from gathered web sources onto
  `citation_verify`'s records, and the call into `audit_citations` with a
  resolver.

Rules kept, all of them the existing gate's: only what the retrieval returned
is supplied (an absent bibliography field stays absent), the
`citation_verified` label is never set by the report path, a rate-limited or
raising registry is recorded as evidence rather than promoted, and the audit is
bounded (`MAX_REPORT_CITATIONS = 3`, 5-second timeout).

Full detail and evidence: [422-report-path-cure.md](422-report-path-cure.md).

## 2. Verification at the exact head (commands and output)

```
$ uv run --no-project --with pytest --python 3.12 pytest tests/test_report_citation_422.py -q
....                                                                     [100%]
4 passed in 0.21s

$ uv run --no-project --with pytest --python 3.12 pytest tests/test_citation_resolver.py \
      tests/test_citation_verify.py tests/test_web.py tests/test_d12cov_audit_evidence.py -q
184 passed, 5 subtests passed in 4.10s

$ uv run --no-project --with pytest --python 3.12 pytest tests/test_agent.py -q
114 passed, 2 subtests passed in 3.63s

$ uv run --no-project --with ruff --python 3.12 ruff check \
      harness/conversation_lifecycle.py harness/citation_resolver.py tests/test_report_citation_422.py
All checks passed!
```

The new test drives the product entry (`run_prompt(..., web=True,
force_conversation=True)` -> `_handle_conversation`), not the resolver in
isolation, and asserts that the resolver the product builds is the one that
answers (`registry.calls == [DOI]`), that a matching registry record yields a
`supported` citation on the report, and that failures stay `not_verifiable` with
their reasons.

**Full suite** (three file chunks; one run exceeds this host's five-minute
command ceiling): `2069 passed` + `2196 passed, 1 failed` + `2413 passed,
1 failed`. The two failures are environmental and named in the cure filing:
`test_jev_chaos::test_roomy_budget` (wall-clock latency assertion tripped under
concurrent load; passes in isolation at this head, `3 passed`) and
`test_release_driver::test_interpreter_matrix_covers_ci_versions` (the host
lacks 3.9/3.11/3.13; pre-existing and already recorded in this repo).

## 3. Which queue items remain gated on GitHub API writes

| Queue item | Gated act | What is ready |
| --- | --- | --- |
| #467 record-and-close | comment on #467 + close | close text written in `467-measurement-record.md` (turn 1) |
| #644 / #469 | comment on #469; the W469 window | the intake cure is committed (`d1d8e7c` on the stand-up branch); the window is not run (no credit-billed runs this turn) |
| #646 register state | count correction | needs the census below; no number is guessed |
| #645 / #422 | PR for this branch, then the acceptance window | **this branch**; the acceptance window is not run this turn |
| #413 | block comment on #413 | block text written (turn 1); the host re-check stands |
| #475, #638, #466, #295 | disposition/retirement comments | not started; each is a GitHub write |
| Closeout, #294, #295 | two clean censuses | needs the census below |

## 4. Exact intended PR body for this branch (no re-deriving needed)

> **#422: wire the citation gate into the report path**
>
> **Head SHA:** `<head of lane/422-report-citation>` (refresh this line in the
> same act as any later commit, per AGENTS.md rule 9).
> **Base:** `main` `280ee3d4`.
>
> `harness.citation_resolver` (PR #645) had no product importer: only
> `tests/test_citation_resolver.py` imported it, so no user path could resolve
> a DOI and the register's line "the report-path call site is the remaining
> product wiring" described the whole remaining defect.
>
> This wires it into the web report path
> (`harness/conversation_lifecycle.py::_handle_conversation`), which is the
> lane that retrieves sources and returns their provenance:
>
> - module-level import of `RegistryResolver` / `audit_report_citations`;
> - `_report_citation_resolver()` seam and `_report_citation_audit()` artifact
>   builder, failing open with a recorded reason;
> - result field `citation_audit` with per-citation status, canonical DOI,
>   metadata source, unresolved list, summary, report counts and the gate's
>   label;
> - `harness/citation_resolver.py::citation_records()` and
>   `audit_report_citations()`: gathered web sources -> `citation_verify`
>   records -> `audit_citations(..., resolver=...)`.
>
> No new behaviour beyond the gate and the adapter #645 published: absent
> metadata stays absent (`metadata_absent`), failures are recorded
> (`resolver_rate_limited`, `resolver_error`), the `citation_verified` label is
> only ever the gate's, and the audit is bounded (3 citations, 5 s).
>
> **Verification (at this head):** `ruff check` clean on the three touched
> files; `tests/test_report_citation_422.py` 4 passed (drives
> `run_prompt(..., web=True, force_conversation=True)`); citation + web +
> audit-evidence suites 184 passed; `tests/test_agent.py` 114 passed.
> Full-suite chunks: 2069 + 2196 + 2413 passed, with `test_jev_chaos::
> test_roomy_budget` (latency, passes in isolation) and
> `test_release_driver::test_interpreter_matrix_covers_ci_versions`
> (host lacks 3.9/3.11/3.13, pre-existing) as the only failures.
>
> **Not in this PR:** the #422 acceptance window (not run), #469's window,
> #475's disposition, and any register count change.

## 5. Counts in the register this head contradicts, and the census still owed

The register of record (`docs/jev-roadmap.md`, "Canonical burndown register -
2026-11-19") prints a census at base `main` `b709e252` (35 open at that head,
37 by the two-method read). The mission checkpoint prints "33 open issues; 4
open PRs (#638 parked, #644, #645, #646)". **Neither is live at `280ee3d4`**:
`#644` (`a4dd345`), `#645` (`280ee3d4`), `#646` (`3a1946a`), `fecc469` (#343),
`6602e00` (#344) and `3816a65` (#626) have landed since the checkpoint, so at
least the "4 open PRs" figure is wrong and no count is restated here.

The exact commands still needed (authenticated API; two independent methods,
as the register's own rule requires):

```
gh issue list --state open --limit 400
gh api -X GET search/issues -f q='repo:Treystu/harness type:issue is:open' --jq '.total_count'
gh pr list --state open --json number,title,headRefName,isDraft
```

Until they run, this lane prints no number. The register will be corrected in
the same PR that changes it, with the census taken at that PR's base.

## 6. Push receipt

Recorded in the second commit after the push completed, verbatim, in
[push-receipt-02.md](push-receipt-02.md).

## 7. Lane state

- **DONE:** #422 report-path cure (code + test + ruff clean); focused and
  neighbouring suites green; full suite read with both failures named; branch
  cut from `main` `280ee3d4`; this filing.
- **WIP:** none uncommitted at push time.
- **NEXT:** #422's acceptance window can now be exercised (not run here); the
  #475 disposition draft; the register count once the census is available.
- **BLOCKERS:** authenticated GitHub API writes and the census. Nothing else.
- **DIRECTIVES:** the 2026-11-21 end-state instruction (product cure on a
  branch off current `main`, test at the product entry, push receipt in the
  filing, no landing claimed) - executed.
