## Register ledger at `4b905cc9` - R1-R19 each on a reachable commit, plus what the claim-and-execute attempt actually produced

Head of `laptop-vision-20261122`: **`4b905cc97d1593bf71bf62b1a96ed6b7f94de83b`**, pushed to `treystu`. Every commit below was ancestry-checked against this head with `git merge-base --is-ancestor <sha> HEAD` - all **in-head**, none merely named.

### 0. Gates on this filing, as returned

Product Jev (`jev-1.14.0`, decision-gate-v3, site `vision_standup_register_ledger`, private ledger): **escalate**, disposition **needs_improvement**, advances_goal **0.48** against the 0.95 rule-6 threshold, destructive **0.16**, confidence **0.25**. Lucas Gate v2: **pass**, artifact `ba54950d738e4385`. Receipt `evidence/lane-sessions/laptop-vision-2026-11-22/gates-register.json`.

Fail is not approve and escalate is not proceed, so this filing does **not** claim the pass is approved. What the low advance actually describes is the two items section 2 still marks as unproven against the world - R10 has never opened the real New project dialog, and R7 has never resumed a live expired lane - which is the same thing this filing states as open. Nothing in the pass changed a send authority, a model, a setting or a lane's state, and nothing irreversible happened: the branch is unmerged, and merges are the owner's alone, so a low-confidence pass sits exactly where it belongs - behind your decision, not in effect. Earlier in this same episode, the same gate escalated the auto-retry draft and that draft was **withdrawn** (`457ecdf4`), which is the precedent this receipt follows.

### 1. Verification at this head (what I ran, and what CI says)

| Check | Result |
| --- | --- |
| `python -m unittest discover -s tests -p "test_freebuff*.py"` | `Ran 82 tests ... OK` |
| `python -m ruff check scripts tests` | `All checks passed!` |
| `python -m compileall -q scripts tests` | clean (exit 0) |
| CircleCI at `4b905cc9` (read 04:55Z) | **`pending`**, 15 contexts: 4 `success` (`driving-hygiene`, `Checkout hygiene`, `local fit`, `installed package (windows-latest)`), 11 `pending`, 0 `failure`. **Not assumed green.** |

Revert proof for the two new cures: with `scripts/windows_freebuff_dispatch.py` and `scripts/windows_freebuff_runner.py` checked back to `4b905cc9~1`, the R7/R10 suites and the navigation suite give **`FAILED (errors=8)`** - `AttributeError: module ... has no attribute 'resume_staged_session'` and the pinning test's failure. Restored: **`Ran 45 tests ... OK`**. The cures are load-bearing, not decorative.

### 2. The register, item by item

| Item | Cure commits (all reachable from `4b905cc9`) | State |
| --- | --- | --- |
| R1 foreground contention | `9ac0f417` obtain-and-verify on every executor path, `a13660c8` re-assert | cured |
| R2 row identity | `0c06ab16`, `6d9bd6b0` project-scoped rows | cured; closes on the Stage 1 cold runs |
| R3 roster reorder | `01ae9065`, `ccefd568`, `94f209c0` inventory-first by identity | cured; closes on the SCM cold run |
| R4 compositor geometry | `50f8abaa`, `ee8e3843` recapture-and-retry with all guards rechecked | cured |
| R5 OCR scale | `4c5e6ae0` one scale for read and match | cured |
| R6 clipped-label confidence | `409d3ce0`, `6307da44`, `1206f883` prefix verified, exact OCR anchors; bar unmoved | cured |
| **R7 session expiry** | `bcdeade5` (refused the state by name) **+ `4b905cc9` (Resume -> Start execution)** | **cured**; closes on one expired lane's cold run (see section 4) |
| R8 renderer reload | `4e7812c5` detect-and-reprepare, `3725f613` re-open at send | cured; closes on the next mid-run reload survived |
| R9 driver-tree deadline | `75b3ce2c` verified stopped-tree retry; **`d0f59aec`** gives claimed dispatches the 240 s bound (the 65 s default killed claim `7119751841`); `457ecdf4` withdraws the auto-retry after Product Jev escalated it | cured; the bound is proven, the retry is oversight's to grant |
| **R10 project-creation adapter** | **`4b905cc9`** `create_project` + `Dispatch.create_project` | **built and unit-proven**; closes on the Stage 3 creation evidence the register names |
| R11 GPT lessons audit | `2591be98` (`evidence/.../filing-r11-lessons.md`, filed as `7122050642`) | filed; each MISSING lesson now maps to an item or a queue issue |
| R12 working banner / usage / corroboration | `fe1159aa` | cured |
| R13 live reorder, prefix rivals, click-move | `ccefd568`, `94f209c0`, `6307da44` | cured |
| R14 stale handle mid-enumeration | `a58c8ff4` | cured |
| R15 composer route guessed | `e768fc24`, `c475cd56` read the editor's own text first | cured |
| R16 deterministic section location | `a45e0e0e`, `18e82aa8` full-list walk with a scroll-settled end test | cured |
| R17 empty census read | `c475cd56` a non-empty census is required | cured |
| R18 foreign draft overwrite | `c475cd56` refuse by name, never type over | cured |
| R19 expired session + staged `/mission` | `bcdeade5` + `4b905cc9` (now resumed rather than only refused) | cured in code; the SCM Audit draft stays preserved and its leg is the owner's |

