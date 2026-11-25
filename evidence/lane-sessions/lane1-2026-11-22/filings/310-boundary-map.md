## #310 boundary map — `harness/provision.py` split by trust boundary

Measured on `treystu/main` at `746e3621`, where `harness/provision.py` is 2381
lines. The module already carries five section banners; the map below takes
those as the starting seams, checks each one against what its code actually
does, and fixes the extraction order. Line ranges are the section ranges at
that head, so a reader can land on them with `git show 746e3621:harness/provision.py`.

### The seven seams

| # | Seam | Lines at `746e3621` | Symbols | Side effects | May import |
|---|------|--------------------|---------|--------------|------------|
| S1 | vocabulary | 69-139 | `READ`/`MUTATING`/`IRREVERSIBLE`, `CLASSES`, `_SEVERITY`, `APPROVE`/`DECLINE`/`DEFER`, `DECISIONS`, the run outcomes (`COMPLETED` ... `ALREADY_DONE`), `PROVISION_EVENTS`, the `DEFAULT_*` limits, `_PROBE_TIMEOUT_S`, `PROBE_PACKAGE_MANAGERS`, `_SYSTEM_MANAGERS`, the `RECIPE_*` ids and `_RECIPE_DESCRIPTIONS`, `ProvisionError` | none | stdlib only |
| S2 | host probe | 140-347 | `PackageManager`, `HostProbe`, `probe_host`, `_probe_body`, `_first_line`, `_existing_ancestor`, `_default_facts`, `_parse_nvidia`, `_parse_rocm` | read-only host queries through `osal` (10 s timeout each); reads disk/platform facts | S1 |
| S3 | typed plan | 348-546 | `Step`, `Plan`, `step_from_dict`, `plan_from_dict`, `_canon`, `_sha256`, `_safe_text`, `render_plan`, `_STEP_ID_RE` | none (pure data + hashing + escaping) | S1 |
| S4 | argv allowlist | 547-1257 | `ProvisionPolicy`, `policy_for_probe`, `Admission`, `classify_argv`, `_classify_core`, the `_admit_*` grammars, the path checks (`_path_problem`, `_within_roots*`, `_require_in_roots`, `_check_executable`), `validate_step`, `validate_plan`, `needs_approval` | none: it decides, it does not act | S1, S3 |
| S5 | approval gate | 1258-1406 | `ApprovalRecord`, `ApprovalGate`, `_now` | appends one `provision_approval` entry to the ledger per decision; never executes | S1, S3, the ledger seam |
| S6 | executor | 1407-1954 | `StepResult`, `ExecutionReport`, `execute_plan`, `_scrubbed_env`, `_resolve_command`, `_builtin_mkdir`, `_verified_done`, `_clean_stale_private_dirs`, `_require_real_ledger`, `_private_cwd_parent` | launches processes, mutates the host, writes ledger entries, creates/removes private directories | S1, S3, S4, S5, `osal`, the ledger seam |
| S7 | planner / recipes | 1955-2381 | `PackageRequest`, `extract_requests`, the `_recipe_*` builders, `applicable_recipes`, `_jev_select`, `_jev_review`, `plan_provision` | reads the probe; may call the model (Jev selection/review); writes nothing to the host | S1, S2, S3, S4, the Jev seam |

The split that matters for trust is between **deciding** (S1, S3, S4: no
effects) and **acting** (S5 persists consent, S6 acts, S7 proposes). S2 is the
one read-only host reader; S7 is the one model-facing proposer.

### Dependency direction (one way, always)

```
S1 -> (nothing)          S3 -> S1                S4 -> S1, S3
S2 -> S1                 S5 -> S1, S3, ledger    S6 -> S1, S3, S4, S5, osal, ledger
S7 -> S1, S2, S3, S4, jev
```

No lower seam may import a higher one. That is what makes the extraction safe
one slice at a time: a module that only ever imports downward cannot create a
cycle with the facade.

### Extraction order (one PR per slice, behavior unchanged)

1. **S1 + S3 -> `harness/provision_plan.py`** (this filing; PR below). The pure
   vocabulary and the typed plan. `provision.py` imports only the names it uses,
   and every other caller imports the plan types from the owner: this repository
   forbids re-export facades (`tests/test_architecture.py`), so a split that
   kept `pv.render_plan` as an alias would fail the build by design. The call
   sites were moved instead of bridged.
2. **S5 -> `harness/provision_approval.py`**: approval records and the gate,
   with the ledger still injected, never opened by the module.
3. **S6 -> `harness/provision_exec.py`**: the executor, the only seam that
   launches processes, still calling `validate_step` immediately before each
   run.
4. **S4 -> `harness/provision_admit.py`**: the allowlist and the policy type.
5. **S2 -> `harness/provision_probe.py`** and **S7 ->
   `harness/provision_planner.py`**: the reader and the proposer.

`provision.py` then holds the facade (probe -> plan -> approve -> execute) and
the re-exports, and nothing else. Order is fixed by the graph above: each step
moves a seam whose dependencies have already moved, so no slice needs a
forward import or a runtime late import to break a cycle.

### Invariants that must hold at every slice

- One authoritative approval gate; a plan-level yes never covers an
  `IRREVERSIBLE` step, and decline/defer stay terminal for that digest.
- Root and scheme admission policy unchanged: argv lists only, no shell, no
  privilege escalation, no deletion, no URL or path installs.
- One durable completion receipt per plan, approval and step; no replay of an
  uncertain execution (`_verified_done` reads the ledger, not a local flag).
- No behavior change outside module structure: the moved code is the same code.
  Each name has exactly one import path (its owner); there is no alias layer to
  drift, which is the rule `tests/test_architecture.py` already enforces.
- The hermetic provisioning tests stay the behavior contract: allowed/denied
  commands, approval changes, checkpoint/resume, partial execution, uncertain
  receipts, temporary roots and injected runners only.

### What this map does not claim

- No real package-manager install was exercised, here or in the audit that
  filed this issue: that mutates the host, and the acceptance criteria forbid
  it in tests. S6's host-level path is covered by injected runners, not by an
  install.
- The line ranges are a reading of `746e3621`, not a generated artifact; if the
  module moves before a slice lands, the symbol names, not the numbers, are the
  contract.
- This is a plan for six further slices. Issue #310 stays open after slice 1,
  and this lane takes no completion credit for the split as a whole.

### A constraint the first slice found

The obvious bridge -- have `provision.py` re-export the moved names so no call
site changes -- is forbidden here. `tests/test_architecture.py::
ImportDirectionTests.test_no_reexport_facades` fails any module that imports
another module's name and does not use it, with the instruction "import from
the owner at the use site". The first head was red for exactly that reason and
the cure was to move the call sites, not to weaken the rule: `cli`, `mcp`,
`server`, `task_lifecycle` and the provisioning tests now import `render_plan`
or `plan_from_dict` from `harness.provision_plan`. `mcp` imports it at module
level because `InterfaceHygieneTests` refuses a function-level policy import
inside an interface. Both rules now pass, and the remaining slices inherit the
same shape.
