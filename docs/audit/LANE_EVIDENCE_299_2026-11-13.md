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

**Branch / exact head:** `lane/core-299-post-body-cap`
`643fc8988f3d48f8af9b3e0815e3d159a65f8dd1` (verified on the remote).

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
| `python3 -m unittest tests.test_server` | Ran 120 tests, OK (includes the 5 new `PostBodyCapTests`) |
| `python3 -m unittest tests.test_server_driver tests.test_intake tests.test_site_server` | Ran 100 tests, OK |
| `ruff check harness/server.py tests/test_server.py` | All checks passed |

New cases: over-cap refused without reading, over-cap refused before
`100-continue`, over-cap refused on the driver route, malformed
`Content-Length` is 400, under-cap POST still dispatches (404 from the
router, i.e. the body was read and routed).

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

## Not checked

- CircleCI rail statuses on this head (no access from this lane; a named
  status read is required from a lane that has it).
- A second non-author reviewer verdict (no reviewer reachable).
- Live GUI/LAN behavior: the cap was exercised on loopback only.
