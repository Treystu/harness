"""Laptop-resident operator control and state for the Harness Laptop Driver Watch.

Manages the local control file (`~/.harness/driver-watch/control.json`), reads
tick status (`status.json`) and log tail (`~/.harness/logs/driver-watch.log`),
syncs the Windows hidden Scheduled Task (`HarnessLaptopDriverWatch`), and
materializes the standalone laptop wrapper scripts so zero operator control
machinery is local-only.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from . import osal
from .errors import HarnessError

WATCH_TASK_NAME = "HarnessLaptopDriverWatch"
LEGACY_POPUP_TASK_NAME = "HarnessVisionWatch-7093801996"
VALID_ACTIONS = ("status", "start", "stop", "pause", "resume", "run-once")
DEFAULT_DRIVER_ROOT = r"C:\Users\SCM\Documents\GitHub\Harness-laptop-vision-20261122"
DEFAULT_PYTHONW = r"C:\Python314\pythonw.exe"
DEFAULT_PYTHON = r"C:\Python314\python.exe"

_WATCH_HIDDEN_VBS = """' Launch the Harness Laptop Driver Watch silently with no console window.
' Scheduled as: wscript.exe //B //Nologo "{watch_dir}\\watch-hidden.vbs"
Set sh = CreateObject("WScript.Shell")
sh.Run "\"\"\"{pythonw}\"\" \"\"{watch_dir}\\run-watch.py\"\"\"", 0, False
"""

_DRIVER_CTL_CMD = """@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{harness_dir}\\driver-ctl.ps1" %*
exit /b %ERRORLEVEL%
"""

_RUN_WATCH_PY = '''"""Laptop-native bootstrapper for the Harness Laptop Driver Watch.

Runs outside any agent work session directly from ~/.harness/driver-watch/.
Enforces single-instance locking, honors local operator start/stop/pause state
in control.json, suppresses child console popups on Windows, logs cleanly with
1 MB rotation to ~/.harness/logs/driver-watch.log, and records atomic telemetry
(plus rate-limited failure alerts on #684) in status.json.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

WATCH_DIR = Path(os.environ.get("HARNESS_DRIVER_WATCH_DIR", "").strip() or (Path.home() / ".harness" / "driver-watch"))
CONTROL_PATH = WATCH_DIR / "control.json"
STATUS_PATH = WATCH_DIR / "status.json"
LOCK_PATH = WATCH_DIR / "watch.lock"
_RAW_LOG = os.environ.get("HARNESS_DRIVER_LOG_PATH", "").strip()
LOG_PATH = Path(_RAW_LOG) if _RAW_LOG else (Path.home() / ".harness" / "logs" / "driver-watch.log")
LOG_DIR = LOG_PATH.parent
MAX_LOG_BYTES = 1_048_576
DEFAULT_DRIVER_ROOT = r"C:\\Users\\SCM\\Documents\\GitHub\\Harness-laptop-vision-20261122"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=2) + "\\n", encoding="utf-8")
    tmp.replace(path)


def _read_status() -> dict:
    if not STATUS_PATH.is_file():
        return {}
    try:
        data = json.loads(STATUS_PATH.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _append_log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if LOG_PATH.exists() and LOG_PATH.stat().st_size > MAX_LOG_BYTES:
        backup = LOG_PATH.with_suffix(".log.1")
        if backup.exists():
            backup.unlink()
        LOG_PATH.replace(backup)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(message)
        if not message.endswith("\\n"):
            handle.write("\\n")


def _read_control() -> dict:
    if not CONTROL_PATH.is_file():
        return {
            "enabled": False,
            "paused": False,
            "driver_root": DEFAULT_DRIVER_ROOT,
        }
    return json.loads(CONTROL_PATH.read_text(encoding="utf-8-sig"))


def _acquire_lock():
    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    handle = LOCK_PATH.open("a+", encoding="utf-8")
    if os.name == "nt":
        import msvcrt

        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            handle.close()
            return None
    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()} {_utc_now()}\\n")
    handle.flush()
    return handle


def _release_lock(handle) -> None:
    if handle is None:
        return
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    finally:
        handle.close()


