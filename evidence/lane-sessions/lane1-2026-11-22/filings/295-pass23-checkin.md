## CHECK-IN pass-23 - Lane 1 (order item 9: the serve log scrubbed one credential name; now the family)

Lane 1 read the lane's GitHub surfaces, found no newer steering than its own
pass-22 filing, and took the first unworked, unblocked item. Items 1-4 and 7-8
of the filed order landed in earlier passes; item 5 stays delivered only to the
limit of this machine's data; item 6 stays skipped. The next genuine, unblocked
defect was **#653**, and it is landed: PR #718, squash-merged as `2e156c92`,
full 16/16 CircleCI rail green at the landing head `0b03d0f9`. No edit was made
to `laptop-vision-20261122` (PR #685); that branch still has one editor.

### Verified at turn start

- #295's newest comments were my own pass-22 check-in (`7139272635`) and its gate
  receipt (`7139287057`). No newer Treystu comment, no STOP.
- #684's newest comments are the vision lane's transition dispatches (T3
  checkpoint last) - that branch and its proofs belong to the standup lane and
  this lane did not touch them.
- Open PRs unchanged and not mine: #685 `18e8160b`, #701 `e280e20f` (refs #684,
  #452, #655), #702 `7e4ec0bf`, #709 `6ed34b80`.
- `main` was `743618e1`; the lane evidence branch matched its remote at
  `cea2b63a`.
- #704 still has no PR, so item 6's stated condition is unchanged.

### Order position, re-read from the filed orders

- Items 1-4 (#705, #685 rail naming, #706, #707) and items 7-8 (#342/#344,
  root scratch removal) landed in passes 19-21.
- **Item 5** is delivered to the limit of this machine's data: the Step 0
  two-count verification is filed on #466, and both remaining legs are blocked on
  inputs, not code (no provider key beyond Jev; no retry/breaker or campaign
  `record_stop` rows in the home ledger).
- **Item 6 (#655)** stays skipped: PR #701 refs it but does not land it, and
  #704 still has no PR.

### DONE this pass - #653, PR #718

**The defect, confirmed in code at `743618e1`.** `harness/server.py` defined
`_TOKEN_IN_LOG_RE = (token=)[^&\s\"]+` and `log_message` applied it to every
request line on both sinks - the `[ui]` stderr line and the #574 on-disk serve
log. One parameter name was covered; a credential arriving as `?key=`,
`?api_key=`, `?auth=`, `?access_token=` or `?password=` was written in plaintext
to both.

**The cure, on `main` `2e156c92`.** `_CREDENTIAL_PARAM_NAMES` names the family
(`token`, `key`, `api_key`/`apikey`/`api-key`, `auth`, `access_token`,
`refresh_token`, `password`/`passwd`, `secret`, `client_secret`,
`session_id`); `_CREDENTIAL_IN_LOG_RE` matches `\b(?:family)=[^&\s\"]+`
case-insensitively and substitutes `\g<name>REDACTED`, keeping the name
readable and removing only the value. The substitution stays in `log_message`,
so both sinks keep the one owner the issue asked for. A word boundary keeps
ordinary parameters out: `?monkey=banana` and `?keys=visible` keep their values.

**Measured, same line.** `GET /?api_key=sk-live-abcdef&page=1 HTTP/1.1" 200` at
`743618e1` keeps the value; at `2e156c92` it reads
`GET /?api_key=REDACTED&page=1 HTTP/1.1" 200`.

**Tests** in `tests/test_serve_log_574.py` (the #574 owner's file): a live
request through `make_server(..., log_path=...)` asserting the file holds
`api_key=REDACTED` and not the value; fifteen name spellings through
`log_message` asserting the value reaches neither `sys.stderr` nor the file;
and an over-redaction guard for `monkey=`/`keys=`.

**Runs at `0b03d0f9`:** `tests/test_serve_log_574.py tests/test_server_driver.py
tests/test_server.py` -> **193 passed, 5 skipped, 8 subtests passed**;
`tests/test_serve_log_574.py` alone -> **16 passed**; full local suite ->
**7842 passed, 82 skipped, 1329 subtests**, with only the documented local-only
`test_local_fit_optional_ci_311` fixture failure.

**The one red head, named rather than retried.** `7566c981` failed all six
hermetic legs and `test` because those jobs run `ruff check harness tests
examples/oc_handoff driver_core` before the suite and the new test used percent
formatting three times (`UP031`, `tests/test_serve_log_574.py:200,203,204`).
`0b03d0f9` uses f-strings; ruff reported `All checks passed!` and the rail went
n=16 ok=16 pend=0 bad=.

**Landing evidence filed on #653 as its own comment** (the issue had zero
comments: a cured security defect with no evidence path), with the pre/post-cure
line, the code names from `main`, the test names and the red-head cause.

The `docs/jev-roadmap.md` register carries no per-issue row for #653 (it appears
only in the open-set line at 274), so this pass made no register edit and cut no
register PR.

### WIP

Nothing is in flight. PR #718 is merged and no PR of mine is open.

### NEXT

The next unworked, unblocked item: the next genuine defect after #653 in the
interleaved order. Item 6 stays skipped until #701 and #704 land; item 5's two
withheld legs stay parked on a provider key and on ledger data.

### BLOCKERS

- Item 5's live-brief leg: no provider key on this machine (Jev only).
- Item 5's champion replays: no retry/breaker rows, no campaign `record_stop` rows.
- Item 6 (#655): PR #701 refs it but is open, and #704 has no PR.

WAIT-STATE: idle: none.

### Gate receipt

Lucas Gate v2 typed track and product Jev were run on this filing before posting;
the receipt comment follows.
