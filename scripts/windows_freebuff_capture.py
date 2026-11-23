"""Capture the existing FreeBuff window through the Harness vision source."""

import argparse
import csv
import ctypes
import hashlib
from ctypes import wintypes
from pathlib import Path
from time import monotonic

from driver_core import osal
from driver_core.audit import AuditLog
from driver_core.observation import GUI, Target

from .windows_notepad_window import WindowsWindowScreen

TITLE = "Freebuff: The free coding agent"


class FreeBuffWindow:
    def __init__(self):
        self.api = osal._WindowsWindowApi()
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.user.GetWindowThreadProcessId.argtypes = (
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
        self.user.GetWindowThreadProcessId.restype = wintypes.DWORD
        processes = osal.run(["tasklist.exe", "/FI", "IMAGENAME eq Freebuff.exe", "/FO", "CSV", "/NH"])
        if not processes.ok:
            raise RuntimeError("could not enumerate FreeBuff processes")
        pids = {int(row[1]) for row in csv.reader(processes.stdout.splitlines())
                if len(row) > 1 and row[0].casefold() == "freebuff.exe"}
        matches = [hwnd for hwnd in self.api.find_exact_visible(TITLE) if self.pid(hwnd) in pids]
        if len(matches) != 1:
            raise RuntimeError(f"expected exactly one visible FreeBuff application, found {len(matches)}")
        self.handle = matches[0]
        self.process = self.pid(self.handle)

    def pid(self, hwnd):
        pid = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    def require_window(self):
        if self.pid(self.handle) != self.process or self.api.title_of(self.handle) != TITLE:
            raise RuntimeError("the bound FreeBuff window changed")
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
                     foreground=foreground, capture_seconds=round(elapsed, 3),
                     sha256=hashlib.sha256(capture.payload).hexdigest())
    except (OSError, RuntimeError) as error:
        audit.append("escalation", step_id="freebuff-window", reason=str(error))
        print(f"Capture failed: {error}")
        return 1
    receipt = audit.verify()
    print(f"FreeBuff capture: {elapsed:.3f}s; foreground={foreground}; trace={receipt.head}")
    return 0 if receipt.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
