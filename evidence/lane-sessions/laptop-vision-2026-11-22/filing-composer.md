## Lane 1 restart: three phases now pass, and it stops at the owner's own draft

Head: **`531a842d`** (code head `3545b950`), pushed to `treystu`. PR #685 OPEN, `mergedAt: null`. Nothing sent to any lane.

### 0. Gate, first and as returned

Product Jev (`decision-gate-v3`, site `vision_standup_composer`): **investigate / proceed**, advances_goal **0.83**, destructive **0.04**, confidence **0.56**, reason: `advances_goal 0.83 < threshold 0.95 ... proceed with a documented note if none is found`. Lucas Gate v2: **pass**, artifact `8be3deb5c923ac08`. Receipt: `evidence/lane-sessions/laptop-vision-2026-11-22/gates-composer.json`.

Documented note, as the gate's condition requires: the residual risk is that "stop" leaves the standup short of a RUNNING verdict. That is a cost this lane accepts deliberately - the alternative on the table was overwriting text the owner left in Lane 1's composer, and no restart is worth destroying unsent owner work.

Earlier gate this pass, for the record: `aa9c4658` (investigate / proceed, 0.87 / 0.09) for the route supplement and the opt-in narrowing.

### 1. The claim ladder: what each run proved

| Claim | Search | Query | Select | Prepare | Send | Ack / result |
| --- | --- | --- | --- | --- | --- | --- |
| `7124457637` | pass (`prefix-unique`) | pass | pass | **parked**: no route and no highlighted row | 0 | `7124475958` / `7124675461` |
| `7124952240` | pass | pass | pass | **parked**: same identity miss, with the row *visible* | 0 | `7124988196` / `7125175497` |
| `7125231144` | pass | pass | pass | reached the composer, **refused a foreign draft** | 0 | `7125239780` / `7125264923` |

`send_freebuff: 0`, `type_freebuff: 0` in all three receipt trees. Each ran the full phase list up to `prepare`; none typed into a lane and none sent.

This is the first time the search leg has completed at all: the exhaustive unique-prefix walk settled `prefix-unique` inside the unchanged 240 s bound, three runs running, with no early exit and no raised deadline.

### 2. Three cures, each derived from the previous run's trace

| Commit | Derived from | Cure |
| --- | --- | --- |
| `0a3310df` | `7123056197` read four rows of a different query | `query_search_field` requires the field's **own text** to come back carrying the label before any roster is read; foreign text is never typed over; a query that never lands refuses by name instead of censusing a stale panel |
| `d4afbd94` | `7124952240` parked with the lane open but out of view | `reveal_lane_row` scrolls the row into view in a bounded four pages - visibility only, never identity, and never during send |
| `3545b950` | the archived frames of `7124952240` | `selection_band`/`highlighted_row` find the selection by **its own fill** (47 against 24) in the row's left padding and match the band's measured centre to the row, instead of comparing two pixels at fixed offsets from the OCR box |

The band cure is proven on the live pixels, not only on synthetic ones: replayed over the two archived frames of `7124952240` (`reveal-lane-1-0.png`, `selected-row-probe-0.png`) the new detector returns **Lane 1** on both, and returns nothing on a band-free crop. The old probe returned nothing on the same frames even though the band was plainly painted.

Narrowed walk: still **opt-in** (`narrowing_enabled`, local flag), no flag present, so every run above took the exhaustive walk. Hermetic suite: `Ran 98 tests ... OK`.

### 3. The fixed point, named

`7125231144` reached the composer and refused, in the driver's own words:

```
composer-route: the composer holds a foreign draft, not 'continue in full';
not typing over it ('ownermodulewithanownertest100statementcoveragemeasuredbeforethefirstpush...')
```

Lane 1's composer holds **the owner's unsent draft** - it opens with an owner-module/owner-test and 100% statement coverage instruction - not this lane's `continue in full`. Three things follow, and only the third is mine to do:

1. Sending it would push an owner order into the lane under a restart authorization that names one text only.
2. Typing over it would destroy unsent owner work, which no restart instruction authorizes.
3. Refusing and filing is the correct end state for this dispatch, which is what `3545b950`'s run did.

This is not a driver defect and it is not the search walk: it is a precondition on the lane itself. **The Lane 1 restart cannot complete until the owner sends or clears that draft, or authorizes overwriting it.** I am not guessing which.

### 4. Verdict: the honest negative

**No RUNNING verdict, no START either.** Nothing was resumed or started, so the sustained-turn standard (lane's own new activity minutes later, never the start cue) had nothing to judge. Lane 1 is still down, unchanged, with its draft intact. No cold run for launch or boundary restart was taken: both are Lane 1 paths with the same composer, and the other lanes' restarts are the fill, which the order sequences after a Lane 1 verdict.

Desktop sovereignty was open throughout, not the blocker: `desktop_idle()` was `True` before the dispatch and every claim ran inside that window. Port 8765 is `LISTENING` on `127.0.0.1`.

### 5. Final head: real check states

| Check at `531a842d` (code `3545b950`) | Result |
| --- | --- |
| `unittest discover -s tests -p "test_freebuff*.py"` | `Ran 98 tests ... OK` |
| `ruff check scripts tests` | `All checks passed!` |
| CI target `ruff check harness tests examples/oc_handoff driver_core` | `All checks passed!` |
| `compileall -q scripts tests harness examples/oc_handoff` | exit 0 |
| CircleCI at the head | `pending` - 8 success / 8 pending at read |
| Full hermetic suite | `Ran 7858 tests ... FAILED (errors=1, skipped=88)` at `4b905cc9`; the single error is the pre-existing `test_serve_log_574`, and `git diff --stat 4b905cc9..HEAD` over its traceback modules is empty |
| Earlier heads this episode | 8 failed / 8 succeeded, and the docs-only `2591be98` failed the same eight contexts, so the red is not attributable to this branch on that evidence |

No CircleCI job logs were read (no CLI or token on this machine); the rail is reported as GitHub states it, not inferred.

### 6. What is still open

1. **Owner action on Lane 1's draft** - send it, clear it, or authorize overwrite. Then one restart dispatch completes the path and the sustained-turn verdict can be taken properly.
2. The launch and boundary-restart cold runs, which want that same lane free.
3. The narrowed walk stays unproven live and opt-in; its flag is off, so it cannot affect any watch run.
4. Everything the order sequences after a Lane 1 verdict: the fill, SCMessenger, Kalshi, BigEnergyCo, Disk Audit, Agensi, CivicScope, Harness Audit, Lane 2, Robby creation, Kanaloa, the register close, the audits and the acceptance run.

The owner's newest filing `7124370203` (SCMessenger, SCM-STOP-2049) was read and **not executed**: the scoring order makes that restart part of the fill, which runs after a Lane 1 verdict. #685, #701 and #702 remain unmerged; no mid-turn lane was touched; the stale `dyn-7117989632` receipt was left exactly as found.
