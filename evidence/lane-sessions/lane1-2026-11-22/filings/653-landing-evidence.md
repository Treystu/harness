## #653 landed: the serve log now scrubs the credential parameter family

The issue's reverify receipt was correct at `main` `743618e1`. `harness/server.py`
defined `_TOKEN_IN_LOG_RE = (token=)[^&\s\"]+`, and `log_message` applied it to
every request line on **both** sinks: the `[ui] ...` stderr line and the #574
on-disk serve log. The mechanism was right; the coverage was one parameter name,
so a credential arriving as `?key=`, `?api_key=`, `?auth=`, `?access_token=` or
`?password=` was written in plaintext.

### The cure, on `main` `2e156c92` (PR #718, head `0b03d0f9`, rail n=16 ok=16)

`harness/server.py`:

- `_CREDENTIAL_PARAM_NAMES` names the family: `token`, `key`, `api_key` /
  `apikey` / `api-key`, `auth`, `access_token`, `refresh_token`, `password` /
  `passwd`, `secret`, `client_secret`, `session_id`.
- `_CREDENTIAL_IN_LOG_RE` compiles `(?P<name>\b(?:<family>)=)[^&\s\"]+` with
  `re.IGNORECASE` and replaces the match with `\g<name>REDACTED`. The parameter
  name survives, so an operator can still tell which credential was in the URL;
  only the value is removed.
- The substitution stays in `log_message`, so both sinks remain covered by the
  one owner, which is what the issue asked for ("keep the redaction in
  log_message so both sinks stay covered by the one owner").
- The leading `\b` is the guard against over-redaction: `?monkey=banana` and
  `?keys=visible` keep their values, and the value still stops at `&`,
  whitespace or a quote, so `page=1` and the rest of the request line survive.

### Measured before and after, same line

Input: `GET /?api_key=sk-live-abcdef&page=1 HTTP/1.1" 200`

- pre-cure pattern at `743618e1`: `GET /?api_key=sk-live-abcdef&page=1 HTTP/1.1" 200`
  (the value survives)
- cure at `2e156c92`: `GET /?api_key=REDACTED&page=1 HTTP/1.1" 200`

### Tests, in `tests/test_serve_log_574.py` (the #574 owner's file)

- `test_a_key_in_the_url_is_redacted_in_the_file` - a live request through
  `make_server(..., log_path=...)`; asserts `api_key=REDACTED` in the file and
  the raw value absent.
- `test_each_credential_parameter_name_is_redacted_on_both_sinks` - fifteen name
  spellings, including `TOKEN` and `Api_Key`, through `log_message`; asserts the
  value reaches neither `sys.stderr` nor the on-disk log, and that the name and
  the rest of the line do.
- `test_a_parameter_that_only_ends_in_a_credential_name_keeps_its_value` -
  `monkey=` and `keys=` are not over-redacted.

At head `0b03d0f9`: `tests/test_serve_log_574.py tests/test_server_driver.py
tests/test_server.py` -> **193 passed, 5 skipped, 8 subtests passed**;
`tests/test_serve_log_574.py` alone -> **16 passed**. Full local suite at the
same tree: **7842 passed, 82 skipped, 1329 subtests**, with only the documented
local-only `test_local_fit_optional_ci_311` fixture failure.

### The one red head, named

Head `7566c981` was red on all six hermetic legs and `test`. Cause, not retry:
the hermetic steps run `ruff check harness tests examples/oc_handoff driver_core`
before the suite, and the new test used percent formatting three times -
`UP031` at `tests/test_serve_log_574.py:200,203,204`. `0b03d0f9` uses
f-strings there; ruff then reported `All checks passed!` and the rail went
n=16 ok=16.
