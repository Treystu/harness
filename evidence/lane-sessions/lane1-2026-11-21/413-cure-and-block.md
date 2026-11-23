# #413 - loopback round-trip: reproduced at `280ee3d4`, two product cures pushed, acceptance blocked on the unkeyed decision tier

**Base:** `main` `280ee3d4f99bf3d33645ddde21b243cebe0b191b`
(`git fetch origin main:refs/remotes/origin/main` this turn;
`git ls-remote --heads origin refs/heads/main` agrees).
**Branch:** `lane/413-roundtrip-truth`, cut from that commit - not the diverged
`lane/burndown` (`86165805`), not `main`.
**Class:** verification (#413) with a product cure on the probed seam. No
measurement window was run and no credit is taken for #413's acceptance.

---

## 1. First correction: the 8791 service IS startable on this host

The mission checkpoint's item 5 carries "the loopback driver service (8791) is
not startable on this host per your re-check", and the earlier session probe
recorded `command -v driver-core -> driver-core NOT on PATH`. That is true of
the **console entry point** and false of the service: this checkout ships the
module entry, and it starts and answers.

```
$ DRIVER_TOKEN=lane1-probe-token DRIVER_DOM_URL=http://127.0.0.1:8797/ \
      python3 -m driver_core serve --host 127.0.0.1 --port 8791
health_code=200 pid=35865
```

The target it reads is a local static page on `127.0.0.1:8797`
(`python3 -m http.server 8797 --bind 127.0.0.1`, `static8797:200`). Both
listeners are loopback-only, and the service was killed at the end of the probe.

So the block on #413 is not the service. It is, exactly as the issue's recorded
diagnosis says, the **unkeyed decision tier**.

## 2. What the round trip actually does at `280ee3d4`

Taken through the product client (`harness.perception_client.PerceptionAdapter`,
token `lane1-probe-token`), against the service started above:

| Surface | Result |
| --- | --- |
| `health()` | `ok=True`, `keyed=False`, `sources=['dom']`, `key_provisioning.state=unkeyed`, variable `DRIVER_JEV_API_KEY` |
| `vocabulary()` | `ok=True` - payload keys `['ok', 'vocabulary']` (the closed action set, keyless, as the health text advertises) |
| `verify()` | `audit.ok=True`, `detail="chain verified"`, `records=4` |
| `schemas()` | `ok=True`, declared extraction schemas returned |
| `step(schema="dom", target=page)` | `ok=False`, **`stopped_at=decision`**, **`reason=decision_not_usable`**, `cost_usd=0.0`, detail `decision status 'unkeyed': no decision key configured` |
| `step(target=page)` (no schema) | `PerceptionUnavailable: driver service returned HTTP 400: schema is required; declare one of ['cli', 'dom', 'gui', 'mcp', 'screen']` |
| `health()` with a stale token | `PerceptionUnavailable: driver service returned HTTP 401: unauthorized` |

**Reproduced, unchanged:** capture clears with a `dom` source declared, the step
stops at the decision stage because no `DRIVER_JEV_API_KEY` is configured, and
the acting tier is therefore unmeasured. That is #413's recorded verdict
(PARTIAL) at the current head, not a new finding.

## 3. The two defects this seam still had, and the cure

Both are about the probe surface telling the truth, and both were measured on
this issue rather than guessed: the first filed a wrong row that had to be
withdrawn, the second is the reason a healthy service reads as a dead one.

### 3.1 `POST /api/driver/step` accepted an `action` field and never read it

`harness/server.py::_api_driver_step` requires `target`/`schema` and always
calls `adapter.step(...)`; an `action` key in the body was silently ignored and
the model-backed decision pipeline ran instead. That is what made the turn-13
probe read a step refusal as a vocabulary refusal and file
`driver-vocabulary-keyless-claim-false`, withdrawn in turn 14.

**Cure:** the route refuses the field by name, before any step runs:

```
400 field 'action' is not a step field: this route runs a step, it does not
    read the action vocabulary. Read the vocabulary at GET /api/driver/vocabulary,
    or pass a consent object to act.
```

### 3.2 A rejected token was reported as an outage

`harness/perception_client.py::_request` turned every HTTP error into
`PerceptionUnavailable("driver service returned HTTP {}: {}")`, and
`_api_driver_step` mapped that to **503**. With two harness processes up (an
undeclared `DRIVER_TOKEN` is generated per start, documented in
`docs/driver.md`), the second process reaches the first process's service and
every route answers `503 driver service returned HTTP 401: unauthorized` -
measured on #413 in turn 15 as an operational constraint, and indistinguishable
there from a service that is down.

**Cure:**

- `PerceptionUnauthorized(PerceptionUnavailable)` carries `.status` and names the
  cause: the presented token is not the one the running service was started
  with, and a declared `DRIVER_TOKEN` is how two processes share one. It stays a
  subclass, so every existing `except PerceptionUnavailable` keeps working.
- `_api_driver_step` maps it to **401** with `error_kind:
  "driver_token_mismatch"` instead of 503. An unreachable service still gets
  503, and a missing schema still gets 400 - the two existing behaviours are
  pinned by tests so the new branch cannot swallow them.

## 4. Verification at this head

```
$ uv run --no-project --with pytest --python 3.12 pytest tests/test_perception_413.py -q
........                                                                 [100%]
8 passed in 2.57s

$ uv run --no-project --with pytest --python 3.12 pytest \
      tests/test_perception_client.py tests/test_server_driver.py \
      tests/test_doctor.py tests/test_driver_conformance.py \
      tests/test_perception_413.py -q -p no:randomly
164 passed, 43 subtests passed in 39.36s

$ uv run --no-project --with ruff --python 3.12 ruff check \
      harness/perception_client.py harness/server.py tests/test_perception_413.py
All checks passed!
```

`tests/test_perception_413.py` pins all of it: a rejected token is
`PerceptionUnauthorized` with `status` 401 and a message naming `DRIVER_TOKEN`
(pinned with `isinstance` against the base class so existing callers cannot
regress), a refused connection and an HTTP 500 stay plain
`PerceptionUnavailable`, the `action` field is refused with the vocabulary route
named and `adapter.step` never called, a credential refusal is 401
`driver_token_mismatch`, and an outage is still 503 while a missing schema is
still 400.

**Full-suite chunk not run, deliberately:** neither touched file is reachable
from the rest of the tree except through the four neighbouring suites above
(`perception_client`, `server_driver`, `doctor`, `driver conformance`), all run
green here, and this change adds one exception subclass plus one early 400 to a
route already covered by that suite. The last full-suite state on this branch's
construction line was 6,678 passed with two failures already named as
environmental (`test_jev_chaos::test_roomy_budget`, a latency assertion under
concurrent load; `test_release_driver::test_interpreter_matrix_covers_ci_versions`,
missing interpreter versions on this host).

## 5. The #413 acceptance block, filed exactly

**Blocked on:** `DRIVER_JEV_API_KEY` in the serving process environment - the
decision tier refuses `decision_not_usable`, `stopped_at: decision`,
`cost_usd: 0.0`, detail `decision status 'unkeyed': no decision key configured`.
The acting tier additionally needs a registered input backend or
`DRIVER_ALLOW_WRITE=1`.

**Why this lane does not clear it:** a keyed decision is a paid provider call.
The mission forbids running the credit-billed #413 window this turn, and #415's
ceiling is the owner's spend item (filed `7012311968`). The key is operator
configuration, not code.

**What is proven without it:** the service starts and is loopback-only; the
keyless surfaces (health, vocabulary, verify, schemas) answer correctly through
the product client; the step pipeline reaches and reports the decision stage
honestly; and the two seam defects above are cured so the next keyed re-run
cannot misread either condition. The one remaining step -
`read_dom`/`click` through a keyed decision - stays NOT MET until the operator
sets `DRIVER_JEV_API_KEY`.

## 6. What this filing does not do

- No landing: the branch is pushed and unmerged, and no CircleCI read was made.
- No measurement window and no completion credit for #413 or #422.
- No register count change (see the STATUS filing for the census commands).
