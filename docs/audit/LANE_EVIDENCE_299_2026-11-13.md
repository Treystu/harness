# Lane evidence — #299 POST body cap (2026-11-13)

**Item:** #299 — fix(server): cap POST body size before reading — return 413
over the limit.

**Delivery state:** READY-TO-MERGE — HAR-SAMS merges; author does not.
No pull request could be opened from this lane: the harness-repo credential
available to it is server-side and covers fetch/pull/push only (plain
`git push` reports `fatal: could not read Username for
'https://github.com'`), `gh` is unauthenticated (`To get started with GitHub
CLI, please run: gh auth login`), and the REST API answers 403 with no token.
This record replaces the PR body so the merge case survives without a
tracker. Rail: **NOT CHECKED from this lane** — CircleCI statuses are not
readable here, and no combined status is offered as evidence.

**Branch:** `lane/core-299-post-body-cap`
**Fix commit:** `643fc8988f3d48f8af9b3e0815e3d159a65f8dd1` — the tree every
count below was measured on.
**Branch tip:** the commit carrying this record, read it from the remote
(`git ls-remote origin refs/heads/lane/core-299-post-body-cap`) — a record
cannot name its own commit without going stale the moment it is written. At
integration time the tip was
`74c155f89cf7855ef44f58dfdb209f72117cdd49`; record-only commits after that
advance it while leaving the code tree untouched (verified by diff in
`lane/core-integration`). Correction, 2026-11-13: this line originally named
the fix commit as the head. A merger checks out the tip; the measured tree is
the fix commit. Both are named.

## Defect

`UiRequestHandler.do_POST` read the whole announced body with
`json.loads(self.rfile.read(n))` and no bound, so any client chose the
handler thread's allocation by announcing a large `Content-Length`. The
`/api/driver/nl` route repeated the same read. `Expect: 100-continue` made it
worse: the base class sent the interim 100 before any route saw the request,
inviting the body that a cap would refuse.

## Fix

- `MAX_POST_BODY = 1 << 20`, documented as far above every route's real
  payload (a prompt, one driver step, a dispatch).
- `_announced_length()` and `_read_json_body()` decide the cap from
  `Content-Length` alone: over the cap is refused 413 **before a byte is
  read** and without draining (draining an oversized body is the allocation
  the cap exists to prevent); malformed or negative lengths are 400; an
  absent header keeps the routes' existing zero-length behavior; zero-length
  stays `{}`.
- `handle_expect_100` refuses an over-cap body before the interim 100.
- Both body readers (`do_POST`, `/api/driver/nl`) now go through the one
  helper. Under-cap chat/driver/apply behavior is unchanged, and the
  separate 4096-byte pairing-redeem cap is untouched.

## Evidence on the exact head

| Suite | Result |
| --- | --- |
| `python3 -m unittest tests.test_server` | Ran 124 tests, OK (includes the 9 `PostBodyCapTests`) |
| `python3 -m unittest tests.test_server_driver tests.test_intake tests.test_site_server` | Ran 100 tests, OK |
| `ruff check harness/server.py tests/test_server.py` | All checks passed |

Cases: over-cap refused without reading, over-cap refused before
`100-continue`, over-cap refused on the driver route, malformed
`Content-Length` is 400, under-cap POST still dispatches (404 from the
router, i.e. the body was read and routed); plus the D12-cure cases below
(negative length 400, empty body dispatches, invalid JSON body 400,
under-cap `100-continue` dispatches).

## Second, independent method (not the same run twice)

A black-box probe against a live `make_server` instance, outside the unit
harness: a raw socket announced `Content-Length: 500000000` and sent no body,
with the server's own `/proc/<pid>/status` `VmRSS` sampled before and after.

```
status: HTTP/1.1 413 Request Entity Too Large
refusal seconds: 0.001
rss delta KiB: 28
probe: PASS
```

A body-first server would have held the handler until the 10 s socket
timeout and grown by the announced size; this one answered from the header in
about a millisecond with a flat footprint.

## Integration evidence

Merged onto current main (`9967aa8a3ff513cac3cbb8ccff52550622e009d3`) alone
and together with #334/#445: see
`lane/core-integration`, `docs/audit/LANE_EVIDENCE_INTEGRATION_2026-11-13.md`.

## HAR-SAMS cure note (2026-11-13, on this branch)

Rail at tip `2dfcd43` read 14/15: only `ci/circleci: audit` red. Cause at
the cause, not the check: D12 holds changed harness statement lines to a
95% suite-executed bar, and four added `server.py` lines had no covering
test — the negative-length `else None`, the zero-length `return {}`,
the invalid-JSON `except` 400 block, and the under-cap
`return super().handle_expect_100()`. Cured with four focused
`PostBodyCapTests` (this file's case list above); focused run 9/9 OK.
Merged onto current main `c73c673` as `cf13eb3`; validator re-review +
fresh 15/15 rail on the final tip required before merge.

## Not checked

- CircleCI rail statuses on the final head (HAR-SAMS reads them per head).
- Live GUI/LAN behavior: the cap was exercised on loopback only.
