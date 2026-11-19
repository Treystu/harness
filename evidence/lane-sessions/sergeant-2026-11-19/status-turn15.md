# Sergeant turn 15 - landing pass: no car green-and-runnable; #636 up-to-date, rail pending

Main: b03071a3 (unchanged, re-fetched this turn). #295 read at turn start; newest is my own 7010799174; no STOP.

## Rail reads (CircleCI commit statuses at exact heads, live this turn)
- #636 a990e0a9: 7/15 ok, 0 fail, 8 pending (smoke, test, 6x hermetic) - NOT green. merge-base(a990e0a9, main)=b03071a3 = main: UP-TO-DATE. Diff: 2+/0- docs/found-in-use.md only. Ready (draft=false), MERGEABLE. Blocked solely on rail completion.
- #633 451a0ef3: 15/16 ok, 0 fail, 1 pending (ci/circleci: audit) - NOT green. Draft, BLOCKED.
- #626 cc192ddf: 16/16 incl audit - GREEN at head but BEHIND main (predates #635). Strict protection refuses not-up-to-date heads. Unblocker: W2 rebase.
- #625 7bc45715: 15/15 green at head but CONFLICTING/DIRTY. Unblocker: W3 update.
- #628 7cf5ef8d: 15/15 green at head but CONFLICTING/DIRTY. Unblocker: W1 update.
- #630 0c591c87: 15/15 green at head but draft + BEHIND. Unblocker: W1 update + ready-mark.
- #637 09190bdf: 16/16 green, draft evidence, not in landing order.

## Decision
No car is simultaneously ready-marked, up-to-date, and green at its exact head. Nothing merges this turn (never merge below green at exact head). #636 remains preferred next: up-to-date + clean + ready, waiting only on its rail.

## Gates
None run - no merge attempted. Jev-then-Lucas run at the exact head immediately before the #636 landing.

## Census (at b03071a3, unchanged - no landing so no delta expected; re-verified turn 14)
List API 41 open; register 44 rows = 41 open + closed {311,407,419}; open-not-register = {} empty.
