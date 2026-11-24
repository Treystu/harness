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
import subprocess
import sys

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

_RUN_WATCH_PY = """\"\"\"Laptop-native bootstrapper for the Harness Laptop Driver Watch.\"\"\"
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import sys

WATCH_DIR = Path(__file__).resolve().parent
CONTROL_PATH = WATCH_DIR / "control.json"
STATUS_PATH = WATCH_DIR / "status.json"
LOCK_PATH = WATCH_DIR / "watch.lock"
LOG_PATH = Path.home() / ".harness" / "logs" / "driver-watch.log"


def run_tick(force=False):
    ctl = json.loads(CONTROL_PATH.read_text(encoding="utf-8-sig")) if CONTROL_PATH.is_file() else {"enabled": False}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not force and (not ctl.get("enabled") or ctl.get("paused")):
        state = "stopped" if not ctl.get("enabled") else "paused"
        STATUS_PATH.write_text(json.dumps({"state": state, "last_run": now, "exit_code": 0}), encoding="utf-8")
        return 0
    root = ctl.get("driver_root", "")
    if root not in sys.path:
        sys.path.insert(0, root)
    os.environ["HARNESS_DRIVER_CONTROL_FILE"] = str(CONTROL_PATH)
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        orig = subprocess.Popen
        class HiddenPopen(orig):
            def __init__(self, *args, **kwargs):
                kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
                super().__init__(*args, **kwargs)
        subprocess.Popen = HiddenPopen
    buf = io.StringIO()
    old = sys.stdout, sys.stderr
    rc = 0
    try:
        sys.stdout = sys.stderr = buf
        from scripts import windows_freebuff_watch
        rc = windows_freebuff_watch.main() or 0
    finally:
        sys.stdout, sys.stderr = old
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"[{now}] rc={rc}\\n{buf.getvalue()}")
    STATUS_PATH.write_text(json.dumps({"state": "idle_watching" if rc == 0 else "error", "last_run": now, "exit_code": rc}), encoding="utf-8")
    return rc


if __name__ == "__main__":
    raise SystemExit(run_tick("--force" in sys.argv))
"""

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
    return os.name == "nt"


def _run_ps(script: str) -> str:
    if not _scheduler_enabled():
        return ""
    kwargs = {"capture_output": True, "text": True, "timeout": 15, "check": False}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script],
        **kwargs,
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
        "head_sha": tick.get("head_sha") or "",
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
    _atomic_write_json(control_path(), ctl)
    return {
        "watch_dir": str(wdir),
        "runner": str(runner),
        "vbs": str(vbs),
        "ps1": str(ps1),
        "cmd": str(cmd),
        "control": str(control_path()),
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
