# Sergeant turn 14 - #636 hazard cured by W2, rail pending; no landing

Main: b03071a3 (unchanged). #295 read at turn start; newest comment 7010657144 (W2 turn 12) acked; no STOP.

## Observations (all live-verified this turn)
- #636 new head a990e0a9 (was 37efe8eb): MERGEABLE, ready (draft=false), state BLOCKED (rail mid-build).
  - Rail at exact head: 7/15 success, 0 fail, 8 pending - NOT green, unmergeable this turn.
  - Diff origin/main...FETCH_HEAD on docs/found-in-use.md: 2+/0- (one ASCII intake row only, zero rewrites).
    Body states: "Pre-existing mojibake in older rows is #631's and is cured by #635; this PR adds one ASCII row and rewrites nothing."
  - Verdict: W2 delivered the requested hazard-aware update. Preferred next once 16/16 at a990e0a9 (then Jev-then-Lucas at exact head, then land).
- #633 new head 451a0ef3 (was 4c76ca09): draft, BLOCKED, rail 14/15 + 1 pending (ui-playwright-smoke). Unmergeable; unblocker unchanged (W1 rail completion + ready-mark).
- #637 09190bdf: rail re-verified live 16/16 success, 0 fail - W2's terminal-green claim ACCEPTED as observed state. Draft evidence, unclaimed by me.
- #629 7255b7c1: open, MERGEABLE/BEHIND (draft flag null in API); W2 turn-9 evidence, parked, not in landing order.
- Census at b03071a3: list API 41 open; register 44 rows = 41 open + closed {311,407,419}; open-not-register = {} empty. Unchanged by construction (no landing).

## Gates
None run this turn - no merge attempted below green. Gates run Jev-then-Lucas at the exact head immediately before the #636 landing.

## Next
1. #636 - land on 16/16 at a990e0a9 (Jev, Lucas, receipt, census).
2. #626 rebase, #633 ready-mark, #628/#630/#625 updates - unchanged order.
