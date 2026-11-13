## Live state: cured on `lane/burndown` in `a241176`

`driver_core/executor_registry.py` registers `run_probe` in `build_read_only_registry`, next to `no_action` / `read_value` / `observe`, with the comment recording the contradiction this issue names:

```python
"run_probe": _run_probe,
```

`_run_probe` runs an argv list through `osal.run` (no shell, no composition), enforces `PROBE_TIMEOUT`, and returns `argv` / `exit_code` / `stdout` / `stderr` (plus `timed_out`) as the action's output -- which the executor records in the audit chain like any other action.

## Acceptance check

- **Probe runs with `allow_write=false`, constrained to declared shapes:** `ReadOnlyProbeTests.setUp` builds the registry with `allow_write=False`; `test_a_probe_runs_and_its_output_lands_in_the_audit_chain` executes and asserts `ok`.
- **Results land in the audit chain:** same test asserts the audit record carries `action == "run_probe"`, `ok`, `output.stdout`, `output.exit_code`, and that `audit.verify().ok`.
- **Write-class actions stay refused:** the suite keeps the write gate asserted (mutating actions still refuse without authority).
- **Regression tests for allowed probe and refused non-allowlisted shape:** `test_a_non_allowlisted_shape_is_refused_before_a_process_starts` (failure text `not allowlisted`, refusal still recorded) and `test_operator_declared_shapes_reject_appended_arguments`.

`python -m pytest tests/test_issue439_read_only_probe.py -q` -> **12 passed** on the current lane head `cbbfc31`.

## Disposition

Met on the lane, kept open for the main landing. `main` does not carry `a241176`; base `5eb9c36` is red (run 41576644039), so landing is the owner-reserved act already recorded on #442.
