# Lane 1 turn 2 filings - 2026-11-21 (carrier v2)

**Base:** `main` `280ee3d4f99bf3d33645ddde21b243cebe0b191b`.
**Branch:** `standup/lane1-2026-11-21`.
**Character of this turn:** the transport test the previous turn owed was run
and passed (receipt in `status-refresh-01.md`); the queue then continued on the
surfaces that work (git + local execution), and every act still needing the
authenticated API is filed here with its exact intended content.

---

## 1. #467 - record-and-close, close-ready

See `467-measurement-record.md` in this directory: the published measurement
(`6991530885`, 27 receipted rows), its artifact on `main` by PR #626
(`3816a65`), the nine-cell frozen sweep (false-proceed 0.0 in every cell;
16/28 best, 14/28 at the shipped 0.95), cost `$0.00067759`, no replay
mismatches, and the close comment text. The count is **no longer provisional**:
the register's condition was "#626 lands", and #626 is an ancestor of `main`
`280ee3d4`.

---

## 2. #644 review findings - the one that was still live is now cured, in code and in the register

### 2.1 The finding, as it was recorded

`docs/found-in-use.md` carried, at `17906e2c`:

> `campaign-trace-writer-unwired` ... open - high: `harness/flush_loop.py:392-396`
> forwards each campaign event to `DecisionTrace.campaign_event` only when a
> writer is injected, and no product call site injects one ... the writer is
> green only because `tests/test_decision_trace_469.py:235-236` constructs it
> by hand, so #627's campaign retention is inert in use

### 2.2 Re-read at `280ee3d4` - the finding no longer holds

| Claim the row made | State at `280ee3d4` |
| --- | --- |
| no product call site injects a writer | **false now** - `harness/flush_loop.py:1299` builds `EventLedger(chosen_ledger, trace=campaign_trace(trace_path))` inside the campaign entry |
| ... so campaigns are inert in use | **false now** - `campaign_trace` (`harness/flush_loop.py:642`) resolves the default sink from `load_settings().ledger_path` when no path is passed, so a default `harness flush --campaign` retains its events |
| only a hand-constructed writer was ever exercised | **false now** - `tests/test_decision_trace_469.py:385::test_a_product_campaign_run_retains_its_events` drives the product entry |