def _install_hidden_subprocess_default() -> None:
    """Ensure child processes spawned under pythonw never flash a console window."""
    if os.name != "nt":
        return
    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    orig_popen = subprocess.Popen
    if getattr(orig_popen, "_harness_hidden", False):
        return

    class HiddenPopen(orig_popen):
        _harness_hidden = True

        def __init__(self, *args, **kwargs):
            kwargs.setdefault("creationflags", create_no_window)
            super().__init__(*args, **kwargs)

    subprocess.Popen = HiddenPopen


def _git_head(driver_root: str) -> str:
    kwargs = {"capture_output": True, "text": True, "timeout": 5, "check": False}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=driver_root, **kwargs)
    except (OSError, subprocess.SubprocessError):
        return ""
    return res.stdout.strip() if res.returncode == 0 else ""


def _runtime_home_module(driver_root: str):
    """The G4 producer from the driver checkout, or ``None`` when absent.

    The producer lives on the driver branch, so a checkout that predates it
    must keep working: the tick then runs from the driver root exactly as it
    did before and the status names why the pinned home was not built.
    """
    path = Path(driver_root) / "scripts" / "driver_runtime_home.py"
    if not path.is_file():
        return None
    import importlib.util

    spec = importlib.util.spec_from_file_location("harness_driver_runtime_home", str(path))
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return None
    return module


def pinned_runtime_root(driver_root: str) -> tuple[str, str, str, str]:
    """``(root, state, detail, sha)`` for the tree this tick executes (G4).

    The watch runs the code pinned at the driver checkout's HEAD, copied out of
    the dev tree, so an uncommitted edit there is never its input - the twelve
    refusals of 2026-11-27 were exactly that input. A home that already carries
    a verified pin at this HEAD is reused instead of rebuilt.
    """
    raw_home = os.environ.get("HARNESS_DRIVER_RUNTIME_HOME", "").strip()
    home_root = Path(raw_home) if raw_home else (WATCH_DIR / "runtime")
    sha = _git_head(driver_root)
    if not sha:
        return driver_root, "unavailable", "driver_root has no readable HEAD", ""
    module = _runtime_home_module(driver_root)
    if module is None:
        return (driver_root, "unavailable",
                "driver checkout carries no scripts/driver_runtime_home.py", sha)
    # G13: the standing-prompt registry is pinned INTO the home, so the claim
    # path reads a lane's continuation from these bytes and a registration
    # change takes effect without a new driver commit.
    raw_registry = os.environ.get("HARNESS_DRIVER_REGISTRY_DIR", "").strip()
    registry = (Path(raw_registry) if raw_registry
                else Path(driver_root) / "dispatch" / "laptop-driver" / "standing-prompts")
    registry_arg = registry if registry.is_dir() else None
    home = home_root / sha[:12]
    try:
        pin = module.read_pin(home)
        if pin and module.verify(home, pin)[0]:
            if registry_arg is not None:
                pin = module.refresh_registry(home, registry_arg)
            return str(home), "pinned", "", str(pin.get("sha") or sha)
        pin = module.install(Path(driver_root), home, sha=sha, registry=registry_arg)
    except Exception as exc:
        return driver_root, "unavailable", f"{type(exc).__name__}: {exc}", sha
    return str(home), "pinned", "", str(pin.get("sha") or sha)


