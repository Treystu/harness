## Lane 1 check-in - 2026-11-22, pass 5 (LD-002: #660 line 2 landed, line 1 designed and one ruling asked)

**Base read at start:** `main` `fda4fd301c1ec93b714c62bac1351ebc30d53a73`, zero open PRs, 40 open issues.
**Head at the end of this pass:** `main` `0e041435425422a9b2511b5afd4e413c346e7254`.

Comm lock: #295 read at turn start (960 comments; newest is the tick-782 stall
nudge `7078052569`, answered here) and re-read before each filing. No STOP
anywhere in the tail. Nothing supersedes the filed order.

### DONE

1. **#660 line 2 landed** - the snippet-versus-rendered evidence distinction,
   one of the two #343 acceptance sentences that were unbuilt when the operator
   ended #343. PR #663, head `c7262c23`, squash-merged as `75fe2a8a` on a fresh
   16/16 CircleCI read (including audit) at the exact head. 286 focused tests
   passed, ruff clean. The producer records what it read, one label helper
   names it to the model on both answer formatters, and the evidence block
   carries a legend that a snippet is not the page.
2. **Register corrected** - PR #664, head `a7bae835`, squash-merged as
   `0e041435` on its own 16/16 read at the exact head. The `#660` row no longer
   says "no code landed yet": it names the landing, the merge SHA, the half it
   covers, and line 1 as unbuilt. Census and both wave tables unchanged, since
   no disposition moved; `test_docs_contracts` and `driving_hygiene_ci` both
   green on the committed diff.
3. **#660 line 1 specified, not invented** - the design is filed in the same
   pass's landing record on #660: it mirrors the existing
   `evaluate_file_triage` seat, bands the noul into
   `relevant >= 0.70` / `rejected <= 0.30` / `uncertain` otherwise, records
   probability and reason per result, and excludes rather than down-ranks.

### WIP

- **#660 line 1 is not built.** No completion credit taken, on either line or
  on the issue.
- **#344 remainders** unchanged: approved-plan/receipt binding (the checkpoint
  has no plan-hash or Jev-receipt field) and saved native-route reuse across a
  changed request.

### NEXT

1. Build #660 line 1 as the designed slice, unless oversight rules otherwise.
2. Then #344's two named remainders, or whichever order oversight names.

### BLOCKERS

- **Ruling asked on #660:** what admission does when the reviewer cannot answer
  at all (refusal, spend limit, transport error). The acceptance text fixes
  rejected and uncertain, not reviewer outage. Until ruled, the build excludes
  and discloses the outage rather than admitting unreviewed evidence; see the
  landing record for the two candidate rules and why this lane did not choose
  between them silently.
- RSI #649-#652 stay parked on the ledger plan inputs that are not in the repo.
- W469: still 0 of 30 campaigns inside the window, so no verdict is possible.

### WAIT-STATE

idle: none.
