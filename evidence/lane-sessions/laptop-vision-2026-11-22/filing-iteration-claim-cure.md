## Driver standup iteration - the watch could never claim the oversight's own dispatch (cured), and what the desktop audit found

Gates on this act, in order: Product Jev (`jev-1.14.0`, decision-gate-v3, site `vision_standup_desktop_audit`, private ledger) **investigate / proceed**, advances_goal **0.88** against the 0.95 rule-6 threshold, destructive **0.06**, confidence 0.55 - the non-advance is the disruptive remediation this filing defers, documented below. Lucas Gate v2 **pass**, artifact `b0ef1e617dec4c43`. Receipt `evidence/lane-sessions/laptop-vision-2026-11-22/gates-desktop.json`.

### 1. Cured: the reserved test launch was unclaimable by the watch

`parse_dynamic_dispatch` accepted only the literal phrase `Action for the runner:`. The oversight's actual restart dispatch `7119751841` (episode L1-STOP-939) says:

> Action requested (runner alone, per the 2026-11-22 cutover): in-place restart only - exactly "continue in full".

So the one dispatch the relaunch receipt `7120935548` reserves for the fixed driver could never be claimed, while the watch faithfully heartbeated *"dynamic oversight dispatch active; no unclaimed dispatches"* every 15 minutes. That is the difference between a watch that is alive and a watch that executes.

Cure, commit **`47735e7e`** on `laptop-vision-20261122` (pushed to `Treystu/harness`):
- Accept either line-start instruction phrase, `Action for the runner:` or `Action requested` (`RUNNER_ACTION`, anchored with `re.M` so prose cannot satisfy it).
- **Supersession guard**: never claim a restart the issue already carries an ack or result for. Without it, widening the wording alone would have re-run `7117989632` (SCMessenger), which the web seat already executed (`7119856718`) and whose leg `7120935548` ruled closed. Measured live: `filed_on_issue(comments, 7117989632) = True`, `filed_on_issue(comments, 7119751841) = False`.

Verification: `python -m unittest discover -s tests -p "test_freebuff*.py"` -> **Ran 67 tests, OK** (three new tests: the oversight wording, the prose negative, and the already-acked skip at the poll level); `ruff check scripts tests` -> **All checks passed**. Read-only parse of the live comment now returns `{'kind': 'restart', 'comment_id': 7119751841, 'thread': '315608d2', 'text': 'continue in full'}`.

### 2. Execution is withheld by design, not by a defect - and not claimed as proof

The claim now resolves, but the run has **not** been executed, so there is no claimed-dispatch verdict to file yet. Primary reason, read from the gate itself:

- `desktop_idle()` -> **False** at `04:2xZ`: the owner is at the keyboard. Cutover bound (f) desktop sovereignty requires the watch to yield to the owner's active use, and the watch files `waiting for owner desktop idle` instead of taking focus. I did not bypass it, force focus, or drive the app by hand.
- The reserved dispatch therefore stays **unspent** (no `claim-dyn-7119751841-315608d2.json` in the watch ledger; no send, no duplicate session, no model change).
- Lane 1 remains down, as oversight tick 947 also records. **This filing does not claim the test launch passed.**

What will happen on the next tick inside an idle window, with no further change: claim `dyn-7119751841-315608d2`, post `Vision restart ack #7119751841`, run search -> query -> select -> prepare -> send (one send, exact `continue in full`), and file the result comment with the trace links. A refusal files the exact step and sends nothing.

### 3. Register R1-R19 - cure commits, and the two that are still open

Every row below is a landed commit on this branch; "OPEN" is named as open rather than smoothed.

| Item | Cure on `laptop-vision-20261122` | State |
| --- | --- | --- |
| R1 foreground contention | `9ac0f417` obtain-and-verify on every executor path, `a13660c8` re-assert | cured |
| R2 row identity | `0c06ab16` + `6d9bd6b0` project-scoped rows | cured; closes on the cold runs |
| R3 roster reorder | `01ae9065`, `ccefd568`, `94f209c0` | cured; closes on the SCM cold run |
| R4 compositor geometry | `50f8abaa`, `ee8e3843` recapture-and-retry | cured |
| R5 OCR scale | `4c5e6ae0` one scale for read and match | cured |
| R6 clipped-label confidence | `409d3ce0`, `6307da44`, `1206f883` prefix anchor + exact gate | cured; bar unmoved |
| R7 session expiry | `bcdeade5` refuses an expired session with a staged `/mission` **by name** | **partial**: the state is handled explicitly and legibly, but Resume -> Start execution is not built; R19 is the owner gate |
| R8 renderer reload | `4e7812c5` detect-and-reprepare, `3725f613` re-open at send | cured; closes on the next mid-run reload survived |
| R9 driver-tree deadline | `75b3ce2c` verified stopped-tree retry + longer census deadline; watch sets `phase_timeout=240` | cured |
| R10 Robby project-creation adapter | - | **OPEN**: no adapter opens the New project dialog, names it, points at the folder, starts a session |
| R11 GPT lessons audit | - | **OPEN**: unfiled; sources are the t8 traces and this branch's jsonl set |
| R12 (I-1..I-4 lessons) | `fe1159aa` working banner, usage/latency, corroboration guard | cured |
| R13 live reorder / prefix rivals / click-move | `ccefd568`, `94f209c0`, `6307da44` | cured |
| R14 stale handle mid-enumeration | `a58c8ff4` | cured |
| R15 composer route guessed | `e768fc24`, `c475cd56` read the editor's own text first | cured |
| R16 deterministic section location | `a45e0e0e`, `18e82aa8` full-list walk with a scroll-settled end test | cured |
| R17 empty census read | `c475cd56` a non-empty census is required | cured |
| R18 foreign draft overwrite | `c475cd56` refuse by name, never type over | cured |
| R19 expired session + staged `/mission` | `bcdeade5` | **owner wait**: SCMessenger's leg was sent and closed by `7120935548`; SCM Audit's draft stays preserved |

