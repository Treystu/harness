# Lane evidence — #334 log_judgment status (2026-11-13)

**Item:** #334 — [mcp][LOW] `log_judgment` reports ok when zero items were
live-judged.

**Delivery state:** READY-TO-MERGE — HAR-SAMS merges; author does not.
No pull request could be opened from this lane (see the #299 record on
`lane/core-299-post-body-cap` for the same capture: server-side credential is
fetch/pull/push only, `gh` unauthenticated, REST 403). This record replaces
the PR body. Rail: **NOT CHECKED from this lane** — no named CircleCI status
is readable here, and no combined status is offered as evidence.

**Branch:** `lane/core-334-log-judgment-status`
**Fix commit:** `2cdb4a23f6a394f320d67c91c16c55381bcad65e` — the tree every
count below was measured on.
**Branch tip:** `bbc6518d380a8c5b22a446e09929743e8d3ec26a` — the fix plus this
record (docs only). Correction, 2026-11-13: this line originally named the fix
commit as the head; the head a merger checks out is the tip, which advances by
the record commit. Both are stated so neither is mistaken for the other.

## Defect

`McpServer._invoke("log_judgment", ...)` returned a hardcoded
`"status": "ok"`. A run in which every item was fallback-judged — no Jev key,
degraded backend — still analyzed the log but judged nothing live, and the
envelope reported unqualified native success. The suite pinned the defect:
`test_mcp_envelope_carries_analysis_and_coverage` asserted `status == "ok"`
on an explicitly unkeyed policy whose coverage records
`live_judged: 0, fallbacks: 5`.

## Fix

- `_log_judgment_status(analysis)` derives the status from
  `coverage.live_judged`: `ok` only when at least one item was live-judged,
  `no_live_judgments` otherwise.
- The coverage block is unchanged and still returned in full, so fallback
  provenance (`total_items`, `fallbacks`, `live_judged`) survives a degraded
  run rather than being hidden behind the status.
- The assertion that encoded the defect now asserts the honest outcome, and a
  stub live policy pins the `ok` path. No thresholds, no canon rows, and no
  other tool face changed.

## Evidence on the exact head

| Suite | Result |
| --- | --- |
| `python3 -m unittest tests.test_jev_log_envelope tests.test_jev_log_judgment tests.test_mcp` | Ran 137 tests, OK |
| `python3 -m unittest tests.test_jev_core_hardening tests.test_model_envelope` (development pass, same code) | Ran 269 tests, OK across the four jev/mcp suites |
| `ruff check harness/mcp.py tests/test_jev_log_envelope.py` | All checks passed |

## Second, independent method (not the same run twice)

The unit suite mocks the transport and calls `server._invoke` directly. The
second check spawns the MCP server as its **own process** over real stdio —
JSON-RPC frames in, wire envelope out (`structuredContent`, and the
`content[0].text` fallback), with an unkeyed Jev policy so every judgment is
fallback. It reads the status an MCP client would actually receive:

```
process exit: 0
status: no_live_judgments
coverage: total=5 live_judged=0 fallbacks=5
buckets: {'ble': 2, 'transport': 1}
probe: PASS
```

The same probe against the pre-fix hardcoded status would have printed `ok`;
the bucket tallies match the unit expectation, so the analysis itself is
unchanged and only the claim about it moved.

## Integration evidence

Merged onto current main (`9967aa8a3ff513cac3cbb8ccff52550622e009d3`) alone
and together with #299/#445: see
`lane/core-integration`, `docs/audit/LANE_EVIDENCE_INTEGRATION_2026-11-13.md`.

## Not checked

- CircleCI rail statuses on this head (no access from this lane).
- A second non-author reviewer verdict (no reviewer reachable).
- A genuinely keyed live-judgment run: no operator key exists on this
  machine, so the `ok` path is pinned by a stub policy, not by live Jev.
