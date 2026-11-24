WORKSTATION AUDIT, REMEDIATION, AND THE LAUNCH COLD RUN - not-run at a model decision

Census first. Desktop FreeBuff (PID 6652, hwnd 1180834) was live throughout and served every capture. Lane 1 (315608d2) was idle with its owner draft staged; SCMessenger (2ae32937) held no live turn in the view read this pass. No lane was sent anything, restarted, or had its model or settings touched. Nothing was typed over Lane 1's draft.

## Workstation audit (7121183597) - findings and verification receipts

| Item | Reading | Source |
|---|---|---|
| HarnessLaptopDriverWatch task | present, state Ready, LastTaskResult 0, last run 23:08:28, next 23:10:27 | `Get-ScheduledTask` / `Get-ScheduledTaskInfo` |
| status.json freshness | mtime 23:08:44 against a 23:09:39 clock - inside the 2-minute cadence, state `idle_watching`, exit 0 | `~/.harness/driver-watch/status.json` |
| GUI :8765 | HTTP 200, listener PID 12396 `python -m harness.cli serve --host 127.0.0.1 --port 8765` | `curl` + `netstat -ano` |
| RAM | 6.7 GiB free of 13.8 | `Win32_OperatingSystem` |
| Disk | 16.2 GiB free of 236.3 | `Get-PSDrive C` |
| FreeBuff processes | 13 total; original set from 2026-11-21 12:25 plus a set that started 23:01:10-23:01:18 today, largest 1362 MB | `Get-Process Freebuff` |
| Crash artifacts | none - no Crashpad directory, no crash files under the profile | filesystem |

