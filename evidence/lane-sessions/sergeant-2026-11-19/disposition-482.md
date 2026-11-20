## Sergeant disposition on #482 (W3 launch_app packet) - code half ACCEPTED, issue stays OPEN on the live line

W3's closure packet (07:40:58Z, verified at `a7ca742`) is re-verified at current `main` `fb27ee895f43638cade271bcd9af33d2276b0136` by re-reading, not by trusting. Every claim below names file:symbol:line at that head.

### 1. Packet locations re-read at `fb27ee89` - all present, content matching

| step | location at `fb27ee89` | read |
|---|---|---|
| vocabulary | `driver_core/actions.py:179` | `Action("launch_app", MUTATING, "launch_app", ("app_name",), ...)` |
| executor | `driver_core/executor_registry.py:131` | `def _launch_app(action, params):` - resolves `app_name` through `APP_ALLOWLIST`, unlisted name refused |
| registration | `driver_core/executor_registry.py:162-171` | `"launch_app": _launch_app` inside `WRITE_EXECUTORS` |
| allowlist | `driver_core/config.py:118` | `APP_ALLOWLIST = {` - code-owned, environment cannot widen |
| resolution guard | `driver_core/osal.py:597` | `def _resolve_launch_executable(app_name, executable):` - absolute path must exist, bare name must resolve on PATH |
| opt-in (default off) | `driver_core/config.py:379` | `launch_app_enabled: bool = False` |
| opt-in (env mapping) | `driver_core/config.py:539` | `launch_app_enabled=_env_bool(env, "LAUNCH_APP", False)` |
| gate context | `driver_core/executor_registry.py:521-539` | read-only always; mutating only under `allow_write` |
| host wiring | `harness/queue_bus.py:542-557` | `payload.get("launch_app")` path with settings/driver/consent |
| vision hand-off | `driver_core/driver.py:455` | `launch_app` in the post-launch verify branch |
| threshold | `driver_core/vision_verify.py:46` | `APP_VISIBILITY_THRESHOLD = 0.85` |

### 2. Tree stability - the strongest fact in this disposition

`git diff --stat 699f677b fb27ee89 -- driver_core` is **empty**. The entire packet surface is byte-identical between the restart pin and current main, across six landings (#619, #620, #621, #623, #622, #631, #627, #624 - none touched driver_core). The `a7ca742` packet evidence carries forward without re-proof of content; what I re-proved is presence at the new head.

### 3. Executed at `fb27ee89` (read-only archive extraction, `-W error::ResourceWarning`)

- `test_launch_app` + `test_launch_app_resolution`: **22 tests, OK**.
- Full `tests/test_driver_core` battery: **884 tests, OK (3 skipped)**.

### 4. Disposition

- **Code/wiring half: ACCEPTED.** Vocabulary, executor, registration, allowlist, resolution guard, opt-in default and env mapping, host wiring, vision hand-off and threshold are all verified present with matching content at `fb27ee89`, and the executed battery is green.
- **Live line: NOT MET, parked with named unblockers.** No supervised cold-desktop FreeBuff launch and no #272 vision-verification pass have been filed on #452/#272 since the 07:40 disposition. The two owner-present acts stand unchanged: (1) FreeBuff resolvable (PATH or absolute-path allowlist change, reviewed code, real path only); (2) supervised launch with DRIVER_SCREEN + both opt-ins, result filed on #452 and #272.
- **#482 stays OPEN on the live line only.** No close keyword is used here and none is authorized by this disposition; closure remains the register's close test ("sergeant accepts packet or supervised run passes") applied to the live line when it is met.

**Gates, in order - recorded exactly as returned, not normalized.** Product Jev (keyed `jev-1.14.0`, caller `sergeant-482-disposition`, site `audit_admissibility`): verdict **escalate**, disposition proceed (supported 0.08, margin 0.2). Lucas Gate v2 (typed track, untracked receipt `gates-482.json`): pass. The escalate is published here rather than smoothed over: this disposition accepts another lane's packet on re-verified evidence, and the Jev's escalation is the marker that oversight should read the table above rather than the headline. Nothing in the escalation blocks the filing - disposition is proceed - but it is not an investigate and is not reported as one.
