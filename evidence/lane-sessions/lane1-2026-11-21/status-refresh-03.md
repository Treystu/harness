CARRIER: blob:89eab7852d40
FIRST ACT: reproduce #413 on the loopback driver service at current `main` `280ee3d4`, cure the two seam defects it still carries, and push the branch over the platform git.

# Lane 1 STATUS refresh - 2026-11-21, turn 3 (#413)

**WAIT-STATE:** pending - the GitHub API writes (PR create, comments, closes,
merges) and the two-method census are gated on an authenticated API this
session does not have, and #413's acceptance is gated on the operator's
`DRIVER_JEV_API_KEY`. **Work taken meanwhile:** the #413 reproduction against a
real 8791 service, two product cures on the probed seam, their tests, and this
filing. **Idle: none.**

**Base read this turn:** `main` `280ee3d4f99bf3d33645ddde21b243cebe0b191b`
(`git fetch origin main:refs/remotes/origin/main`; `git ls-remote` agrees).
**Branch:** `lane/413-roundtrip-truth`, cut from that commit - not the diverged
`lane/burndown` (`86165805`, 136 commits diverged), not `main`.

---

## 1. #413 reproduced, and one claim in the checkpoint corrected

The checkpoint's item 5 says the 8791 loopback driver is "not startable on this
host". The console entry point is not installed; the **service is startable**
through the module entry and answers:

```
DRIVER_TOKEN=... DRIVER_DOM_URL=http://127.0.0.1:8797/ \
  python3 -m driver_core serve --host 127.0.0.1 --port 8791   -> health 200
```

Through the product client at `280ee3d4`: `health` `ok=True keyed=False
sources=['dom']`; `vocabulary` `ok=True` (keyless); `verify` `audit.ok=True,
"chain verified", 4 records`; `schemas` `ok=True`; `step(schema="dom")`
`ok=False stopped_at=decision reason=decision_not_usable cost_usd=0.0 detail
"decision status 'unkeyed': no decision key configured"`; no-schema step `400
schema is required`; stale token `HTTP 401: unauthorized`.

So #413's recorded diagnosis holds at this head and the block is the **unkeyed
decision tier** (operator configuration, a paid call this turn may not run), not
the service. Full evidence: [413-cure-and-block.md](413-cure-and-block.md).

## 2. The cure pushed (product code, not a test edit)

Two seam defects that made #413's own probes lie, both fixed in product code:

- `harness/server.py::_api_driver_step` accepted an `action` field and silently
  ignored it, running the model-backed step instead - the misreading that filed
  the withdrawn `driver-vocabulary-keyless-claim-false` row. It now refuses the
  field by name (400) and points at `GET /api/driver/vocabulary`.