def _emit_failure_alert(control: dict, exit_code: int, error_text: str, failures: int) -> bool:
    if os.environ.get("HARNESS_DRIVER_WATCH_NO_ALERT", "").strip():
        return False
    if not control.get("alert_on_failure", True):
        return False
    repo = str(control.get("repo") or "Treystu/harness")
    issue = str(control.get("dispatch_issue") or 684)
    msg = (
        f"Vision watch service failure alert (self-heal monitor): "
        f"exit_code={exit_code}, consecutive_failures={failures}, "
        f"error={error_text[:240] or 'nonzero watch exit'}."
    )
    kwargs = {"capture_output": True, "text": True, "timeout": 15, "check": False}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        res = subprocess.run(
            ["gh", "issue", "comment", issue, "--repo", repo, "--body", msg],
            **kwargs,
        )
        return res.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def run_tick(*, force: bool = False, echo: bool = False) -> int:
    lock = _acquire_lock()
    if lock is None:
        msg = f"[{_utc_now()}] skipped: another watch tick already holds {LOCK_PATH}"
        _append_log(msg)
        if echo:
            print(msg)
        return 0
    prior = _read_status()
    prev_cwd = os.getcwd()
    try:
        try:
            control = _read_control()
            enabled = bool(control.get("enabled", False))
            paused = bool(control.get("paused", False))
            driver_root = str(control.get("driver_root") or DEFAULT_DRIVER_ROOT)
            now = _utc_now()

            if not force and not enabled:
                _atomic_write_json(STATUS_PATH, {
                    "state": "stopped",
                    "enabled": False,
                    "paused": paused,
                    "driver_root": driver_root,
                    "head_sha": _git_head(driver_root) if Path(driver_root).is_dir() else "",
                    "pid": os.getpid(),
                    "last_run": now,
                    "exit_code": 0,
                    "last_error": "",
                    "consecutive_failures": 0,
                    "alerted_failure": False,
                })
                return 0

            if not force and paused:
                _atomic_write_json(STATUS_PATH, {
                    "state": "paused",
                    "enabled": True,
                    "paused": True,
                    "driver_root": driver_root,
                    "head_sha": _git_head(driver_root) if Path(driver_root).is_dir() else "",
                    "pid": os.getpid(),
                    "last_run": now,
                    "exit_code": 0,
                    "last_error": "",
                    "consecutive_failures": 0,
                    "alerted_failure": False,
                })
                return 0

            if not Path(driver_root).is_dir():
                err = f"driver_root not found: {driver_root}"
                failures = int(prior.get("consecutive_failures") or 0) + 1
                _append_log(f"[{now}] ERROR {err}")
                alerted = bool(prior.get("alerted_failure")) or _emit_failure_alert(control, 2, err, failures)
                _atomic_write_json(STATUS_PATH, {
                    "state": "error",
                    "enabled": enabled,
                    "paused": paused,
                    "driver_root": driver_root,
                    "head_sha": "",
                    "pid": os.getpid(),
                    "last_run": now,
                    "exit_code": 2,
                    "last_error": err,
                    "consecutive_failures": failures,
                    "alerted_failure": alerted,
                })
                if echo:
                    print(err, file=sys.stderr)
                return 2

            _install_hidden_subprocess_default()
            os.environ["HARNESS_DRIVER_CONTROL_FILE"] = str(CONTROL_PATH)
            execute_root, runtime_state, runtime_detail, head_sha = pinned_runtime_root(driver_root)
            os.environ["HARNESS_DRIVER_RUNTIME_ROOT"] = execute_root
            for entry in (driver_root, execute_root):
                if entry not in sys.path:
                    sys.path.insert(0, entry)
            os.chdir(execute_root)

            _atomic_write_json(STATUS_PATH, {
                "state": "running_tick",
                "enabled": enabled,
                "paused": paused,
                "driver_root": driver_root,
                "head_sha": head_sha,
                "runtime_home": execute_root,
                "runtime_state": runtime_state,
                "runtime_detail": runtime_detail,
                "pid": os.getpid(),
                "last_run": now,
                "exit_code": None,
                "last_error": "",
                "consecutive_failures": int(prior.get("consecutive_failures") or 0),
                "alerted_failure": bool(prior.get("alerted_failure")),
            })

            buf = io.StringIO()
            old_out, old_err = sys.stdout, sys.stderr
            exit_code = 0
            last_error = ""
            try:
                sys.stdout = buf
                sys.stderr = buf
                from scripts import windows_freebuff_watch
                result = windows_freebuff_watch.main()
                if isinstance(result, int):
                    exit_code = result
            except SystemExit as exc:
                code = exc.code
                exit_code = code if isinstance(code, int) else (0 if code is None else 1)
            except Exception as exc:
                exit_code = 1
                last_error = f"{type(exc).__name__}: {exc}"
                traceback.print_exc(file=buf)
            finally:
                sys.stdout = old_out
                sys.stderr = old_err

            captured = buf.getvalue().strip()
            finished = _utc_now()
            if captured:
                _append_log(f"[{finished}] sha={head_sha[:8]} rc={exit_code}\\n{captured}")
                if echo:
                    print(captured)
            elif exit_code != 0 or last_error:
                _append_log(f"[{finished}] sha={head_sha[:8]} rc={exit_code} err={last_error}")
            else:
                _append_log(f"[{finished}] tick ok sha={head_sha[:8]} state={'forced' if force else 'active'}")

            failures = int(prior.get("consecutive_failures") or 0) + 1 if exit_code != 0 else 0
            alerted = bool(prior.get("alerted_failure"))
            if exit_code != 0 and not alerted:
                alerted = _emit_failure_alert(control, exit_code, last_error, failures)
            elif exit_code == 0:
                alerted = False

            final_state = "error" if exit_code != 0 else ("paused" if paused else ("stopped" if not enabled else "idle_watching"))
            _atomic_write_json(STATUS_PATH, {
                "state": final_state,
                "enabled": enabled,
                "paused": paused,
                "driver_root": driver_root,
                "head_sha": head_sha,
                "runtime_home": execute_root,
                "runtime_state": runtime_state,
                "runtime_detail": runtime_detail,
                "pid": os.getpid(),
                "last_run": finished,
                "exit_code": exit_code,
                "last_error": last_error,
                "consecutive_failures": failures,
                "alerted_failure": alerted,
            })
            return exit_code
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            failures = int(prior.get("consecutive_failures") or 0) + 1
            _append_log(f"[{_utc_now()}] OUTER ERROR {err}\\n{traceback.format_exc()}")
            try:
                _atomic_write_json(STATUS_PATH, {
                    "state": "error",
                    "enabled": False,
                    "paused": False,
                    "driver_root": DEFAULT_DRIVER_ROOT,
                    "head_sha": "",
                    "pid": os.getpid(),
                    "last_run": _utc_now(),
                    "exit_code": 1,
                    "last_error": err,
                    "consecutive_failures": failures,
                    "alerted_failure": bool(prior.get("alerted_failure")),
                })
            except Exception:
                pass
            if echo:
                print(err, file=sys.stderr)
            return 1
    finally:
        try:
            os.chdir(prev_cwd)
        except OSError:
            pass
        _release_lock(lock)


