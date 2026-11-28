## Pinned route recorded, narrowed walk kept opt-in, one Lane 1 claim next

Head: **`0a3310df`** (pushed; `git ls-remote` agrees). PR #685 still OPEN, `mergedAt: null`.

### 0. Gate, first and as returned

Product Jev (`decision-gate-v3`, site `vision_standup_narrow_route`): **investigate / proceed**, advances_goal **0.87**, destructive **0.09**, confidence **0.37**, reasons: `advances_goal 0.87 < threshold 0.95 ... proceed with a documented note if none is found`. Lucas Gate v2: **pass**, artifact `aa9c4658c2f64144`. Receipt: `evidence/lane-sessions/laptop-vision-2026-11-22/gates-narrow-route.json`.

Documented note (the gate's own condition): the residual risk it names is a send landing in the wrong session, and that is bounded by the driver's existing pre-send gates rather than by this pass - `verify_session_identity` must bind the open session (route, exact scoped selection, or the staged draft), `pre-send-freshness` refuses past 60 s, and the one-send marker refuses a second send ever.

### 1. WIP census (re-taken, not inherited)

| Item | State this pass | Hands-off? |
| --- | --- | --- |
| Driver watch (`HarnessLaptopDriverWatch`) | `idle_watching`, `exit_code 0`, head `0a3310df`, last run 06:53:47Z | n/a - it is the driver being restored |
| `dyn-7117989632-2ae32937` | a **stale** one-line `claim` decision from 2026-11-23 16:11 local, 324-byte `runner.jsonl`, no live child, no phases | left untouched; not reused, not deleted |
| Lane 1 (`315608d2`) | idle since 2026-11-24T01:18:57Z; no driver input this pass | **yes** - only a cold-run restart may touch it |
| Every other lane (SCMessenger, Kalshi, BigEnergyCo, Disk, Agensi, CivicScope, Harness Audit, Lane 2) | no phase receipts newer than the last run; nothing mid-turn observed | **yes** - no send, restart or takeover |
| Port 8765 | `LISTENING` on `127.0.0.1` | n/a |
| Owner's newest filing `7124370203` | SCMessenger restart dispatch (SCM-STOP-2049) | not executed: the inherited order makes the SCMessenger restart part of the fill, which runs only after a Lane 1 sustained-turn verdict |

### 2. Step 2 of the order: pinned-route supplement, executed read-only

Filed authority `7118494622`, never run until now. Executed with the branch's own reader, no writes to app storage:

```
lookup_local_session_uuid("315608d2")
-> 315608d2-1531-456b-918a-f7e97db56496
```

Matches `PINNED_UUIDS[315608d2]` already in `scripts/windows_freebuff_dispatch.py` (line 52). Ledger entry, executed-dispatch form:

```
thread       315608d2
route        315608d2-1531-456b-918a-f7e97db56496
source       read-only FreeBuff Partitions leveldb/IndexedDB scan (7118494622)
bound in code PINNED_UUIDS + require_cached_session("verify-lane1-id", ...)
authority    #684 7118494622 (read-only, identifiers only)
sent         nothing
```

What this does and does not buy: it pins the identity the driver must see before a send, and `require_cached_session` proves the UUID exists in the app's stores. It does **not** replace the in-view proof - `verify_session_identity` still has to bind the open session at send time, and a UUID that exists in a store is not a UUID that is on screen.

### 3. Step 1: the focus-anchor state, honestly

`0a3310df` landed `query_search_field`, which clicks the field, types, and **requires the field's own text to come back carrying the label** before any roster is read; a field holding foreign text is never typed over, and a query that never lands raises instead of censusing a stale panel. 92 hermetic tests pass, including the three new ones (never-landed refusal, foreign-text refusal, landed readback).

What the live trace from `7123056197` shows is why this matters and where it stops: the click landed at `[619,197]` on the located `Search chats` label, `query_freebuff` was accepted, and the panel still returned four rows for a different query. So the readback gate is the right cure, and it has **not yet been measured live** - that is what the claim below is for. Per the order: if the field still does not filter, I will say so with the trace and move on rather than retry a third mechanism.

### 4. What happens next in this pass

One fresh Lane 1 restart claim through the watch, read from its trace. Success is the resumed/starting path with in-view evidence and `send_freebuff` at most 1 for `continue in full`; a refusal is filed by name with the step that stopped it. Then the sustained-turn verdict is taken the strict way - the lane's own new activity minutes later, never the start cue - or filed as a negative.
