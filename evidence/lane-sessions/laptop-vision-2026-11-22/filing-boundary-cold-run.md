STANDUP RECEIPT - boundary cold run, workstation cure, audits, R7 (head f266b4b7)

Census first, as the order requires. Lane 1 is in progress: its composer holds the owner's unsent draft and its banner reads `WAIT-STATE: idle: none`. It was not touched - no send, no clear, no restart - and every action below is either on a different lane at its own boundary or on the workstation itself. No duplicate session was created and no lane's model or settings changed.

## R7 - expired-session restart exists and is exercised

Commit `cb52e0c9` on `laptop-vision-20261122`: `ResumeStartCompositionTests` in `tests/test_freebuff_watch.py`. `_SingleUseSurface` fails the test if Resume and Start are located in two passes or if the composed action re-locates either control, and the Start frame is captured after the Resume click, so the test fails unless the two steps are one bounded action.

Trace: `evidence/lane-sessions/laptop-vision-2026-11-22/r7-resume-start-trace.jsonl`, produced by `r7-resume-start-trace.py`, seven hash-chained records (extraction Resume, verification, action Resume, extraction Start, verification, action Start, `start-staged-running`), tail hash `b26ee2ccd220770dbad4121e4882dc35a774d23ff29a457ded85a567077d033c`, script prints `R7 composition: OK` and exits 0. It is a harness trace, not a live expired-lane run, and is filed as such.

## Workstation audit (7121183597) - verdict and remediation

Found: `HarnessLaptopDriverWatch` was **absent** from the task scheduler while watch ticks kept advancing. Port 8765 answered HTTP 200 three times, owned by `C:\Python314\python.exe -m harness.cli serve --host 127.0.0.1 --port 8765` (PID 12396). RAM 6.8 GiB free of 13.8, disk 16.7 GiB free of 236.3. Eight or more `Freebuff` processes, largest 1348 MB.

Remediated: re-registered from `%TEMP%\register-driver-watch.ps1` (wscript hidden launcher, 2-minute repetition, IgnoreNew). Verified `state=Ready`, `LastTaskResult 0`, `LastRunTime 21:52:28`, `NextRunTime 21:54:27`, and `status.json` advanced `07:50:05 -> 07:52:44` with `exit_code 0`. A heartbeat is not proof of execution, so the watch's claim and execute record is filed below from the receipts themselves.

## Desktop refresh audit (7121037795, amendment 7121063139) - verdict

`%APPDATA%\Freebuff\logs\orchestrator-stderr.log` (1728 B) shows one "Starting Freebuff orchestrator" at 2026-11-21T22:25 and no refresh, restart or update marker since; what it does show is repeated `[local-mcp] connection failed` (aborted / HTTP 503) and `[shell-lifetime] the shell went quiet, then answered again after N attempt(s)`. `app-update.yml` and `app-update.yml.bak` both exist; no `mcp.json` under `%APPDATA%\Freebuff`. Desktop FreeBuff is stable: it served every capture in this pass.

Remediation disposition: the one destructive step - a desktop app restart - is **deferred, not skipped silently**. A restart at this moment would discard the owner's unsent draft in Lane 1, which this pass is explicitly barred from touching, so it belongs to the owner's decision and is named here rather than taken. Everything else in the amendment (diagnosis, feed files, log evidence) is resolved read-only.

## The watch claims and executes - receipts

Three Lane 1 claims executed end to end with zero sends: `7124457637`, `7124952240`, `7125231144` (acks `7124475958`, `7124988196`, `7125239780`; results `7124675461`, `7125175497`, `7125264923`), each `send_freebuff: 0`, `type_freebuff: 0`. The third reached the composer and refused the owner draft, which is the correct behaviour and the subject of gate `8be3deb5`.

## Boundary-restart cold run - NOT-RUN at the send gate, with the trace

Authorised by the owner's own dispatch `7124370203` (SCM-STOP-2049). That comment never parsed (`DISPATCH_BANNER` False, `restart_dispatch` False, `parse_dynamic_dispatch` None) because its banner is "LANE CONTINUATION WATCH - RESTART DISPATCH SCM-STOP-2049", so four parseable iterations were filed carrying the same instruction: `7125497229`, `7125647656`, `7125763396`, `7125887396`. All four were claimed. No message was sent in any of them.

