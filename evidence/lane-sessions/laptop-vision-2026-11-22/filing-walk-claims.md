## The narrowed walk, three live claims, and why there is still no verdict

Head of `laptop-vision-20261122`: **`39de2ae2`**, pushed to `treystu`. This pass tried to cheapen the unique-prefix walk the way the order asked, measured what the app's search surface actually does, and **declined to ship the unproven default**.

### 0. Gate receipt, as returned

Product Jev (`jev-1.14.0`, decision-gate-v3, site `vision_standup_walk_claims`, private ledger): **investigate / proceed**, advances_goal **0.65**, destructive **0.04**, confidence **0.30**. Lucas Gate v2: **pass**, artifact `b2a23bfbe33e35b8`. Receipt `evidence/lane-sessions/laptop-vision-2026-11-22/gates-walk.json`.

Earlier in the same episode, for the record: the retry-authority draft was **escalated and withdrawn** (`457ecdf4`), and the R7/R10 pass was filed as **escalate / needs_improvement** (`7122501428`) rather than as approval.

### 1. The walk cure: built, tested, measured, and deliberately not default

| Commit | What it does |
| --- | --- |
| `5308f5bb` | narrows the candidate set with the app's own search field, then runs the **same** `candidates_in` collection, `prefix-exact-wins` rule and one-candidate census over the filtered roster; 240 s untouched, no early exit |
| `c8c9f085` | opens the search dialog through an extracted, verified `ensure_search_dialog` (routing through `open_search` would have restored the eight-page walk) |
| `ca34d347` | reads `SEARCH_RESULTS`, the panel the field actually filters, after the trace showed the field does not filter the sidebar |
| `39de2ae2` | **returns the exhaustive walk to the default**, keeps narrowing as `narrow=True`, and pins the default with a test so an unproven path cannot silently become the one the watch uses |

Hermetic tests (all passing, `Ran 89 tests ... OK`): one candidate on the filtered roster is picked; two non-exact rivals are refused by name; an exact title wins over a row that merely opens with it; a query already in the field is not typed twice; a missing field refuses by name without walking; the default is the exhaustive walk.

**What the live traces measured** - this is the part that decides the default:

- `7122996519`: after the field received "Lane 1", the **sidebar census still returned 54 unfiltered rows**. The field does not filter the sidebar.
- `7123056197`: reading `SEARCH_RESULTS`, the panel returned **4 rows for a different query** - `['Vision Driver Standup Completion', 'GitHub Lane Oversight Duties', 'Harness Audit Lane', 'Vision Driver Standup Completion']` - because the field was never focused (`narrow-search-field-tail` was reached only through the fallback locate), so the keystrokes went nowhere. Census: `candidates: [] count: 0`.

So the narrowed walk is **written and unit-proven but not proven against the live panel**. Making it the default would have replaced a walk that is correct with one that finds nothing, which is why `39de2ae2` reverts the default. What remains to prove is narrow: focusing the search field reliably in the select phase (the `Search chats` placeholder is not OCR-visible in this build, so the focus click needs its own anchor).

### 2. Three more claims, all claimed and executed by the watch, all zero sends

| Claim | Ack | Result | Outcome |
| --- | --- | --- | --- |
| `7122882994` | `7122912547` | `7122978670` | search + query **passed** (first time any run got past search), then `select: BLOCKED: the project session list does not hold 'Lane 1'` - narrowing ran without the dialog in that phase |
| `7122996519` | `7123006898` | `7123043916` | `search: BLOCKED ...` - narrowing read the unfiltered sidebar (54 rows) |
| `7123056197` | `7123069348` | `7123093119` | `search: BLOCKED ...` - narrowing read a stale results panel (4 rows, different query) |

Actions across the three evidence trees: `send_freebuff: 0`, `type_freebuff: 0`; the only text input is `query_freebuff: 1` per run, which types the label into the app's own search field, not into a lane. **No lane was sent to, no session created, no model or setting changed.**

Combined with the four claims filed earlier (`7119751841`, `7122154514`, `7122241209`, `7122320861`), the watch has now claimed and executed **seven** dispatches, every one ack'd and resulted on #684, with **zero sends**.

### 3. The verdict: none, filed as a negative

**No RUNNING verdict is claimed, and none is implied.** No dispatch reached `prepare` or `send`, so no lane was resumed or started, and the sustained-turn standard (25 s observation plus a second corroboration minutes later) never had anything to observe. Lane 1 remains **down** and unchanged; its own queue was not touched.

The desktop-sovereignty gate was **open**, not closed: `desktop_idle()` returned `True` at 05:20Z (774 s since last input) and every claim above ran inside that window. The withholding cause is the driver's search leg: the exhaustive walk is correct but costs more than the 240 s bound, and the narrowed replacement is not yet proven.

Cold runs for launch, in-place restart and boundary restart were **not** executed, because no dispatch reached the phase that would drive them; they remain for the window after the search focus anchor is cured.

### 4. Final head: check states as they actually are

| Check at `39de2ae2` | Result |
| --- | --- |
| `python -m unittest discover -s tests -p "test_freebuff*.py"` | `Ran 89 tests ... OK` |
| `ruff check scripts tests` | `All checks passed!` |
| CI's own targets: `ruff check harness tests examples/oc_handoff driver_core` | `All checks passed!` (exit 0) |
| CI's own targets: `compileall -q harness tests examples/oc_handoff` | exit 0 |
| `compileall -q scripts tests` | exit 0 |
| Full hermetic suite | `Ran 7858 tests ... FAILED (errors=1, skipped=88)` at `4b905cc9`, the one error being `test_serve_log_574` |
| Proof it is not this branch | `git diff --stat 4b905cc9..HEAD -- harness/` is **empty**, and `-- tests/test_serve_log_574.py harness/ui.py harness/server.py harness/osal.py` is **empty**: nothing in the failing traceback changed in this pass, and it fails standalone with and without `-W error::ResourceWarning` |
| CircleCI at `39de2ae2` | **`pending`** at read (no statuses posted yet). At `4b905cc9` it was 8 failure / 8 success, and the **docs-only** `2591be98` failed the same eight contexts - a docs commit cannot break six hermetic legs on three OSes - which is the evidence for not attributing the red to this branch |

I did not read CircleCI job logs (no CLI or token on this machine), so the red is reported as **not attributable on the evidence above**, not as infrastructure confirmed.

### 5. Open

1. Focus anchor for the search field in the select phase, so `narrow=True` can be measured live; then either it becomes the default on evidence or the 240 s bound question goes to oversight with that measurement.
2. The sustained-turn verdict for Lane 1, and the launch / in-place restart / boundary restart cold runs, which need a dispatch that reaches `prepare`.
3. The pre-existing `test_serve_log_574` error (`'_Thread' object has no attribute 'is_alive'` under Python 3.14) - a real defect, outside this register and untouched here.
4. Everything the pass scope excluded: fill, Robby creation, Kanaloa stand-up, desktop-feed remediation, acceptance.

PR #685, #701 and #702 remain open and unmerged. No mid-turn lane was touched; SCM Audit stays held.
