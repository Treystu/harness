# Cloud Cure Lane - STATUS (2026-11-21, oversight mission)

Mission acknowledged: **HARNESS CLOUD CURE LANE - 2026-11-21 (oversight)**.
Branch: `standup/harness-cure-2026-11-21`. Base: `main`.
Queue: #653, #654, #655, #656. Fences: Lane 1 owns #343/#344 verification, the
#422 acceptance, #415, W469 and RSI #649-#652 - untouched here.

## Live census (two methods, taken from this workspace)

| Reading | Method A | Method B |
|---|---|---|
| `main` head | `git ls-remote origin refs/heads/main` -> `32f8f843103c0088979e854be3a4df225f518714` | local `git log -1` -> `32f8f84` (docs(roadmap): record the #343 and #344 landings...) |
| open issues | `GET /repos/Treystu/harness/issues?state=open` (paged, 3x100) -> **39** | `GET /search/issues?q=repo:Treystu/harness+type:issue+is:open` -> `total_count` **39** |
| open PRs | same listing, items carrying `pull_request` -> **0** | `GET /search/issues?q=repo:Treystu/harness+type:pr+is:open` -> `total_count` **0** |

Open issue set (both methods agree): 277, 280, 281, 289, 291, 294, 295, 308, 309,
310, 313, 314, 318, 319, 337, 342, 344, 380, 381, 382, 412, 413, 415, 422, 452,
466, 469, 475, 480, 482, 517, 649, 650, 651, 652, 653, 654, 655, 656.

Method B is the unauthenticated public REST/search API (repo is public,
`http=200` on `/repos/Treystu/harness`), read from this workspace with `curl`.

## GitHub API acts I cannot perform from this workspace (filed verbatim for oversight to mirror)

`gh auth status`:

```
You are not logged into any GitHub hosts. To log in, run: gh auth login
```

`gh issue list --state open --limit 400`:

```
To get started with GitHub CLI, please run:  gh auth login
Alternatively, populate the GH_TOKEN environment variable with a GitHub API authentication token.
```

`gh pr list --state open --limit 100`:

```
To get started with GitHub CLI, please run:  gh auth login
Alternatively, populate the GH_TOKEN environment variable with a GitHub API authentication token.
```

Consequences, stated plainly rather than faked:

- No issue comment, no PR creation, no draft-PR body refresh, no label and no
  merge can be performed here. Every GitHub-side act this lane owes (STATUS
  comments on #653/#654/#655/#656, the draft PR into `main`) has to be mirrored
  by oversight.
- Git **write** via the platform's connected git does work; the stand-up commit
  on this branch is the proof of that write path.
- Census was therefore taken by `git ls-remote` plus the unauthenticated public
  REST API (two independent methods, both above); the authenticated-`gh` read
  is the act that failed.

## Canonical Jev

Canonical Jev from this workspace reads **NOT CHECKED**. No Jev alignment was
run for this filing.

## Queue state

| Issue | State in this filing |
|---|---|
| #653 serve scrubber | queued |
| #654 GUI version/commit | queued |
| #655 loopback split | queued |
| #656 test isolation | queued - part (2) is a named local-lane act, below |

## Named local-lane act (cannot be done from this workspace - not faked)

**#656 part (2), the contamination re-measure, needs the laptop operator
database.** This workspace has no `~/.harness` and no operator ledger, so the
current test-run-vs-total record count cannot be taken here. That count is
filed as a named LOCAL-LANE act for the laptop session: read the operator DB,
count test-run rows against total records, and file the number on #656. Nothing
in this lane will claim that number.

## Midnight cutoff

No new turn at or after 00:00 HST (2026-11-22). State is filed on the branch
before that cutoff.

## Result at this head (a632b8c, on top of main 32f8f84)

Queue worked in order. Every change is on `standup/harness-cure-2026-11-21`;
nothing was pushed to `main`, and no Lane-1 territory (#343/#344, #422
acceptance, #415, W469, RSI #649-#652) was touched.

### #653 - serve scrubber (DONE)

`harness/server.py`: `_TOKEN_IN_LOG_RE` now matches the enumerated credential
family (`api_key`, `access_token`, `password`, `token`, `key`, `auth`), keeps
the parameter name, redacts only the value, and still stops at `&`, whitespace
or a quote. The one owner is unchanged: `log_message` applies it to stderr and
the #574 on-disk log together. Longer names are listed first so `api_key=` is
not matched as `key=`; `author=` is untouched (an equality is required).

Tests (`tests/test_serve_scrub_653.py`, 8): each enumerated name through the
pattern; case-insensitivity; the `api_key`/`key` ordering; a name without `=`
left alone; each name through `log_message` asserting both sinks; and one real
HTTP request asserting the file holds `api_key=REDACTED` and no secret.

### #654 - GUI renders version/commit (WIRED, served-side verified)

`harness/ui/index.html`: a quiet `#harness-identity` line inside the input
footer. `harness/ui/app.js`: `loadHarnessIdentity()` fetches `/api/status`
(the payload that carries `version` + `commit`) and paints
`Harness v<version> (<short commit>)`; it never opens a modal and never raises
an error banner. `harness/ui/app.css`: the persistent, muted style.

Verified against a served instance (not by reading source): `GET /` -> 200 with
`id="harness-identity"`, `GET /api/status` -> 200 with
`version=0.5.1`, `commit=v0.5.1-198-g985f421-dirty`, matching
`X-Harness-Version` / `X-Harness-Commit` headers, `GET /app.js` -> 200 with the
render code. **The rendered pixels were not viewed: this workspace has no
browser, so the visual placement is unverified.** Tests:
`tests/test_ui_identity_654.py` (5).

### #655 - loopback split (UNIFIED, 8766 retired)

New `harness/loopback.py` states the rule once:
`HARNESS_BASE_PORT` (default 8765) + media offset 0 (8765) + serve offset 2
(8767). `make_server` and `harness serve --port` default to `serve_port()`;
`harness/ui.py` now defaults to the same `serve_port()` and the
`default=8766` desktop default is gone; `harness doctor --gui-port` and
`media_client.DEFAULT_BASE` derive from the same owner. Docs updated:
`docs/ui-acceptance.md` (port map + the rule), `docs/media.md`,
`docs/security.md`, `docs/ui-readiness.md`, `README.md`.
Tests: `tests/test_loopback_655.py` (8) plus the updated doc contract.

### #656 - test isolation (guard + script DONE; contamination count NOT MEASURED)

`tests/conftest.py` installs a session guard at `pytest_configure` /
`pytest_sessionstart`: `HARNESS_HOME`, `HARNESS_CONFIG_DIR` and
`HARNESS_LEDGER` all point into one ephemeral directory that is removed at
exit, restored on teardown, and overridable by a test that sets its own.
`scripts/cleanup_test_records.py` removes test rows from a ledger, dry run by
default, `--apply` to write, backup on by default, count printed either way.
Tests: `tests/test_test_isolation_656.py` (7).

**Part (2), the contamination re-measure, is NOT DONE here and is not faked.**
It needs the laptop operator database. Named local-lane act: read the operator
ledger, run `scripts/cleanup_test_records.py --ledger <path>` (dry run) for the
current test-run-vs-total count, and file that number on #656.

## Gates actually run at this head

`python3 -m unittest` on: `test_serve_scrub_653`, `test_loopback_655`,
`test_ui_identity_654`, `test_test_isolation_656`, `test_serve_log_574`,
`test_media_client`, `test_docs_contracts` -> 86 tests OK.
`test_server`, `test_site_server`, `test_serve_identity_587`,
`test_driver_core.test_serve_base_url` -> 174 tests OK.
CircleCI statuses were **not** read: that read needs the authenticated GitHub
API this workspace does not have, and a queued or absent run is not green.
This head is therefore green locally and unverified on CI.

## GitHub acts oversight must mirror (this workspace cannot perform them)

1. Comment the result above on #653, #654, #655 and #656 (this lane has no
   authenticated `gh`, so no issue comment can be posted here).
2. Open the draft PR `standup/harness-cure-2026-11-21` -> `main` (branch is
   pushed; PR creation needs the authenticated API).
3. Read CircleCI statuses on the exact head and land only if green.

## #654 follow-up: the render was executed, and it found a defect

The served-side read above proved the payload and the element, not the label.
So the real render code in `harness/ui/app.js` (`shortCommit` +
`loadHarnessIdentity`, cut from the file and executed with only the DOM and the
network call stubbed) was run in node against a live `python3 -m harness.server`
instance. First run at `3f2e9eb`:

```
servedCommit: v0.5.1-200-g3f2e9eb
renderedText: "Harness v0.5.1 (v0.5.1-)"   <- wrong
```

`shortCommit` sliced the first 7 characters of the whole `git describe` string.
Fixed in `c48`-series commit "fix(ui): render the commit from the describe
suffix": the suffix after `-g` is now extracted (`-dirty` tolerated), a bare
sha is passed through, anything else is shown whole. Re-run at the fix:

```
servedVersion: 0.5.1
servedCommit:  v0.5.1-200-g3f2e9eb-dirty
renderedText:  "Harness v0.5.1 (3f2e9eb)"
hidden:        false
```

`tests/test_ui_identity_654.py` now also pins the describe-suffix extraction
(6 tests, OK). The verification helper is `.verify/render_check_654.js`, left
**untracked** on purpose: CI has no node, so it is evidence for this filing
rather than a suite test. Pixel placement is still unviewed (no browser here);
what is now verified is that the real client code paints the correct label into
the served element.