Landed by PR #644 (`a4dd345`, "fix(flush): wire the campaign trace writer at
the product entry (#469)"), which is an ancestor of `main` `280ee3d4`.

### 2.3 Executed at `280ee3d4` (not read - run)

```
uv run --no-project --with pytest --python 3.12 pytest tests/test_decision_trace_469.py -q
..............................                                           [100%]
30 passed in 0.27s
```

Including `test_a_product_campaign_run_retains_its_events`,
`test_the_trace_retains_a_stop_row_with_its_evidence`,
`test_the_writer_can_be_disabled_explicitly`,
`test_an_empty_trace_path_is_a_disabled_writer` and
`test_an_unreadable_trace_ledger_does_not_abort_the_campaign` - so the wiring
is not merely present, it fails open as documented.

### 2.4 The car

`docs/found-in-use.md`: the row is flipped from `open` to **cured 2026-11-21**
with the file:line and the test name quoted above, in the same act that proves
it. No other row is touched; the two neighbours (`audit-traces-not-persisted`,
`flush-campaign-ledgers-uncommitted`) stay `open` because #644 does not cure
what they describe: the first is the family-wide trace inventory (#468's
assessment distributions are still not written), the second is the pre-#627
"no archive exists" row.

**What this does not do:** it does not close #469. #469's close is its W469
measurement window under the filed protocol (`7003243188`, `7010349175`), and
the register already carries the landing as "cured by PR #644, the window opens
at the first real campaign start". Curing the finding and running the window
are two acts; this turn did the first.

---

## 3. #645 / #422 - the resolver landed, the call site did not: #422 is NOT acceptible end-to-end, and here is the evidence

The mission's item 4 says: land #645, then run the #422 end-to-end acceptance
live. #645 is already on `main` (`280ee3d4`) and its tests are green:

```
uv run ... pytest tests/ -q -k "citation"
66 passed, 7552 deselected in 5.81s
```

But the acceptance cannot be run, for a reason that is a finding rather than a
supply problem:

```
$ grep -rn "citation_resolver\|CitationResolver\|DoiResolver" --include=*.py harness/ tests/ \
    | grep -v "^harness/citation_resolver.py"
tests/test_citation_resolver.py:9:from harness.citation_resolver import (
```

**The resolver has no product caller at `280ee3d4`.** Its only importer is its
own test file. So:

- #422's citation gate cannot resolve a DOI in use, because nothing in the
  product calls the resolver;
- the register's line "the report-path call site is the remaining product
  wiring" is **still true** at this head, and #645 landing did not change it;
- an "end-to-end acceptance" run at this head would measure a path that does not
  exist, so this filing does not fake one. #422 stays open on the wiring, which
  is the next actionable lane item (a real code car, not a re-measurement).

This is a decision point with deciding evidence rather than a blocker: the lane
can write the call site next; what it cannot do is claim the acceptance.

---

## 4. #413 - re-checked this turn, still host-side, filed as the mission directs

The mission's item 5 instructs: if the loopback driver service cannot be
started, file the block and proceed. Re-checked, exact output:

```
$ ss -ltn | grep 8791            -> no listener tool output (nothing bound)
$ python3 -c 'socket.connect(("127.0.0.1",8791))'
REFUSED: ConnectionRefusedError [Errno 111] Connection refused
$ command -v driver-core        -> driver-core NOT on PATH
DISPLAY=unset DRIVER_SCREEN=unset DRIVER_ALLOW_WRITE=unset
```

The round-trip needs a perception source and an input backend; this host has
neither, and the driver service is not startable here (no display, no installed
console entry point). **Block stands, filed.** What would unblock it, named
exactly: a host with `DISPLAY`/a virtual display plus the `driver-core` entry
point installed, and `DRIVER_SCREEN` pointing at a real capture.

---

## 5. #646 - the register count cannot be corrected without the live census

The register's own rule is that its census is taken two ways at the PR's base.
Both reads need the authenticated API. Named act, unchanged from the stand-up:

```
gh issue list --state open --limit 400
gh api -X GET search/issues -f q='repo:Treystu/harness type:issue is:open' --jq '.total_count'
gh pr list --state open --json number,title,headRefName,isDraft
```

Until those run, this lane does not restate the checkpoint's "33 open / 4 open
PRs" as live, because six landings have happened since (`a4dd345`, `280ee3d4`,
`3a1946a`, `fecc469`, `6602e00`, `3816a65`).

---

## 6. Blocked API acts this turn, with exact intended content

| # | Act | Exact intended content |
| --- | --- | --- |
| 1 | Comment on #295 | the check-in block in `status-refresh-01.md`, plus one line: "turn 2: #467 record filed; `campaign-trace-writer-unwired` cured by #644 and corrected in the intake; #422 has no product call site at `280ee3d4`" |
| 2 | Comment on #467 and close | the close text in `467-measurement-record.md` section 5 |
| 3 | Comment on #469 | "the `campaign-trace-writer-unwired` finding is cured by PR #644 at `280ee3d4`: product entry injects the writer (`flush_loop.py:1299`), default sink resolved (`:642`), and `test_a_product_campaign_run_retains_its_events` drives that entry; 30/30 in `tests/test_decision_trace_469.py`. W469 remains unrun and the brief takes no credit." |
| 4 | Comment on #422 | "cannot be accepted end-to-end at `280ee3d4`: `harness.citation_resolver` has no product importer (only `tests/test_citation_resolver.py`); 66 citation tests pass, so the resolver works and is unreached. #645 landing did not create the report-path call site." |
| 5 | Comment on #413 | the section 4 output block, verbatim, plus the two named unblockers |
| 6 | Comment on #466 | "#467 is record-and-close complete on its published measurement; the brief is terminal. Live briefs remaining: #469, #472 closed, #473 closed, #468 closed, #470 closed" |
| 7 | Census | the three commands in section 5 |

## 7. Lane state

- **DONE:** transport test passed and receipted; stand-up filed; #467 record
  drafted to close-ready; `campaign-trace-writer-unwired` cured and the intake
  row corrected with executed evidence; #422's call-site absence established by
  grep; #413 re-checked and filed; #646's exact census act named.
- **WIP:** the #422 call site (next code car; not started, not claimed).
- **NEXT:** write the #422 report-path call site, gate it, land it, then run the
  #422 acceptance live.
- **BLOCKERS:** authenticated GitHub API (writes + census). Nothing else.
- **IDLE:** none.