So R10 and R11 are the substantive gaps. R10 is deliberately not written blind: the adapter needs the dialog's real control names, and opening that dialog is desktop input - barred while the owner is active. R11 is a filing I have the sources for and will file next, not a claim to make here.

### 4. Desktop refresh audit (`7121037795`, remediation under `7121063139`)

Primary sources read, no install modified, no process killed:

- **No crashes.** Windows Application log, last 24 h: zero `Application Error`, `Application Hang` or `.NET Runtime` events involving `Freebuff.exe`, `bun.exe` or `msedgewebview2.exe`. `debug.log` was last written 2026-11-15. The owner's "screen refreshes" are therefore not crash-restarts.
- **Renderer churn is real.** 21 `Freebuff.exe` processes now; the renderer client ids in the live command lines reach **1594**, i.e. ~1,594 renderer launches since the app started 2026-11-21 12:25. Sixteen renderers carry a 2026-11-23 18:20 start stamp - a burst, not a steady cadence.
- **The orchestrator's own log names the restarts.** `%APPDATA%\Freebuff\logs\orchestrator-stderr.log` repeats `[local-mcp] connection failed: The operation was aborted.` / `HTTP 503` and eight `[shell-lifetime] the shell went quiet, then answered again after N attempt(s)` lines. A shell whose lifetime is being cycled is what re-renders the whole client surface.
- **Auto-update is currently blackholed.** `resources\app-update.yml` reads `url: http://127.0.0.1:9/`, while `app-update.yml.bak` (2026-11-15 14:56) holds the real feed `https://freebuff.com/api/desktop/updates/win-x64/`. Every update check fails instantly against a dead port; the feed was deliberately replaced at some earlier point.
- **Not the watch cadence.** The driver-watch ticks every 2 minutes and wrote only `tick ok ... state=active`; it spawns no window and no updater. Refresh timestamps cannot be pinned to it from these logs, and I am not inventing a correlation.

Disruptive remediation **deferred, with its reason**: restarting `Freebuff.exe`/`bun.exe` would interrupt every live lane turn and this chat's own session; restoring the real update feed could trigger an app update mid-run; stopping the MCP/serve processes risks this session's own tool channel (PID 15676 is the `harness.mcp` server). Under `7121063139` remediation is authorized, and it is still correctly sequenced at a lane boundary with re-stand - so it is filed here as the next remediation act, not executed mid-turn on a busy desktop.

Named items: (a) at a lane boundary, restart the app once and restore `app-update.yml` from `.bak`, then observe one 10-minute window for refresh recurrence; (b) prune the Nov-21/22 orphan `node`/`python` processes that belong to no live lane; (c) add the per-lane transition lines the detection dispatch `7121240272` requires to the heartbeat, which is code, not a desktop act.

### 5. Workstation proof (`7121183597`)

- `GET http://127.0.0.1:8765/` -> **HTTP 200**, held by `python.exe` PID 12396 (`harness.cli serve --host 127.0.0.1 --port 8765`), which answers the owner's "GUI no longer running" report: it is up.
- `\HarnessLaptopDriverWatch`: `Ready`/`Enabled`, Last Result `0`, ticking every 2 minutes, and it picked up this branch's new head on its own: `status.json.head_sha` moved `0d1e3da9` -> **`47735e7e`** with `exit_code 0`.
- Resources: 3464 MB free of 14158 MB RAM, 16.8 GB free on `C:`. 58 registered worktrees; 10 carry vision/driver/burndown branches.
- Rail on `47735e7e` (CircleCI statuses read individually, not a combined status): **14 success**, 2 pending (`audit`, `hermetic suite (ubuntu-22.04, py3.9)`), 0 failure. The GitHub Actions `hermetic suite` check-runs on the same commit show `failure`; on this repo those are the billing lock, not a signal, and they are not the rail.

### 6. What this iteration does not claim

No dispatch was executed, so no sustained-turn verdict is claimed for launch, in-place restart or boundary restart. The fill stages were not started: Stage 1's Lane 1 leg needs the dispatch above, and the other lanes' boundaries belong to the web seat under `7120935548`. SCM Audit stays held. Robby creation stays blocked on R10 (app-side project creation), with its checkout half already filed (`7119716263`). PR #685, #701 and #702 remain open and unmerged.

Next, in order: R11 lessons audit filing (sources: t8 traces + this branch's jsonl set), R10 adapter once the desktop can be inspected at the dialog, then the reserved Lane 1 claim inside an idle window, then the fill stages and the acceptance run against `7094050344`.
