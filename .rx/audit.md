AUDIT - VISION STANDUP FAILURES (dispatch 7094753830, read-only)

ANTIGRAVITY: not used, and why. Antigravity 2.34.0.0 is installed and already running (pid 26256, window "Codex Findings Verificati..."), so it "opened"; what it will not do is take an audit mission read-only without hand-driving. Its only non-interactive surface is `Antigravity IDE/bin/antigravity-ide.cmd`, the VS Code CLI (open/diff/merge/goto/reuse-window) - no prompt mode, no stdin agent run, no headless audit. Relaying the mission to its chat panel means typing into another application's UI by hand, which the lane fences forbid and which would take the foreground from the FreeBuff queue mid-standup. Per the dispatch's own fallback clause, the audit below is the implementation lane's own, from the same evidence. All findings are read from `Treystu/slow-lane-ledger@laptop-vision-20261122:dispatch/laptop-driver/evidence/t8/` plus a read-only probe of this desktop at 08:0x-08:16Z.

== 1. ROOT CAUSE: driver method, not FreeBuff behaviour and not the crops ==

F1 - THE BINDING IS A STORED HANDLE PLUS A BYTE-EXACT TITLE, AND THE APP CHANGES BOTH UNDER IT.
Measured on this desktop, read-only, PID 6652 unchanged throughout: the same process owned top-level handle 51709886, then 4261648, then 3475728 within ~12 minutes with no input from me. A *fresh* enumeration each time resolved the exact title; a stored handle does not survive. `scripts/windows_freebuff_capture.py` stored `self.handle` once and then required `title_of(handle) == TITLE` forever, with a single-shot enumeration and no settle. That one defect produces all three park strings:
- `7094198934-0319b9f6/runner.jsonl` seq 1 (07:39:56Z) capture ok, `stop_cue: true`; seq 2 (07:40:12Z) "observe-running: BLOCKED: the bound FreeBuff window changed"; seq 4 (07:40:16Z) result "search: RuntimeError: expected exactly one visible FreeBuff application, found 0". A window that captured 16 s earlier became invisible-to-enumeration 4 s later.
- `7093818060-7d4a9b14-full-title-cure/runner.jsonl` seq 6 (07:35:03.608Z) "the bound FreeBuff window changed" and seq 7 (07:35:03.640Z) "prepare: BLOCKED: FreeBuff is not the foreground window" - the same 32 ms.
So the "found 0 windows" flake and the "lost the foreground" park are not separate classes; they are the stale-binding class, seen from the enumeration side and the foreground side.

F2 - THE SEARCH-DIALOG GATE IS A PROBABILITY, NOT A STATE.
`close_search_if_open` asked Jev "is a centered chat search dialog visible..." and branched at 0.9 / 0.2. On the SAME UI state the model answered both ways: `7093745521-2ae32937-search-dismiss-cure/project-census.jsonl` seq 1 (07:31:17Z) `open noul = 0.09`; `7093946738-918dad1a/search.jsonl` seq 1 (07:38:40Z) `open noul = 0.21`. The frame filed with the first run (`7093745521-2ae32937-search-dismiss-cure/before-freebuff.png`) shows the dialog plainly open, carrying a stale "BigEnergyCo" query and 13 results. 0.09 sent the driver on to click a magnifier over an already-open dialog; 0.21 parked it with "the current FreeBuff search dialog state is ambiguous" and zero input. The crop was correct - the magnifier, the placeholder and the X are all inside (488,150,1315,380). The decision was the defect.

F3 - ROWS ARE CENSUSED FROM A MOVING LIST AND RE-CHECKED 39 ms LATER.
`visual_project_pages` wheel-scrolls 240 px, sleeps 1 s, requires only that *some* pixels changed, and takes row y-coordinates from OCR; `visual_select_row` then re-captures and aborts on any difference. `7093745521-2ae32937-search-dismiss-cure/project-census.jsonl` seq 11 (07:31:39.141Z) and seq 12 (07:31:39.180Z) are exactly that pair, and the park is "a census row moved during project navigation". The row did not move on its own; the driver read a list that its own wheel step was still settling and had no settle rule, so it turned its scroll inertia into a refusal.

F4 - THE LABELS WERE GUESSES, NOT READINGS, AND SIDEBAR ROWS ARE CLIPPED.
- `7093818060-7d4a9b14/select.jsonl` searched the exact label "Kalshi" against a row titled "Kalshi Paper Burndown".
- `7093818060-0d7e2f37-native-logo-cure/select.jsonl` searched "BigEnergyCo" against 13 results that all begin "BigEnergyCo ..." or "BEC-..." and none of which equals it (the dialog frame above is that result set).
Exact-OCR equality cannot match a guessed title. Worse, the sidebar clips: this desktop currently reads "Kalshi Paper Burndov", "Kalshi Paper Rotation ar", "Kalshi-Trader Ovemight Bu", so even a correct title cannot survive byte-exact comparison in the session list. `708...`-series runs that used the search dialog instead still needed the title to be exactly right, which is why the same leg parked on every lane with the same shape.

