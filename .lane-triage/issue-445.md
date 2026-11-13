## Inventory (reproduced on `lane/burndown` at `6a4988d`, pyright 1.1.414, `--pythonversion 3.9`)

21 errors, not 40: `harness/cli.py` is clean on the current tree, so the 19 recorded there are gone (or were counted from a different root set). Per file as measured: `config.py` 9 (583, 1129, 1147, 1148, 1164, 1175 x2, 1177 x2), `service.py` 5 (410, 437, 441, 444, 477), `spend.py` 5 (227 x2, 411, 909), `chat.py` 2 (701, 702), `fireworks.py` 1 (90). Recording the drift rather than restating the old count.

## Cure (`1b3869b`) - typing-only, one intent per file

- **`errors.py`**: `HarnessError` declares `known_cost` and `cost_accounted`. `chat.py` was already assigning both after booking a post-dispatch charge - a real contract, written in the dark. The default (`0.0` / `False`) is the same value every defensive `getattr` reader already substituted, so runtime reads are unchanged.
- **`config.py`**: `osal.keyfile_mode()` may answer `None` where modes are not modelled (Windows ACLs), and the warning called `oct(None)`; it now prints `unknown` and the warning itself is unchanged. `max_price_prompt` / `max_price_completion` read their key once through `_opt_float`, so the None guard and the conversion see the same value. `token_budget_input`, `token_budget_output` and `mcp_tool_timeout` are converted with `int(...)` at the `Settings` call - which is exactly what `_num(..., int, ...)` already returned; the annotation just could not prove it through the `cast is int` branch. `fireworks_key` is passed as `fireworks_key or ""`, matching what `Settings.__init__` already does with it.
- **`service.py`**: `report` is annotated `dict`; the literal `{"phases": []}` had let a checker infer `dict[str, list]`, so every `report["status"] = "..."` read as a list write.
- **`spend.py`**: `key_info`, `fetch_models()` and the discovery rows are Optional; the key-status copy and both loops now say `or {}` / `or []` instead of assuming, which is the same empty-iteration outcome they already relied on.
- **`fireworks.py`**: an `endpoints` dict without `offers` is an empty comparison (`or []`), not an iteration over None.

## Evidence

- `pyright --pythonversion 3.9` over the six files plus `errors.py`: **0 errors, 0 warnings**.
- `ruff check harness tests`: clean.
- Full suite on `1b3869b`: `Ran 5355 tests ... OK (skipped=65)`, 415.0 s - one test more than the previous run (the new advisory pin from #446), no failures.
- CI on `1b3869b` (run 41633661986): **17/17 check-runs success**, `changed-file typecheck (pyright)` among them.

## Disposition

Cured on the lane; **not closed**, for the same reason as #446: the debt the issue tracks is on `main`, and main stays red until this lands (base `5eb9c36` failed its own run 41576644039; recorded on #442). Not taken here: a repo-wide pyright job or baseline subtraction - the issue names that as a separate CI-policy change with its own gate, and a changed-files leg cannot prove a repo-wide baseline either way.