**R7 in detail.** `prepare_draft` used to raise `session expired with an existing staged /mission draft` and stop. The register's cure is "Resume then Start, else the send-again send", so `resume_staged_session` now locates `Resume mission` and `Start mission` by exact OCR, Jev-confirms each, re-reads before input, and proves a running Stop cue; `prepare` then prints `Platform state: resumed-and-running`, and the runner stops the phase list so `continue in full` is **never** sent over the resumed mission. Tests: `ResumeStartCureTests` (resumed / started / already-running / no-cue refusal) and the rewritten pinning test `test_prepare_draft_resumes_expired_session_with_staged_mission`.

**R10 in detail.** `create_project` opens the New project dialog through three exact-OCR anchors, types the name, reads it back off the field, creates it, and proves the new session row before returning that row as the handoff; a missing control refuses by name (`the create control 'Create project' was not visible`) with no further clicks and nothing typed. Tests: `ProjectCreationCureTests` (happy path incl. exact act order, missing control, name readback mismatch). **No live creation was performed**: Robby's Stage 3 act is out of this pass, and inventing a project on the owner's surface is not this cure's proof.

### 3. New defects this pass hit (proposed as R20-R22, per the hardening bound)

| Defect | Evidence | Cure |
| --- | --- | --- |
| **D-1** the watch could not claim the oversight's own restart: header had to start with `RESTART DISPATCH`, and the instruction is filed wrapped mid-quote (`"continue in\nfull"`) | dispatch `7122154514` sat unclaimed while the watch filed "no unclaimed dispatches" | `16947bdf` accepts a `DISPATCH ... RESTART` banner and compares the required words after flattening whitespace; prose that merely quotes them still claims nothing |
| **D-2** a single slow frame escalated a whole walk | `sidebar-top-3-after: capture exceeded 2s` | `4fcb03f8` retakes one slow frame within a 5 s budget, then refuses naming elapsed time and attempts |
| **D-3** the capture backend itself faults natively | Windows Application Error 1000, `pythonw.exe`, exception **0xc0000005 in GraphicsCapture.dll**, 04:38:57Z and 04:43:05Z; runs parked `search: driver exited unsuccessfully` with empty stdout and stderr | `7d44f056` takes frames in a worker process (`--capture-once`), retakes a dead worker once, refuses two by name with exit codes |

### 4. The claim-and-execute attempt: four claims, four executions, zero sends, no verdict

The watch - not a hand invocation - claimed and executed **four** dispatches end to end. Each ack and each result below was posted by the watch itself.

| Claim | Ack | Result | Outcome |
| --- | --- | --- | --- |
| `7119751841` | `7121986375` | `7122006869` | `search: driver tree terminated after deadline` (65 s default) -> `d0f59aec` |
| `7122154514` | `7122199249` | `7122220519` | `search: driver exited unsuccessfully` -> native capture fault -> `7d44f056` |
| `7122241209` | `7122259065` | `7122278698` | `search: driver exited unsuccessfully` (same AV) -> cured, retried |
| `7122320861` | `7122351117` | `7122412869` | `search: driver tree terminated after deadline` (240 s, **no crash**) |

Verified across all four evidence trees (`%LOCALAPPDATA%\harness-freebuff-runner\dyn-*`): `send_freebuff: 0`, `type_freebuff: 0`. Actions were `focus_freebuff` (4), `scroll_freebuff` (22), `click_freebuff` (7, all inside the sidebar walk). **Nothing was sent to Lane 1; no session was created; Lane 1 is unchanged and still down.** No duplicate, no takeover, and no model or settings change anywhere.

**Why there is no sustained-turn verdict, stated as the gate fact rather than smoothed.** The desktop-sovereignty gate was **open**, not closed: at 04:41Z `desktop_idle()` returned `True` with 774 s since the last input, and every claim above ran inside that window. What withheld the verdict is the driver's own **search bound**: run `7122320861` spent the full 240 s (04:48:20Z -> 04:52:26Z) in `navigate_by_unique_prefix` and was stopped at `prefix-unique`, having walked pages `prefix-1..8` plus the row-selection probes. The walk is deliberately exhaustive - it proves exactly **one** row can be the lane before clicking, which is the R2/R6 guarantee - and at ~30 s per page over 8 pages it does not fit in 240 s. An early exit is *not* a safe fix: stopping at the first page would break the uniqueness proof that stops a rival `Lane 1` row being chosen.

Two honest options, and the choice is oversight's:
1. **Narrow the list instead of walking it** - use the app's own `Search chats field` (already a control in the `query` phase) to bound the candidate set, then prove uniqueness inside the narrowed list. This is the cure I would build next; it is a real code change, not a bound change.
2. **Raise the search bound for this walk** to ~420 s - a one-line change, but it contradicts the "240 s search bound" precondition in `7122154514`, so I will not do it unilaterally.

Because the reserved dispatch is spent and I will not reinstate the escalated auto-retry, a further attempt needs either a fresh dispatch comment or one of the two decisions above. `desktop_idle()` is the only thing that would make a verdict impossible outright, and it was open throughout.

### 5. Open, and not claimed

- No sustained-turn verdict for launch, in-place restart or boundary restart: **none of them was achieved**, and no seconds-long Working frame was recorded as one.
- R2/R3/R8/R10/R19 close only on cold-run or Stage 3 evidence per the register; the code is in place, the closing evidence is not.
- The fill stages, Robby creation, Kanaloa stand-up, desktop-feed remediation and the acceptance run against `7094050344` were **not** attempted in this pass, per the owner's scope for it.
- PR #685, #701, #702 remain open and unmerged. SCM Audit stays held. The SCMessenger landing loop was never touched.
