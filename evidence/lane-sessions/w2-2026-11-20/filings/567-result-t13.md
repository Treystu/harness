## W2 verification at 6ea96c29 - #567 log surfaces: all four answer authenticated, 401 unauthenticated; the 2026-11-16 transcript stays unrecoverable

**Revision under test.** Working tree HEAD **`6ea96c29fed9373e8a591085ca3173d18c9edd1b`** (operator tree, `sergeant/evidence-2026-11-19`), served on `127.0.0.1:8797` (pid 5212, startup marker `2026-11-19T14:28:15Z`). `git diff --name-only 4618b5f9..6ea96c29` is **evidence-only** (74 files, 0 product paths), so the product code under test is identical to `main` **`4618b5f9`**. Owner token read from the token store, never printed.

### What was executed

Four authenticated GETs plus the same four unauthenticated, in one probe (`probe_turn13.py`, receipt `probe-turn13.json`).

| Surface | Authenticated | Unauthenticated | Payload observed |
|---|---|---|---|
| `GET /api/chat/sessions` | **200** | **401** | `sessions` list, **80** session records |
| `GET /api/chat/history` | **200** | **401** | **5,292** typed turn records; keys `composition, confirmation, cost, dag, intent, prompt, response, stage_judgments, status, structural, target_files` |
| `GET /api/ledger/tail?n=3` | **200** | **401** | 3 rows, hash-chained (`prev_hash`, `hash`, `seq`), first `event: jev_eval`, with `decision_verdict`/`decision_disposition`/`supported`/`cost` |
| `GET /api/status` | **200** | **401** | `auth_required: true`, `events_buffered: 0`, `run_count: 0`, `recovered_count: 25`, plus `commit`/`version` |

### Verdict

**PASS for the audit's stand-up limitation at this head.** The limitation #567 recorded on 2026-11-16 ("not available: the running service's own log store") no longer holds for an auditor holding the owner token: sessions, typed turn history, ledger tail and status all answer, and the boundary is an auth boundary (401 without token) rather than a missing store.

**Not settled, and not claimed:** #567's three-turn Antigravity transcript has no wall-clock timestamps and no server-side capture in this store; that window remains independently unverifiable and nothing here authenticates it retroactively. #567's items 3-6 (Jev flush to fixed point, findings, remainder-of-hour loop, final filing) remain the issue owner's.

No product code changed. Intake: this receipt adds no new symptom; the surface state is the same one recorded on `583120b4`, now re-measured at the current head. Existing row `audit-traces-not-persisted` stays the owner-routed finding for the persistence family.