def main() -> int:
    parser = argparse.ArgumentParser(description="Harness Laptop Driver Watch runner")
    parser.add_argument("--force", action="store_true", help="Run one tick even if paused/stopped")
    parser.add_argument("--echo", action="store_true", help="Echo tick output to stdout")
    args = parser.parse_args()
    return run_tick(force=args.force, echo=args.echo)


if __name__ == "__main__":
    raise SystemExit(main())
'''

_DRIVER_CTL_PS1 = """param([Parameter(Position=0)][string]$Command = 'status', [Parameter(Position=1)][string]$Arg1 = '')
$argsList = @('-m', 'harness.cli', 'driver-watch', $Command)
if ($Arg1) { $argsList += @('--driver-root', $Arg1) }
& "__PYTHON__" @argsList
exit $LASTEXITCODE
"""


def watch_dir() -> Path:
    override = os.environ.get("HARNESS_DRIVER_WATCH_DIR", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".harness" / "driver-watch"


def control_path() -> Path:
    return watch_dir() / "control.json"


def status_path() -> Path:
    return watch_dir() / "status.json"


def log_path() -> Path:
    override = os.environ.get("HARNESS_DRIVER_LOG_PATH", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".harness" / "logs" / "driver-watch.log"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path, default: dict) -> dict:
    if not path.is_file():
        return dict(default)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8-sig"))
        return loaded if isinstance(loaded, dict) else dict(default)
    except (OSError, ValueError):
        return dict(default)


def _scheduler_enabled() -> bool:
    if os.environ.get("HARNESS_DRIVER_WATCH_NO_SCHEDULER", "").strip():
        return False
    return osal.IS_WINDOWS


def _run_ps(script: str) -> str:
    if not _scheduler_enabled():
        return ""
    proc = osal.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script],
        timeout=15,
    )
    if proc.returncode != 0:
        raise HarnessError(f"scheduled task command failed: {(proc.stderr or proc.stdout).strip()[:200]}")
    return proc.stdout.strip()


def _task_state(name: str) -> str:
    if not _scheduler_enabled():
        return "not-windows-or-disabled"
    out = _run_ps(
        f"$t = Get-ScheduledTask -TaskName '{name}' -ErrorAction SilentlyContinue; "
        "if ($t) { $t.State } else { 'missing' }"
    )
    return out or "missing"


def _register_watch_task(vbs_path: Path) -> bool:
    if not _scheduler_enabled():
        return False
    vbs_arg = f'//B //Nologo "{vbs_path}"'
    ps_vbs = str(vbs_path).replace("'", "''")
    script = (
        f"$action = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument '//B //Nologo \"{ps_vbs}\"'; "
        f"$tLogon = New-ScheduledTaskTrigger -AtLogOn; "
        f"$tRepeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) "
        f"-RepetitionInterval (New-TimeSpan -Minutes 2) -RepetitionDuration (New-TimeSpan -Days 3650); "
        f"$settings = New-ScheduledTaskSettingsSet -Hidden -AllowStartIfOnBatteries "
        f"-DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -StartWhenAvailable "
        f"-ExecutionTimeLimit (New-TimeSpan -Minutes 5); "
        f"Register-ScheduledTask -TaskName '{WATCH_TASK_NAME}' -Action $action "
        f"-Trigger @($tLogon, $tRepeat) -Settings $settings "
        f"-Description 'Harness laptop driver watch (hidden, logon + 2-minute ticks)' -Force | Out-Null; "
        f"if (Get-ScheduledTask -TaskName '{LEGACY_POPUP_TASK_NAME}' -ErrorAction SilentlyContinue) "
        f"{{ Disable-ScheduledTask -TaskName '{LEGACY_POPUP_TASK_NAME}' | Out-Null }}"
    )
    _run_ps(script)
    _ = vbs_arg
    return True


def _set_task_state(action: str) -> None:
    if not _scheduler_enabled():
        return
    if action in ("start", "resume"):
        _run_ps(
            f"if (Get-ScheduledTask -TaskName '{LEGACY_POPUP_TASK_NAME}' -ErrorAction SilentlyContinue) "
            f"{{ Disable-ScheduledTask -TaskName '{LEGACY_POPUP_TASK_NAME}' | Out-Null }}; "
            f"if (Get-ScheduledTask -TaskName '{WATCH_TASK_NAME}' -ErrorAction SilentlyContinue) "
            f"{{ Enable-ScheduledTask -TaskName '{WATCH_TASK_NAME}' | Out-Null; "
            f"Start-ScheduledTask -TaskName '{WATCH_TASK_NAME}' }}"
        )
    elif action == "stop":
        _run_ps(
            f"if (Get-ScheduledTask -TaskName '{WATCH_TASK_NAME}' -ErrorAction SilentlyContinue) "
            f"{{ Disable-ScheduledTask -TaskName '{WATCH_TASK_NAME}' | Out-Null }}"
        )
    elif action == "run-once":
        _run_ps(
            f"if (Get-ScheduledTask -TaskName '{WATCH_TASK_NAME}' -ErrorAction SilentlyContinue) "
            f"{{ Start-ScheduledTask -TaskName '{WATCH_TASK_NAME}' }}"
        )


def _log_tail(max_lines: int = 8) -> list[str]:
    path = log_path()
    if not path.is_file():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()[-max_lines:]


def driver_watch_status() -> dict:
    """Return the combined local control, last tick, task, and log-tail state."""
    default_ctl = {
        "enabled": False,
        "paused": False,
        "python": DEFAULT_PYTHONW,
        "driver_root": DEFAULT_DRIVER_ROOT,
        "repo": "Treystu/harness",
        "dispatch_issue": 684,
        "interval_minutes": 2,
    }
    ctl = _read_json(control_path(), default_ctl)
    tick = _read_json(status_path(), {})
    enabled = bool(ctl.get("enabled", False))
    paused = bool(ctl.get("paused", False))
    effective = "stopped" if not enabled else ("paused" if paused else (tick.get("state") or "running"))
    return {
        "state": effective,
        "enabled": enabled,
        "paused": paused,
        "driver_root": ctl.get("driver_root", DEFAULT_DRIVER_ROOT),
        "task_name": WATCH_TASK_NAME,
        "task_state": _task_state(WATCH_TASK_NAME),
        "legacy_popup_task": LEGACY_POPUP_TASK_NAME,
        "legacy_popup_state": _task_state(LEGACY_POPUP_TASK_NAME),
        "last_run": tick.get("last_run"),
        "exit_code": tick.get("exit_code"),
        "pid": tick.get("pid"),
        "consecutive_failures": int(tick.get("consecutive_failures") or 0),
        "head_sha": tick.get("head_sha") or "",
        "runtime_home": tick.get("runtime_home") or "",
        "runtime_state": tick.get("runtime_state") or "unknown",
        "runtime_detail": tick.get("runtime_detail") or "",
        "last_error": tick.get("last_error") or "",
        "control_file": str(control_path()),
        "log_tail": _log_tail(),
    }


def driver_watch_control(action: str, *, driver_root: str | None = None, by: str = "harness-ctl") -> dict:
    """Apply one declared watch control action and return the updated status."""
    verb = str(action or "").strip().lower()
    if verb not in VALID_ACTIONS:
        raise HarnessError(f"unsupported driver-watch action {action!r}; choose from {list(VALID_ACTIONS)}")
    if verb == "status":
        return driver_watch_status()
    ctl = _read_json(control_path(), {
        "enabled": False,
        "paused": False,
        "python": DEFAULT_PYTHONW,
        "driver_root": driver_root or DEFAULT_DRIVER_ROOT,
        "repo": "Treystu/harness",
        "dispatch_issue": 684,
        "interval_minutes": 2,
    })
    if driver_root:
        ctl["driver_root"] = driver_root
    if verb in ("start", "resume"):
        ctl["enabled"] = True
        ctl["paused"] = False
    elif verb == "pause":
        ctl["paused"] = True
    elif verb == "stop":
        ctl["enabled"] = False
        ctl["paused"] = False
    ctl["updated_at"] = _utc_now()
    ctl["updated_by"] = by
    _atomic_write_json(control_path(), ctl)
    _set_task_state(verb)
    return driver_watch_status()


def install_laptop_watch(
    *, driver_root: str | None = None, pythonw: str = DEFAULT_PYTHONW, python_exe: str = DEFAULT_PYTHON,
) -> dict:
    """Materialize the standalone hidden watch wrapper templates in the watch directory."""
    wdir = watch_dir()
    hdir = wdir.parent
    wdir.mkdir(parents=True, exist_ok=True)
    runner = wdir / "run-watch.py"
    runner.write_text(_RUN_WATCH_PY, encoding="utf-8")
    vbs = wdir / "watch-hidden.vbs"
    vbs.write_text(_WATCH_HIDDEN_VBS.format(watch_dir=wdir, pythonw=pythonw), encoding="utf-8")
    ps1 = hdir / "driver-ctl.ps1"
    ps1.write_text(_DRIVER_CTL_PS1.replace("__PYTHON__", python_exe), encoding="utf-8")
    cmd = hdir / "driver-ctl.cmd"
    cmd.write_text(_DRIVER_CTL_CMD.format(harness_dir=hdir), encoding="utf-8")
    ctl = _read_json(control_path(), {
        "enabled": True,
        "paused": False,
        "python": pythonw,
        "driver_root": driver_root or DEFAULT_DRIVER_ROOT,
        "repo": "Treystu/harness",
        "dispatch_issue": 684,
        "interval_minutes": 2,
        "updated_at": _utc_now(),
        "updated_by": "install",
    })
    if driver_root:
        ctl["driver_root"] = driver_root
        ctl["updated_at"] = _utc_now()
        ctl["updated_by"] = "install"
    _atomic_write_json(control_path(), ctl)
    task_registered = _register_watch_task(vbs)
    return {
        "watch_dir": str(wdir),
        "runner": str(runner),
        "vbs": str(vbs),
        "ps1": str(ps1),
        "cmd": str(cmd),
        "control": str(control_path()),
        "task_registered": task_registered,
        "task_state": _task_state(WATCH_TASK_NAME),
    }


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harness driver-watch", description=__doc__)
    parser.add_argument("action", choices=(*VALID_ACTIONS, "install"), default="status", nargs="?")
    parser.add_argument("--driver-root", default=None, help="Checkout path carrying scripts/windows_freebuff_watch.py")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    opts = parser.parse_args(argv)
    if opts.action == "install":
        result = install_laptop_watch(driver_root=opts.driver_root)
    else:
        result = driver_watch_control(opts.action, driver_root=opts.driver_root, by="cli")
    if opts.json:
        print(json.dumps(result, indent=2))
    else:
        print(
            f"driver-watch state={result.get('state', 'installed')} "
            f"task={result.get('task_state', 'n/a')} "
            f"legacy_popup={result.get('legacy_popup_state', 'n/a')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli(sys.argv[1:]))