What the iterations measured, and the cures they landed on this branch:

- `7125497229` refused thirteen times with "the separate Lane 1 Stop square is absent". Lane 1 was idle, which is exactly why the square could not be there. Cure `afba5094`: `observe_bystander` returns `BYSTANDER_IDLE` for that refusal and records `t5-<phase>-idle`; any other failure still parks, and `bystander_needs_pair` keeps the paired comparison for a live observation only.
- `7125647656`/`7125763396` paid the bystander probe's full deadline before every one of their own phases, then died in `search` with "driver tree terminated after deadline". Cure `4cefa595`: the probe runs under a short bound and an unobserved bystander is recorded rather than charged to the dispatch.
- `7125887396` got through the whole front half under the narrowed walk (`narrow-walk.flag` on for this lane only): `narrow-query-landed`, `selected-exact-session` row `SCMessenger`, `active-session-id`, one `type_freebuff`, `pre-send-freshness` **16.33 s**, then `send-once` refused with "the active FreeBuff document did not expose the exact pinned thread". Actions in that receipt: `click_freebuff 2`, `type_freebuff 1`, `scroll_freebuff 2`, `send_freebuff 1`, and the one send returned `ok: false`. Zero messages sent.

Verdict: **not-run**. The identity gate refused the send, which is a negative and not a green; the lane's composer now holds our staged `continue in full` from the authorised prepare, un-sent, and that is stated here so nobody presses Enter by accident. The narrowed walk, previously opt-in and unproven live, is now proven for search on this lane: the exhaustive walk was still at page 5 when its unchanged 240 s bound expired, and the narrowed walk reached select/prepare/identity in about twenty seconds under the same bound and the same one-candidate proof.

## Launch cold run - NOT-RUN

Desktop FreeBuff was already running for every claim in this pass, and a cold launch would stand up a second window and risk a duplicate session, which the census rule forbids while lanes are in flight. Recording not-run with that reason rather than calling a second-window start a launch.

## Lane 1 composer - still pending, untouched

Fresh capture `evidence/lane-sessions/laptop-vision-2026-11-22/census-composer.png` (1800x1131, taken 2026-11-24) reads:

```
owner module with an owner test, 100% statement coverage measured before the first push,
docs rows and the same one-way dependency contract.
```

Banner in the same frame: `WAIT-STATE: idle: none`. The foreign draft is **still there**, so no restart was attempted: the negative stands and the decision stays with the owner. Do not type over it.

## Checks at the head

`python -m unittest discover -s tests -p "test_freebuff*.py"` -> Ran 104 tests, OK (includes the three new bystander tests and the R7 composition test). `ruff check scripts tests` -> All checks passed. `compileall scripts harness tests` -> exit 0. CI as GitHub reports it: CircleCI `pending` on `f266b4b7` (contexts `ci/circleci: test`, three hermetic suites, `Checkout hygiene`, installed package), Actions red in 1-4 s across every job, which is the known billing lock and not a code verdict. PR #685 is OPEN at `f266b4b7`, `mergedAt: null`; #701 and #702 untouched. No merge performed.

## Gate receipt

`gates-boundary-cold-run.py` -> `gates-boundary-cold-run.json`: product Jev `investigate` / disposition `proceed`, advances_goal 0.81 against threshold 0.95, is_destructive 0.07, artifact `535dd755b5834d3d`; Lucas Gate v2 `pass`. Earlier gates this pass: `aa9c4658` (route plus opt-in narrowing), `8be3deb5` (stop at the composer).

## Still open

1. Lane 1: owner draft pending; the "continue in full" restart needs the owner to send, clear, or authorise an overwrite.
2. Boundary restart: the last gate is the send-time route read on a non-Lane-1 standing dispatch; the front half is proven, the send is not.
3. Launch cold run: needs a window where Desktop FreeBuff can be started fresh without a duplicate session.
4. Desktop restart: deferred to a lane boundary with an empty Lane 1 composer.
5. Fleet fill, Robby and Kanaloa stand-up: not started in this pass.
