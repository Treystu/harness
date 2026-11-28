## R11 - the previous driver session's lessons: what the successes actually did, and which of those the current build embodies

Register item R11 (`7095488264`) asked for the prior GPT-driven session to be reconstructed **from its own traces**, not from recollection, with each lesson marked EMBODIED or MISSING and every MISSING lesson turned into a concrete queue item. This is that filing. Sources are named per row; nothing below is inferred from the prose of a verdict comment where a trace exists locally on `laptop-vision-20261122`.

### The reconstructed method

The successful path in every case was the same five-part shape, and it is worth naming plainly because it is what made the runs auditable rather than lucky:

1. **Identify the window by ownership, never by handle.** `FreeBuffWindow.discover` enumerates visible top-level windows, keeps only those whose `GetWindowThreadProcessId` is in the `Freebuff.exe` process set, and takes the single title with the `Freebuff` prefix. The app recycles handles (measured: one PID owned four handles in twelve minutes), so a stored handle is not identity - `require_window` re-resolves HWND and PID at every use.
2. **Anchor every target with exact OCR, then ask the model a narrower question.** Geometry and exact text come from the OCR pass; the model is asked only what OCR cannot say (is this row selected, is this the right result). `freebuff-send.jsonl` shows the pattern: three `noul` decisions at 0.97/0.99/0.97 against the captured region, then the click.
3. **Bind consent to the exact action and payload.** The send consent in `freebuff-send.jsonl` carries `control: "Lane 1 Send (up arrow)"`, `point: [1506,1072]`, `size: [1800,1131]` - the grant is for that click at that place, not for "send".
4. **One send, then read the app's own state back.** A capture after the click at 0.204 s, then `choice` decisions: `running` at 0.56 (inconclusive) and again `running` at 0.97 one frame later. The run did not treat the first confident-looking frame as the verdict.
5. **Prove bystander safety with pixels, and restore focus exactly.** `t6-exact-focus.jsonl` records capture -> `focus_exact(hwnd=200042,pid=16252)` -> capture -> `focus_exact(hwnd=2361136,pid=6652)` -> capture -> `verification restore passed:true`, i.e. the original HWND and PID were re-focused after the proof, and the trace says so.

### Lesson table

| # | Lesson from the success set | Where it lives in the current build | State |
| --- | --- | --- | --- |
| L1 | Window identity = process ownership + title prefix, re-resolved per use | `FreeBuffWindow.candidates/_visible/require_window`; handle-recycle cure `a58c8ff4` | EMBODIED |
| L2 | OCR anchors geometry; the model answers only the residual question | `locate_exact_text`, `session_candidates`, `scoped_row`, `yes()`; scale cure `4c5e6ae0`, prefix cure `409d3ce0` | EMBODIED |
| L3 | Consent carries the exact action and payload (control, point, size, thread, text) | `Consent` grants in `send`/`type_text`; `69f05e2a` bound thread+text+arrow geometry after run 11 | EMBODIED |
| L4 | Read the app's own state back after input; do not upgrade a first confident frame to a verdict | `stop_visible`, `working_banner` (I-1), `corroborates_running` (I-3), `44d55d1d` (banner over a flickering stop glyph) | EMBODIED |
| L5 | Exact focus restore, proven by HWND+PID readback | `windows_focus.activate_exact`, `windows_foreground_proof.py`, `t6-exact-focus.jsonl`; drive-side `371`-class restores in `execute()` | EMBODIED |
| L6 | Bystander safety = identical RGB before/after, not "we did not look at it" | `Bystander`, `same_pixels`, `capture_set` hashes; T7 PASS filed `7093146641` | EMBODIED |
| L7 | Every step leaves a hash-chained trace, and the verdict is a separately filed receipt | `driver_core.audit.AuditLog` in every phase; runner `publish()` uploads traces; verdict comment per dispatch | EMBODIED |
| L8 | Unattended admission: owner identity, immutable payload, expiry, at-most-once claim | `approved()`, `one_shot_dispatch()`, claim checkpoints; this iteration added the wording widening and the ack/result supersession guard (`47735e7e`) | EMBODIED |
| L9 | Wait for a real turn boundary and prove the lane is not already running before any restart input | `prepare_draft` refuses with `already running; no restart input`; `run_phases` returns that as a standup, not a park | EMBODIED |
| L10 | Enumerate the project/session list by identity when the sidebar reorders | `01ae9065`, `ccefd568`, `94f209c0`, `a45e0e0e`, `18e82aa8` | EMBODIED |
| L11 | The app names a project and a chat alike; bind the row to the heading above it | `project_of_row`, `scoped_row`; `0c06ab16`, `6d9bd6b0` | EMBODIED |
| L12 | Do not overwrite a foreign or owner-staged draft; read the editor's own text first | `composer_written_route`; `e768fc24`, `c475cd56`, and `bcdeade5` for the expired-session + staged `/mission` combination | EMBODIED (refusal) |
| L13 | Resume an expired session by its own controls (Resume mission -> Start mission), or the app's send-again send | not built: the driver refuses and names the state (R7 partial) | MISSING |
| L14 | Create the app-side project (name + folder + first session) from the driver | not built: no adapter opens the New project dialog (R10) | MISSING |
| L15 | Capture a second running lane's Stop frame as paired evidence | `observe_bystander` exists and is wired for standing dispatches, but the paired separate-lane Stop capture is still the open T5 gap | MISSING (partial) |
| L16 | Publish per-lane state transitions on the heartbeat so a finishing lane is visible within one tick | not built: `heartbeat()` emits one line and a checkpoint (`7121240272` requires the transition lines) | MISSING |
| L17 | Keep a proof venv and its interpreter path durable | the documented `%TEMP%\harness-notepad-venv-20261122` no longer exists; the watch works only because `C:\Python314` happens to satisfy `windows_capture`/`PIL`/`driver_core` | MISSING (environment) |

### Queue items for every MISSING lesson

- **L13 -> R7**: implement the expired-session transition (Resume mission -> Start mission, else the app's send-again send) with the existing identity and consent gates, and prove it on one expired lane. Today it refuses by name, which is safe but not a restart.
- **L14 -> R10**: project-creation adapter (dialog discovery, name, folder, first session), built against the real dialog's controls, not guessed coordinates.
- **L15 -> T5**: paired Stop-frame capture from a lane that is not the target, with scope proving zero input to it.
- **L16 -> `7121240272`**: per-lane transition lines in the heartbeat (lane identity = title + thread, state, tick time), filed once per transition.
- **L17**: pin the driver interpreter in `control.json` (already done) **and** add a startup check that refuses with a named error when `windows_capture`/`PIL`/`driver_core` are missing, instead of failing inside a phase.

Two of these (L16, L17) are code with no desktop dependency and can be built in the next cycle without an idle window. L13 and L14 need the desktop at a lane boundary; L15 needs a second running lane.

**Closure is oversight's call**, not this filing's: this is the deliverable R11 asked for, and the MISSING rows above are now named items rather than gaps in the record.
