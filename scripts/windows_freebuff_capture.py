"""Capture the existing FreeBuff window through the Harness vision source."""

import argparse
import csv
import ctypes
import hashlib
import time
from ctypes import wintypes
from pathlib import Path
from time import monotonic

from driver_core import osal
from driver_core.audit import AuditLog
from driver_core.errors import OsalError
from driver_core.observation import GUI, Target

from .windows_notepad_window import WindowsWindowScreen

TITLE = "Freebuff: The free coding agent"
OWNER_NAME = "Freebuff"
SETTLE_SECONDS = 8.0


class FreeBuffWindow:
    """One visible top-level FreeBuff window, owned by a FreeBuff.exe process.

    The application recycles its top-level handle (measured 2026-11-22: one
    PID owned four different handles within twelve minutes with no input), so
    a stored handle is not the identity. Ownership by the FreeBuff.exe process
    set plus one visible titled window is; the title is matched by its
    "Freebuff" prefix because the application, not this driver, owns the rest
    of that string. Every use re-resolves ownership, and a discovery that
    finds nothing settles before it refuses instead of failing on a single
    enumeration.
    """

    def __init__(self, *, settle=SETTLE_SECONDS):
        self.api = osal._WindowsWindowApi()
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.user.GetWindowThreadProcessId.argtypes = (
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
        self.user.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.handle, self.title = self.discover(settle=settle)
        self.process = self.pid(self.handle)

    def pid(self, hwnd):
        pid = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    @staticmethod
    def processes():
        result = osal.run(["tasklist.exe", "/FI", "IMAGENAME eq Freebuff.exe", "/FO", "CSV", "/NH"])
        if not result.ok:
            raise RuntimeError("could not enumerate FreeBuff processes")
        return {int(row[1]) for row in csv.reader(result.stdout.splitlines())
                if len(row) > 1 and row[0].casefold() == "freebuff.exe"}

    def candidates(self, pids=None):
        """Visible titled top-level windows owned by the FreeBuff processes."""
        pids = self.processes() if pids is None else pids
        matches = []
        for hwnd in self._visible():
            if self.pid(hwnd) in pids:
                try:
                    title = self.api.title_of(hwnd)
                except OsalError:
                    # The application recycles its top-level handles, so a
                    # window can close between the visibility check and the
                    # title read (measured: Win32 1400 mid-enumeration). A
                    # vanished handle is not a FreeBuff window; the settle
                    # loop re-enumerates.
                    continue
                if title and title.startswith(OWNER_NAME):
                    matches.append((hwnd, title))
        return matches

    def _visible(self):
        self.user.EnumWindows.argtypes = (ctypes.c_void_p, wintypes.LPARAM)
        self.user.EnumWindows.restype = wintypes.BOOL
        handles = []

        def visit(hwnd, _param):
            if self.api._user32.IsWindowVisible(hwnd):
                handles.append(int(hwnd))
            return True

        self.user.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(visit), 0)
        return handles

    def discover(self, *, settle=SETTLE_SECONDS):
        deadline = monotonic() + settle
        last = []
        while True:
            last = self.candidates()
            if len(last) == 1:
                return last[0]
            time.sleep(0.35)
            if monotonic() >= deadline:
                break
        census = ", ".join(f"{hwnd}:{title!r}" for hwnd, title in last) or "none"
        raise RuntimeError(
            f"expected exactly one visible FreeBuff application, found {len(last)}; "
            f"visible owned windows: {census}")

    def require_window(self):
        """Re-resolve the window and refuse if ownership or visibility changed."""
        if (not self.api._user32.IsWindow(self.handle)
                or self.pid(self.handle) != self.process):
            self.handle, self.title = self.discover()
            self.process = self.pid(self.handle)
        elif not self.api._user32.IsWindowVisible(self.handle):
            self.handle, self.title = self.discover()
            self.process = self.pid(self.handle)
        return self.handle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    args.evidence.mkdir()
    audit = AuditLog(args.evidence / "driver.jsonl")
    try:
        window = FreeBuffWindow()
        foreground = window.api.foreground() == window.handle
        screen = WindowsWindowScreen(window, source="windows-freebuff")
        started = monotonic()
        capture = screen.capture(Target("existing FreeBuff desktop", GUI))
        elapsed = monotonic() - started
        if elapsed > 2:
            raise RuntimeError(f"FreeBuff capture exceeded the 2s budget ({elapsed:.3f}s)")
        (args.evidence / "freebuff.png").write_bytes(capture.payload)
        audit.append("capture", step_id="freebuff-window", **capture.summary(),
                     hwnd=window.handle, pid=window.process, title=window.title,
                     foreground=foreground, capture_seconds=round(elapsed, 3),
                     sha256=hashlib.sha256(capture.payload).hexdigest())
    except (OSError, RuntimeError) as error:
        audit.append("escalation", step_id="freebuff-window", reason=str(error))
        print(f"Capture failed: {error}")
        return 1
    receipt = audit.verify()
    print(f"FreeBuff capture: {elapsed:.3f}s; foreground={foreground}; title={window.title!r}; "
          f"trace={receipt.head}")
    return 0 if receipt.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