F5 - THE IDENTITY GATE DIES WITH THE ACCESSIBILITY TREE.
`verify_active_session()` requires a UIA Document exposing a `/c/<uuid>` route. On a fresh handle today that same window exposes ZERO Document elements: `windows_freebuff_accessibility`-equivalent probe `windows_freebuff_active_session.ps1 -Window 4261648` returned `[]`, and a full descendant dump returned `{"count":0,"documents":[]}`. The census run at 07:31 did read `2ae32937-c991-4c33-87d4-68b8c956ba98`, so the tree is intermittent, not absent - which makes it a gate that fails a lane at random, independently of navigation.

VERDICT ON Q1: the driver's method. FreeBuff behaves consistently (one window, one dialog, one session list); the crops are correctly placed; every park is a single-shot decision - a stored handle, a probability band, an exact string on clipped text, or an intermittent tree - taken on a frame that was right.

== 2. FOREGROUND: WHAT HELD IT IN THE KALSHI PARK (7094487115) ==

Trace: `7093818060-7d4a9b14-full-title-cure/prepare.jsonl` seq 0 (07:35:00.978Z) capture "lane1-before-draft" with `foreground: true`; seq 1 (07:35:03.328Z) escalation "FreeBuff is not the foreground window". No action row between them: the prepare child captured, then `verify_lane` -> `require_foreground` refused 2.3 s later. The day's select click was at 07:34:55; the runner's "after" capture at 07:35:03.608Z is the same second as the refusal and reports "the bound FreeBuff window changed".

WHAT IT WAS NOT: not a driver FOCUS action (none was issued in that window of time), and not a human keystroke (the standing guard requires 60 s of desktop idle and no PAUSE was filed).
WHAT THE EVIDENCE CANNOT SAY, HONESTLY: the holder's identity. `capture_set` recorded only `foreground: <bool>`, and the refusal message carried no holder. No other application's title appears anywhere in the run, and the only two candidate holders in the same second are the old FreeBuff handle and its replacement - which is why I read the foreground as taken by the window's own replacement, exactly the F1 class. That reading is inference, not measurement, and it is the reason the cure now makes it a measurement: `require_foreground` files `holder`, `holder_detail` (hwnd + pid + exact title) on every refusal, and the capture trace now records `hwnd`, `pid` and `title`.

== 3. RESOLUTION: THE CHANGE THAT STANDS THE LANES UP (head 5f20f86) ==

1. BIND BY PROCESS, NOT BY HANDLE. `FreeBuffWindow` re-enumerates visible top-level windows owned by the FreeBuff.exe PID set, takes the one whose title begins "Freebuff" (the app rewrites the rest of it), settles up to 8 s, re-resolves on every use, and on failure files the census it saw (`found N; visible owned windows: hwnd:'title', ...`). A recycled handle rebinds instead of killing the leg.
2. DIALOG STATE FROM THE DIALOG'S OWN TEXT. `dialog_open()` OCRs its placeholder ("Search chats", fallback "chats"); `ensure_search_closed()` clicks the close control and polls until the placeholder is gone (<= 4 s). No model confidence is consulted anywhere in the reset, so "ambiguous" cannot recur.
3. SESSION LIST FIRST, SEARCH LAST. `walk_session_list()` scrolls to top, then per page takes TWO CONSECUTIVE IDENTICAL OCR censuses before reading rows, clicks "Show more" when present, and stops when the list stops moving. The search dialog is opened only if the label is absent from the list.
4. SELECTION PROOF. A settled roster must yield exactly one matching row - exact, or a clipped prefix with a 2-glyph edge-slip allowance ("Kalshi Paper Burndov" now matches); the click is re-read against that row's pixel band; then the sidebar's highlighted row must read the same label. Every refusal names the roster it saw, so the next iteration reads the real titles out of the evidence instead of guessing again.
5. IDENTITY WITHOUT THE TREE. `verify_session_identity()` uses the route when the tree offers one, otherwise the settled highlighted sidebar row, and records which proof it used. An absent tree no longer parks a lane.

VERIFIED BEFORE ANY LANE RIDES ON IT:
- 10 focused tests pass (`tests/test_freebuff_navigation.py` added, `tests/test_freebuff_watch.py` unchanged): two-census settle, never-settling refusal, ambiguous-row refusal naming candidates, clipped-label matching.
- The roster and highlight primitives were run against a live capture of this desktop: 15 rows read, `Lane 1` correctly identified as the highlighted row, clipped "Kalshi Paper Burndov" correctly matched to "Kalshi Paper Burndown".
- Capture re-ran through the new discovery against a recycled handle: bound pid 6652, hwnd 3475728, title recorded, 0.596 s.
- Not verified: no lane has been stood up on this build yet. That is the next step and its evidence follows on this issue, per the push dispatch's velocity order.

Head: 5f20f8643180854a2889d174f9934e10c877b1e9 (PR #685, not merged).
