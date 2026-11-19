# Sergeant turn 22 - #630 parked; #638 stalled-rail note filed

Main: 4618b5f9 (unchanged). #295 read at turn start; newest was my own turn 21; no STOP.

## #630 (parked alone)
- Head 074be302 unmoved; still BEHIND (merge-base b03071a3); rail re-read 16/16 success. No merge attempted.
- Unblocker unchanged (W1's act): rebase onto 4618b5f9 + fresh 16/16.

## Forward advance: #638 stalled-rail note
- Head fbcb8cfb rail: 8 ok / 8 pending / 0 fail, UNCHANGED across two turns - the remaining 8 never started.
- Filed a factual rail note on #638 as 7011965233 (W1's eyes needed; possible stuck build, not a failure). Still draft, unclaimed. #475 stays OPEN.
- #634 post-merge rail: 4 ok / 10 pending, still rebuilding (expected, draft, unclaimed).
- No writer heads moved (#628/#633/#626/#625 unmoved).

## Census (two ways at 4618b5f9)
- List API: 41 open. Register: 44 rows = 41 + closed {311, 407, 419}; open-not-register empty. No delta.

## Queue
1. #630 rebase -> land (#471). 2. #638 rail+ready -> land (#475). 3. #626 W2 rebase. 4. #628 W1 ready-mark. 5. #633 W1 ready-mark + increment. 6. #625 W3 update.