- `harness/perception_client.py` reported a rejected token through the same
  `PerceptionUnavailable` an outage uses, and the route then returned 503. New
  `PerceptionUnauthorized(PerceptionUnavailable)` carries `.status` and names
  the cause (a per-start token, so a second process cannot reach the first
  process's service unless `DRIVER_TOKEN` is declared); the route maps it to
  401 `error_kind: driver_token_mismatch`. An outage is still 503 and a missing
  schema still 400, both pinned by tests.

## 3. Verification at this head

```
pytest tests/test_perception_413.py -q                    8 passed in 2.57s
pytest tests/test_perception_client.py tests/test_server_driver.py \
       tests/test_doctor.py tests/test_driver_conformance.py \
       tests/test_perception_413.py -q -p no:randomly      164 passed, 43 subtests
ruff check harness/perception_client.py harness/server.py \
       tests/test_perception_413.py                        All checks passed!
```

A full-suite chunk was not run: the touched files are reachable only through the
four neighbouring suites above, which are green, and the change is one exception
subclass plus one early 400 on a route that suite already covers. The last full
run on this construction line was 6,678 passed with two failures named as
environmental.

## 4. Exact intended PR body for this branch (no re-deriving needed)

> **#413: make the loopback driver round-trip report what actually happened**
>
> **Head SHA:** `<head of lane/413-roundtrip-truth>` (refresh this line in the
> same act as any later commit, per AGENTS.md rule 9).
> **Base:** `main` `280ee3d4`.
>
> #413's verification probe was twice misled by the seam rather than by the
> driver: `POST /api/driver/step` accepted an `action` field and never read it
> (which filed the withdrawn `driver-vocabulary-keyless-claim-false` row), and a
> 401 from a healthy service was reported through the outage exception and
> returned as 503 (measured with two harness processes, where an undeclared
> `DRIVER_TOKEN` is generated per start).
>
> - `harness/server.py`: the step route refuses `action` by name (400, naming
>   `GET /api/driver/vocabulary`) before any step runs, and maps a credential
>   refusal to 401 `error_kind: driver_token_mismatch`. Outage stays 503,
>   missing schema stays 400.
> - `harness/perception_client.py`: `PerceptionUnauthorized` carries `.status`
>   and names the cause, as a subclass so every existing caller keeps working.
> - `tests/test_perception_413.py`: pins both, hermetically (fake opener, fake
>   adapter), including the two behaviours that must not change.
>
> **Reproduced at this base:** the 8791 service starts and answers
> (`python3 -m driver_core serve`), keyless surfaces green, and a `dom` step
> stops at `decision_not_usable` (`detail: decision status 'unkeyed'`) because
> `DRIVER_JEV_API_KEY` is unset. #413's acceptance stays PARTIAL: the
> read_dom/click round-trip needs that operator key, and this branch does not
> run a paid window.
>
> **Verification (at this head):** 8 passed in `tests/test_perception_413.py`;
> 164 passed across the perception/client, server-driver, doctor and driver
> conformance suites; ruff clean on the three touched files.
>
> **Not in this PR:** any measurement window, any register count change, any
> close.

## 5. Queue items still gated solely on GitHub API writes

| Item | Gated act |
| --- | --- |
| #467 | comment with the record + close |
| #469 / #644 | comment on the disposition; the W469 window (also credit-billed) |
| #646 | register count correction (needs the census below) |
| #422 / #645 | comment on the report-path cure (`lane/422-report-citation`, turn 2) and the acceptance window |
| #413 | comment with this block + the cure pointer |
| #475 | disposition draft, gate receipts and close |
| #638 | gated retirement close |
| #480 / #482 / #452 | owner-present (parked, unchanged) |
| #466, #294, #295 | tracker/closeout acts, all comments |

## 6. Register counts at this head, and the census still owed

No count is restated here. The register of record prints a census at base
`main` `b709e252` (35 open / 37 by the two-method read) and the mission
checkpoint prints "33 open issues; 4 open PRs (#638 parked, #644, #645, #646)" -
neither can be true at `280ee3d4`, where #644 (`a4dd345`), #645 (`280ee3d4`),
#646 (`3a1946a`), #343 (`fecc469`), #344 (`6602e00`) and #626 (`3816a65`) have
landed. Correcting it needs the authenticated two-method read:

```
gh issue list --state open --limit 400
gh api -X GET search/issues -f q='repo:Treystu/harness type:issue is:open' --jq '.total_count'
gh pr list --state open --json number,title,headRefName,isDraft
```

The register is corrected in the same PR that changes it, with the census taken
at that PR's base.

## 7. Push receipt

Recorded verbatim in [push-receipt-03.md](push-receipt-03.md), committed after
the push completed.

## 8. Lane state and outcome rung

- **DONE:** #413 reproduced end to end against a real 8791 service; the
  checkpoint's "not startable" claim corrected with the command that starts it;
  two product cures + 8 hermetic tests; neighbouring suites and ruff green;
  branch cut from `main` `280ee3d4`; this filing.
- **WIP:** none uncommitted at push time.
- **NEXT:** the #475 disposition draft (rung 3/4 at best while writes are
  blocked); the register census when the API is available.
- **BLOCKERS:** GitHub API writes and the census; #413's acceptance on the
  operator's `DRIVER_JEV_API_KEY`.
- **RUNG:** **2 - a cure pushed** (product code + tests on a fresh branch off
  `main`). Not rung 1: no landing is available while writes are blocked, and
  none is claimed.
- **DIRECTIVES:** the 2026-11-21 #413 end-state instruction - reproduce, cure in
  product code, prove with focused + neighbouring tests at the exact head, push
  with the receipt in the filing, file the exact block, no landing, no
  credit-billed window - executed.