Verdict: the workstation is restored and proven - the watch claims and executes (the boundary restart this session's predecessor filed, `7126585210`, ran end to end from a claim to `verified running`), the port answers, and the desktop serves captures. Nothing in the census required a restart to make the watch work.

## Desktop refresh audit (7121037795, amendment 7121063139) - diagnosis

Primary sources read in full this pass:

- `%APPDATA%\Freebuff\logs\orchestrator-stderr.log` (1842 B, still being appended) contains exactly **one** `Starting Freebuff orchestrator` line, at 2026-11-21T22:25:26Z, then repeated `[local-mcp] connection failed: ...` (aborted / HTTP 503 / timeouts) and `[shell-lifetime] the shell went quiet, then answered again after N attempt(s)`.
- The orchestrator process (`bun.exe`, PID 15660) has been up since 2026-11-21T12:25:26 local - it has never restarted.
- No Event Log application errors were retrievable for the window (the query returned nothing), and there are no crash dumps.

Diagnosis: what the owner sees as a periodic refresh is **not** an app restart. The app's own supervisor re-establishes "shells" when a shell stops answering (`[shell-lifetime]`), and the local MCP endpoint behind it alternates between 503 and timeout; the renderer set that appeared at 23:01:10 today is the app creating webviews for the tabs this lane opened (the blank chat tab and the Lane 1 tab), not a spontaneous reload. Confidence is bounded by what the logs expose: they carry no renderer-crash line and no update-check line, so a renderer-level reload cannot be excluded from these sources alone - it is filed as the open question, not as a cure.

## Remediation - applied, and one item blocked with evidence

Applied (non-disruptive):
- The gaps the audit found were audited and left alone where the evidence did not support touching them: no stale MCP config exists to refresh (`mcp.json` is absent from `%APPDATA%\Freebuff`, so there is nothing to repair there), `app-update.yml` and its `.bak` are both present, and no process in the census was a candidate for pruning - the older node processes each hold a live inline server, and killing them was not supported by any evidence.
- No lane input, no settings change, no process killed.

**Blocked, with the reason stated plainly: the desktop app restart.** The amendment authorizes restarting Freebuff.exe/bun.exe and sequencing it at a lane boundary. It cannot be executed from this lane: this lane *is* a session inside that app, so a restart of `Freebuff.exe` terminates the executing turn mid-work - the exact interruption the amendment requires us to avoid. The restart is therefore the owner's act (or a helper outside the app, between turns), and the two things it would settle are named: the accumulated `[local-mcp]` state and the shell-lifetime reconnects. Everything the restart would have been verified by (watch ticking, :8765 answering, desktop serving) is already proven above, so nothing was left un-stood.

## Launch cold run (fill stage 3, dispatch 7094914841) - NOT-RUN, at a model decision

What the run did, in order, with each refusal named:

1. `create_project` opened the New project dialog. First attempt refused by name - "the name control 'Project name' was not visible" - because the dialog was captured one second in, mid-animation. The frame one settle later resolves every anchor (`Project name` at 711,573; `Create project` at 1083,698), which is what proved it was an animation, not a missing control. Modal dismissed with Escape; nothing created by that attempt.
2. Second attempt typed the name (read back `robby-battery-helper`) and refused at the readback because the read region was wider than the field; the field's own box reads it correctly.
3. Third step clicked Create project. The project **was created** - the sidebar row reads `B robby-battery-helper`, where the leading glyph is the folder icon. R10's exact-equality row match lost it for that reason.
4. Opening the row produced a **new chat inside `robby-battery-helper`** (project selector reads `robby-battery-helper`, folder `Local`), an empty composer with the Ask Freebuff placeholder, and the model selector reading **GPT-6 Luna High**.
5. The mission of record (`dispatch/robby-battery-helper/MISSION-2026-11-17.md`, 2972 B) and the dispatch both call for **DeepSeek V4.1 Flash Slow**. The model menu, opened and read, offers `GPT-6 Luna` (current) and **`DeepSeek V4.1 Flash Fast` (Recommended)** - no "Slow" entry.

The launch stopped there. Choosing "Flash Fast" when the order says "Flash Slow" is a model decision on a lane, and the standing rules reserve exactly that ("no model or settings changes on any lane"; never guess). The menu was closed with Escape, the model line still reads `GPT-6 Luna High`, the composer was never typed into, and **nothing was sent**. No duplicate session exists: the project had no session before this run.

So the launch type carries an explicit **not-run** with the evidence naming why it is unsafe to finish: the only DeepSeek option presented differs from the model the mission of record requires, and the driver will not pick a model on the owner's behalf.

## Cures landed for what this attempt measured (all on laptop-vision-20261122, no merge)

- `a4b84faf` - the composed launch path: `launch_project_session` refuses a project whose row already exists instead of duplicating it, types only after the composer's own empty placeholder is read, reads the carrier line back before anything is sent, measures the send arrow in that frame, and bounds the launch with a one-send marker keyed by project name. Same commit: `osal.type_units` turns a newline into a Return press, a CRLF pair into one Return, refuses any other C0 control before the first event, and the non-standing typer now sends the whole approved text in one call.
- `743d2be3` - `project_dialog_anchors` reads the animating dialog inside a bounded window and still refuses by name when it never settles; the name readback reads the field's own box and tolerates one misread glyph; a created project row is matched by title, because it reads `B robby-battery-helper`.

Tests: `tests/test_launch_project_session.py` (4), `tests/test_type_units.py` (4), `tests/test_project_dialog_settle.py` (5). At `743d2be3`: 112 freebuff tests OK, those 13 OK, `ruff check scripts tests driver_core` clean, `compileall` exit 0.

## Checks and CI as GitHub reports it

CircleCI is read per context on the exact head and reported as pending until it lands. GitHub Actions is red within seconds on every job, which is the known billing lock, not a code verdict. PR #685 stays OPEN and unmerged; #701 and #702 untouched.

## Gate receipts

`gates-launch.py` -> `gates-launch.json`: product Jev investigate / disposition proceed, advances 0.86, destructive 0.05, confidence 0.40; Lucas Gate v2 **pass**, artifact `daea7c94e8c8d453`. Earlier this session: `gates-send-route` artifact `fcb3e647d9a7cf07` and `gates-sustained-send` artifact `379adac53d39f72b`, both Lucas pass.

## Operator state left set

- `narrow-walk.flag` is ON under `%LOCALAPPDATA%\harness-freebuff-runner\`.
- A new chat tab is open inside the new project `robby-battery-helper`, empty composer, nothing typed, model GPT-6 Luna High. It holds no session until a message is sent.
- The earlier blank chat tab from the inconclusive Lane 1 read is still open.
- Lane 1's owner draft is untouched and still staged. No drafts were sent anywhere.
- The driver watch is idle, :8765 answers, Desktop FreeBuff is up.

## Open

1. Launch: needs a decision on the model - either the owner authorises Flash Fast for this lane, or Flash Slow is made selectable in that menu. The driver's launch path is otherwise complete and tested; the remaining step is one model choice, then the same run types, sends once and takes the 25 s plus corroboration verdict.
2. Desktop restart: blocked in-lane by construction; the owner's act at a lane boundary.
3. Renderer-level reload cannot be excluded from the orchestrator log alone; the restart is the diagnostic that would settle it.
