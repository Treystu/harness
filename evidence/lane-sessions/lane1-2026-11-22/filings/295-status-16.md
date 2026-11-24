## Lane 1 check-in - 2026-11-22, pass 7 (LD-002: #344 route binding landed, plan half named as a gap)

**Base read at start:** `main` `f4b2109922da6adc615ced558ef68d145cb2a2ef`, zero open PRs, 40 open issues.
**Head at the end of this pass:** `main` `900029a7e97a017a2e027ad947d11416b8b8b560` (PR #667, then register PR #668).

Comm lock: #295 read at turn start (966 comments; newest is the tick-797 stall
nudge `7080668682`, which named this pass's order) and re-read before filing. No
STOP in the tail. Nothing supersedes the filed order.

### DONE

1. **#660 line 1 landed and closed out** - PR #665 (`d6dec51f`) merged on a fresh
   16/16 at head `1a5ce93f`; the register row was corrected in PR #666
   (`f4b21099`) on its own 16/16 at `16a92df`. Landing record:
   #660 comment `7080870100`, gate receipt `7080870357`. Both acceptance lines
   are built; #660 stays OPEN because closure is the operator's call.
2. **#344 saved-route binding landed** - PR #667, head `0ba0a65`, 16/16 at the
   exact head including `audit`, merged as `baf65628`. A resumed checkpoint's
   saved native route decision is now bound to the request it judged
   (`_saved_route_decision_reusable`), so a changed request routes again instead
   of inheriting the old choice, an unchanged continuation still reuses it
   without paying twice, and the checkpoint persists `route_request_prompt` /
   `route_recorded_at` with the receipt. 57 focused tests and 383 in the wider
   affected set; ruff and compileall clean; changed lines measured executed.
3. **Register corrected in a separate PR** - PR #668, head `4c5c00a`, 16/16 at
   that head, merged as `900029a7`. The #344 row names the route binding and
   states the remaining item as a dependency: no `ResearchPlan` type exists
   (#342 owns it), so the plan hash cannot be computed. Census stays 40; the row
   stays OPEN. `driving_hygiene_ci.py` PASS and `test_docs_contracts` 15 passed
   on the committed diff before the PR.

### WIP

- **#344 approved-plan/receipt binding: not built, dependency-named.** The
  addendum requires an accepted ResearchPlan hash and its native Jev receipt.
  Neither type exists in the tree; #342 is the issue that creates them. The
  binding will extend the same predicate by compared field when #342 lands. No
  completion credit is taken for this half, and no field was invented.
- **#660 stays OPEN** with both lines built.

### NEXT

1. #342 (shared ResearchPlan + native Jev review lifecycle) is the next W5 item
   on the register and the dependency that unblocks #344's last half. It is a
   new feature slice, not a repair, so it starts as its own PR against the filed
   design rather than being improvised here.
2. Keep #660 and #344 OPEN; no disposition of either is this lane's to make.

### BLOCKERS

- **#344's remaining half is blocked on #342** by construction, not by choice.
- RSI #649-#652 stay parked on the ledger plan inputs that are not in the repo.
- W469: still 0 of 30 campaigns inside the window, so no verdict is possible.

### WAIT-STATE

idle: none.
