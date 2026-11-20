## W2 — #567: the log surfaces the audit could not read now answer; the 2026-11-16 transcript still cannot be recovered

Register home: #466. Nothing fixed by this lane; no product code touched.

**Revision under test.** Operator tree HEAD `583120b436ce747c40be8543c4fa8cbf686cb48b`, served on `127.0.0.1:8797` with the owner token (`X-Harness-Auth`); the operator UI on `:8765` untouched.

### The stand-up limitation, re-checked

#567's stand-up recorded: `http://127.0.0.1:8765/api/chat/sessions` and `/api/chat/history` returned `{"error": "This browser is not connected to Harness"}` and `HEAD /` returned 501. At this head, with an authenticated owner token, all four surfaces answer:

| Surface | Result at `583120b4` |
|---|---|
| `GET /api/chat/sessions` | **200** — session list with ids, previews, `updated_at` |
| `GET /api/chat/history` | **200** — typed turn records (`status: refused`, prompt, response text), not free prose |
| `GET /api/ledger/tail?n=3` | **200** — hash-chained `jev_eval` rows (`hash`, `cache_hit`, `cost`, `confidence`) |
| `GET /api/status` | **200** — `auth_required: true`, `events_buffered`, `run_count`, `recovered_count` |

Unauthenticated access still returns **401** on the same endpoints, so the earlier `501`/refusal was the auth boundary answering, not a missing store.

### What this does and does not settle for the audit

- **Settled:** the audit's own limitation ("not available: the running service's own log store") no longer holds for future audits at this head. An auditor holding the owner token can now read sessions, typed turn history, the ledger tail and service status.
- **Not settled:** the three-turn Antigravity transcript #567 examines has no wall-clock timestamps and no server-side capture in this store; the issue's own window statement ("cannot be independently verified from the log") stands unchanged. Nothing here authenticates that run retroactively, and this lane makes no attempt to.
- **Untouched:** #567's items 3-6 (Jev flush to fixed point, findings, remainder-of-hour loop, final filing) are the issue owner's, not this lane's.

Recorded as evidence only; #567 stays open.


**Gates, in order.** Product Jev (keyed `jev-1.14.0`, caller `w2-champion-audit`, site `audit_admissibility`, ledger seq 81520): verdict `escalate`, supported 0.29, cost $2.7006e-05. Lucas Gate v2 (typed track): `status: pass`, artifact `a6884f23b8a9dc96`. The Jev verdict is reported as returned, not re-run for a friendlier verdict; the disposition above rests on the observed run, not on the gate label.
