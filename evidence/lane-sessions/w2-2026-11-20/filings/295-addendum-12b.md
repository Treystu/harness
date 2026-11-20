## W2 turn 12 addendum - #636 hazard cleared and terminal green; #637 terminal green

Comm lock: #295 re-read after status 7010657144 and after this turn's filings. Oversight read: sergeant checkpoints increments 13 and 15 (13:24:22Z, 13:41:55Z). No new oversight comment addressed to W2 and no STOP.

### 1. #636 was behind and carrying a hazard; both are cured

Increment 13 named the hazard correctly: my branch at `37efe8eb` was stacked on pre-#635 main, so merging it would have reverted #635's em-dash cure (10+/8- on `docs/found-in-use.md`: 8 lines of stale mojibake overwriting the cure, plus my row). Increment 15 then measured it at 7/15 mid-rail.

Rebuilt from the cured main as the sergeant asked - keep main's fixed rows, add only the new one:

- **New head `a990e0a9`**, base `b03071a3` (merge-base = `b03071a3` = main: up to date).
- **Diff: `docs/found-in-use.md +2 -0`** - the one intake row and its blank separator line. Nothing rewritten, nothing reverted.
- Content re-read byte-wise at the new head: **mojibake absent, 11 em dashes (the cure intact), 14 table rows** (13 + mine), LF only.
- **CircleCI at `a990e0a9`: 16/16 success, 0 failures, 0 pending, `ci/circleci: audit` success** - terminal green, read context-by-context at that head.

The car is ready and needs nothing further from W2.

### 2. #637 terminal green

At its current head **`09190bdf`**: **16/16 success, 0 failures, `ci/circleci: audit` success**, and its body now names that head. It carries this turn's two verdict filings, the CANON-1 inventory and the gate receipts.

### 3. State of the turn-12 deliverables (unchanged by this addendum)

- #468 per-brief verdict **7010347186**: YES - admissible, window W468, slot 1, identity PASS at `fb27ee89`, blocked on #628, no credit.
- #469 per-brief verdict **7010349175**: YES - admissible, window W469, slot 2, identity PASS, blocked on the unwired trace writer, no credit.
- CANON-1 inventory **7010350007**: ten brief numbers, nine live, one closed, and the "eight" reconciled to the one rule that yields it (#474), with my earlier "no rule yields eight" corrected on the record.
- Gate receipts: `gates-canon1-final.json` (Jev `investigate`/proceed x3, Lucas `pass` x3), published in #637 at `09190bdf`.

### Rail table, exact heads

| PR | Head | Base | CircleCI | GitHub |
|---|---|---|---|---|
| #636 intake row | `a990e0a9` | `b03071a3` | **16/16 incl audit** | MERGEABLE, up to date, ready |
| #637 evidence (draft) | `09190bdf` | `fb27ee89` | **16/16 incl audit** | MERGEABLE, BEHIND |

#637 is a draft evidence car and is now behind `b03071a3`; it needs a branch update only if the sergeant wants it landed, and it is not required for any deliverable above.

Gates for this addendum: product Jev investigate/proceed then Lucas Gate v2 pass (`gates-turn12b.json`), reported as returned.
