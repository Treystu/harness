"""Prove exact foreground round-trip using the saved Notepad proof window."""

import argparse
import hashlib
from pathlib import Path

from driver_core.actions import MUTATING, Action, Vocabulary
from driver_core.audit import AuditLog
from driver_core.config import Settings
from driver_core.driver import Driver
from driver_core.executor import Consent
from driver_core.observation import GUI, Target
from driver_core.osal import _WindowsWindowApi

from .windows_focus import activate_exact
from .windows_notepad_window import NotepadWindow, WindowsWindowScreen

TITLE = "vision-test.txt - Notepad"
FOCUS = Action("focus_exact", MUTATING, "focus_exact", ("hwnd", "pid"),
               "Activate this exact known window.", "gui")


class Bound:
    def __init__(self, native, hwnd):
        self.native = native
        self.hwnd = hwnd
        self.pid = native.pid(hwnd)

    def require_window(self):
        if not self.pid or self.native.pid(self.hwnd) != self.pid:
            raise RuntimeError("bound window identity changed")
        return self.hwnd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    args.evidence.mkdir()
    audit = AuditLog(args.evidence / "driver.jsonl")
    native = NotepadWindow()
    original = Bound(native, native.foreground())
    matches = _WindowsWindowApi().find_exact_visible(TITLE)
    if len(matches) != 1 or matches[0] == original.hwnd:
        audit.append("escalation", step_id="preflight", reason="saved test window unavailable or already foreground")
        return 1
    test = Bound(native, matches[0])
    windows = (original, test)
    native.user.IsIconic.argtypes = native.user.IsWindowVisible.argtypes
    minimized = bool(native.user.IsIconic(test.hwnd))
    driver = Driver(audit=audit, settings=Settings(allow_write=True),
                    vocabulary=Vocabulary("foreground-proof", "1.0.0", [FOCUS]))

    def focus(action, params):
        target = next((window for window in windows if window.hwnd == params["hwnd"]
                       and window.pid == params["pid"]), None)
        if target is None:
            raise RuntimeError("focus target is outside the two bound windows")
        hwnd = target.require_window()
        if target is test and minimized:
            native.user.ShowWindow(hwnd, 9)
        if not activate_exact(hwnd, native.foreground):
            raise RuntimeError("Windows refused exact foreground activation")

    driver.register_executor(FOCUS.name, focus)

    def act(step, target):
        params = {"hwnd": target.hwnd, "pid": target.pid}
        result = driver.executor.execute(
            FOCUS.name, params, consent=Consent(True, FOCUS.name, params, by="operator:T6"),
            step_id=step)
        if not result.ok:
            raise RuntimeError(result.detail)

    def capture(step, target):
        screen = WindowsWindowScreen(target, source="bound-foreground")
        frame = screen.capture(Target(step, GUI))
        (args.evidence / f"{step}.png").write_bytes(frame.payload)
        audit.append("capture", step_id=step, hwnd=target.hwnd, pid=target.pid,
                     sha256=hashlib.sha256(frame.payload).hexdigest())

    try:
        capture("before", original)
        try:
            act("activate-test", test)
            capture("test-window", test)
        finally:
            if native.foreground() == test.hwnd:
                act("restore-original", original)
            if minimized:
                native.user.ShowWindow(test.require_window(), 7)
        if native.foreground() != original.require_window():
            raise RuntimeError("prior foreground HWND did not return")
        capture("after", original)
        restored = native.foreground() == original.require_window()
        audit.append("verification", step_id="restore", passed=restored)
        print(f"Exact foreground restored: {restored}")
        return int(not restored)
    except (OSError, RuntimeError) as error:
        audit.append("escalation", step_id="foreground-proof", reason=str(error))
        print(f"BLOCKED: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
