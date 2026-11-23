"""Restore one exact Windows foreground handle with a bounded activation retry."""

import ctypes
import time
from ctypes import wintypes


def activate_exact(hwnd, foreground):
    if foreground() == hwnd:
        return True
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.SetForegroundWindow.argtypes = (wintypes.HWND,)
    user.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user.GetWindowThreadProcessId.restype = wintypes.DWORD
    user.BringWindowToTop.argtypes = (wintypes.HWND,)
    user.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
    user.PeekMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                 wintypes.UINT, wintypes.UINT, wintypes.UINT)
    user.SetForegroundWindow(hwnd)
    previous = foreground()
    if previous and previous != hwnd:
        user.PeekMessageW(ctypes.byref(wintypes.MSG()), None, 0, 0, 0)
        caller = ctypes.windll.kernel32.GetCurrentThreadId()
        current = user.GetWindowThreadProcessId(previous, None)
        attached = caller != current and user.AttachThreadInput(caller, current, True)
        try:
            user.BringWindowToTop(hwnd)
            user.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user.AttachThreadInput(caller, current, False)
    deadline = time.monotonic() + 0.75
    while foreground() != hwnd and time.monotonic() < deadline:
        time.sleep(0.05)
    return foreground() == hwnd
