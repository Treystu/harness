# Lane evidence — integration of #299, #334, #445 (2026-11-13)

**Delivery state:** READY-TO-MERGE — HAR-SAMS merges; author does not.
**Rail: NOT CHECKED from this lane** — no named CircleCI status is readable
here, and no combined status is offered as CI evidence. GitHub Actions
check-runs on this repository are a billing lock, not a signal, so they are
not read either.

This record is the merge case for three lane branches. Each item's own record
carries its defect, fix, and per-head evidence; this one carries what a merger
actually needs: the exact heads, that they merge, and that the combination is
proven by behavior.

## Items and exact heads

Base for every merge test: **main `9967aa8a3ff513cac3cbb8ccff52550622e009d3`**
(the head named at the start of this pass, unchanged by it).

| Item | Branch | Fix commit (measured tree) | Delivery tip at integration time |
| --- | --- | --- | --- |
| #299 POST body cap | `lane/core-299-post-body-cap` | `643fc8988f3d48f8af9b3e0815e3d159a65f8dd1` | `74c155f89cf7855ef44f58dfdb209f72117cdd49` |
| #334 log_judgment status | `lane/core-334-log-judgment-status` | `2cdb4a23f6a394f320d67c91c16c55381bcad65e` | `081dd363320e14f72d774773c579cfadf686589b` |
| #445 pyright / plan+execute | `lane/core-445-server-pyright` | `5fea30e73800b082d57cda8c47dfa702ca6971f5` | `7753384447b269688fa19e8282fa698e1a769220` |

A record-only commit written after the merges were proved advances a tip
without touching the code tree, so the tip a merger checks out is read from the
remote (`git ls-remote`), and the sha above is what the merge tests used. Each
item record states the same thing for itself.

Heads were read from the remote (`git ls-remote`), not from local pointers.
Record corrections made during this pass, stated as corrections rather than
rewritten history: the #299 and #334 records named their *fix* commit under a
label that read like the branch head, and the #445 record carried no SHA at
all. All three now name the measured tree and say explicitly that later record
touches are documentation only. Those corrections advanced each tip by one
docs-only commit; `git diff --stat <tested-tree> <final-tip> -- harness tests
driver_core` is empty for every one of them, so no measured result moved.

## Merge cleanliness

**Each item alone, onto main `9967aa8`:** clean, no conflicts.

| Item | Scratch merge head | Code tree |
| --- | --- | --- |
| #299 | `2164cb0` | identical to the fix commit |
| #334 | `57a4537` | identical to the fix commit |
| #445 | `3d79a6f` | identical to the fix commit |

**All three together, in the order #299, #334, #445:** clean at every step.

- Earlier combined tree, pre-correction tips: `b1d9331` — this is the tree the
  full suite union and all three probes below ran on.
- Final combined tree, final tips: `4f5272556ba65ba6f90a66324bb329f1960d36d3` —
  `git diff --stat b1d9331 4f52725 -- harness tests driver_core` is empty, so
  the tested tree and the mergeable tree are the same code.
- Re-checked on the final head: `pyright --pythonversion 3.9` on
  `harness/server.py harness/mcp.py harness/agent.py harness/spend.py` →
  `0 errors`; `ruff check` on those plus the two touched test modules → clean;
  `PostBodyCapTests + test_jev_log_envelope + test_plan_http_batch` → Ran 37
  tests, OK.

**Conflicting paths:** none. The only shared file is `harness/server.py`,
touched by #299 (the POST read path and the handler header) and #445 (the
overridden stdlib parameter names, the `ui` property, `run_plan_task`, the
duplicated route removal, and two route/assert sites). Git merged both sides
cleanly and the combined tree contains both behaviors; nothing was dropped or
hand-edited to make the merge pass.

## Suites on the combined tree, per module

Combined tree `b1d9331` (code identical to `4f52725`); every module below was
run separately on it, all OK.

| Suite | Tests |
| --- | --- |
| `tests.test_server` | 120 |
| `tests.test_server_driver` | 58 |
| `tests.test_site_server` | 29 |
| `tests.test_intake` | 13 |
| `tests.test_jev_log_envelope` | 19 |
| `tests.test_jev_log_judgment` | 8 |
| `tests.test_mcp` | 110 |
| `tests.test_plan_http_batch` | 13 |
| `tests.test_agent` | 113 |
| `tests.test_jev_ledger_spend` | 14 |
| `tests.test_agent_run_limits` | 11 |
| `tests.test_agent_desktop_audit_report` | 11 |
| **Union** | **519, all OK** |

No regressions against the per-branch results: #299's own set is 220 on its
merged-alone tree (`test_server` 120 + 58 + 13 + 29); #334's is 137; #445's is
255 on its merged-alone tree. The only count that moves is `test_server`,
115 on the #445 tree and 120 on the combination, because #299 adds the five
`PostBodyCapTests`. That is an addition, not a lost test.

## Second method per item, re-run on the combined tree

Each was re-run on `b1d9331`; all three passed.

1. **#299 — raw socket against a live server**, 500 MB announced and never
   sent, with the server's own `VmRSS` sampled either side:

   ```
   status: HTTP/1.1 413 Request Entity Too Large
   refusal seconds: 0.001
   rss delta KiB: 0
   probe 299: PASS
   ```

2. **#334 — the MCP server as its own process**, real JSON-RPC over stdio,
   unkeyed policy, reading the wire envelope a client receives:

   ```
   process exit: 0
   status: no_live_judgments
   coverage: total=5 live_judged=0 fallbacks=5
   buckets: {'ble': 2, 'transport': 1}
   probe 334: PASS
   ```

3. **#445 — the real `run_plan_task` with the real `PlanExecutor`**, driving
   both call shapes (only `apply_session` and `compose_plan` doubled):

   ```
   old call: TypeError: PlanExecutor.__init__() got an unexpected keyword argument 'dag'
   new call: status=ok execution=True
   probe 445: PASS
   ```

## Merge recipe

```
git checkout 9967aa8        # current main
git merge --no-ff lane/core-299-post-body-cap
git merge --no-ff lane/core-334-log-judgment-status
git merge --no-ff lane/core-445-server-pyright
```

The scratch branches used for these results are local only and are not pushed;
the recipe above reproduces them from the three tips.

## Not checked

- CircleCI rail statuses on any of these heads or on the combination (no
  access from this lane; a named per-status read on the exact head is still
  required from a lane that has it).
- A second non-author reviewer verdict on any item or on the integration.
- Repository-wide pyright debt: 741 errors remain across `harness/` and
  `driver_core/` at `9967aa8`, outside the modules touched here.
- Live GUI/LAN traffic: the #299 cap was exercised over loopback only.
- A genuinely keyed live-judgment run: no operator key exists on this machine,
  so #334's `ok` path is pinned by a stub policy.
