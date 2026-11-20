## W2 TURN 15 — status

**Comm lock:** #295 read at turn start (newest: oversight ASYNC/NO-SLEEP-WAIT
mandate `7018380913`, v2 carrier note `7018380913`/`7018429217`, sergeant turns
32-34, oversight steering on the re-verification loop) and re-read after
filings; no STOP.

**Acks.** (1) Oversight ASYNC/NO-SLEEP-WAIT mandate `7018380913` ACCEPTED as an
owner order and already binding this lane: this turn used no sleep, poll loop or
idle pause — every command was the work itself, and the one check that depends
on CI (the #637 rail after a push) is handled by launch-then-work, with the
result read once. (2) Steering on sergeant turns 33/34 noted; the W2 note
("turn 17, mission-text defect, re-run triggers stand as filed") is
acknowledged — this lane's re-run triggers are exactly as filed: W468 armed on
#628, W469 armed on a product call site, neither fired. (3) As of this turn the
queue has not moved: main is still `d916a7b`, #628 is still open at `e8ef0b63`
and still draft, #630 unmoved, #638 unmoved.

### DONE

1. **#637 rail read in full — 16/16 SUCCESS at `0533b5da`.** Per context:
   driving-hygiene, Checkout hygiene, package, test, the three `installed
   package` legs, the six `hermetic suite` legs (ubuntu py3.9/3.11/3.13/3.14,
   macos py3.11, windows py3.11), `local fit (optional train/export)`,
   `ui-playwright-smoke`, and **`ci/circleci: audit`** — all success, total 16.
   This closes the per-context read left pending at turn 14. The branch is
   `4618b5f9`-based (BEHIND main), so the car needs a rebase before it is
   landable; that rebase is this lane's and is in progress below.
2. **#413 re-run at the identified head `d916a7b` — verdict PARTIAL, unchanged.**
   Fresh run, two paired states, one harness process at a time:
   no source declared -> `stopped_at: capture`, `no_capture`; `DRIVER_DOM_URL`
   declared -> `stopped_at: decision`, `decision_not_usable` (`status:
   unkeyed`). Keyless read surfaces 200/200/200 with the owner token and 401
   without it in both states; action split 15 total / 4 executable / 11
   `refused_until_backend`, identical to turn 14, so no drift across
   `04fb1cd0 -> d916a7b`. Full receipt filed on #413.
3. **A configuration dependency stated instead of glossed.** `docs/driver.md`
   (42-46) makes `no_capture` the documented default with no source declared;
   the decision tier is reachable only with a source. Turn 13/14's
   `decision_not_usable` was taken with a dom source and is reproduced here
   exactly — two stop positions of one chain, not a contradiction.
4. **Servers stopped, ports released.** Verified listeners only
   (8799 pid 46604, 8800 pid 49456, 8800 pid 14100), killed by PID with their
   trees; `8791/8799/8800` now report no listener.

### WIP

- **#637 rebase + turn-15 evidence.** The evidence branch is being re-based
  from `4618b5f9` onto `d916a7b` and the turn-15 records added in the same
  move, so the car it hands the sergeant is both green and current. Artifacts
  are pushed this turn (>= 20 min cadence honoured); the fresh rail is the one
  pending check.

### NEXT

1. #637: post-push rail read; if 16/16 at the new head, ready-mark for the
   sergeant.
2. On #628 merging: run W468 unchanged at that head (frozen slot 1) and publish
   the comparison on #468.
3. On a product call site injecting `DecisionTrace` into `EventLedger`: open
   W469's clock (frozen slot 2).
4. Continue verifications in frozen order as the sergeant directs.

### BLOCKERS

- **W468** — `harness/jev_assessment.py` has no write path; trigger armed on
  #628 (draft, `e8ef0b63`), not fired.
- **W469** — `git grep -n "trace=" 4618b5f9 -- "harness/*.py"` still returns
  only the parameter declaration `flush_loop.py:374`; no product call site
  injects a writer.
- **#413 acting tier** — needs `DRIVER_JEV_API_KEY` in the serving process;
  unset here, no `.env` in this checkout.
- **#422** — needs a DOI resolver plus the report-path call site; product-owner
  decision via the sergeant.
- **#412** steps 4-7 — owner-signed-in browser window. **#415** — OpenRouter
  credit (`/api/v1/key` 200 with `limit_remaining 1.5` while paid calls 402).
  Both parked with unblockers named, not waited on.

Gates on this status and the #413 receipt (product Jev first, Lucas second):
Jev `investigate`, Lucas `pass` on both — `gates-turn15.json`.

**WAIT-STATE:** pending #637 fresh rail after this turn's push (CircleCI, ~5-8
min from push by prior runs); task taken meanwhile: the #413 head-currency
re-run and its receipt; idle seconds this turn: 0.

**Evidence links:**
- #413 receipt: https://github.com/Treystu/harness/issues/413 (this turn's
  comment)
- receipts in the repo: `evidence/lane-sessions/w2-2026-11-20/probe-turn15.json`,
  `probe-turn15-default.json`, `probe-turn15-configured.json`,
  `probe_turn15.py`, `combine_turn15.py`, `serve-8799-turn15.*`,
  `serve-8800b-turn15.*`
