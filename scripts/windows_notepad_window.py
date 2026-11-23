"""Window-scoped Windows capture and typing for the Notepad proof."""

import ctypes
import io
from ctypes import wintypes

from driver_core.observation import Capture, fingerprint


class GuiThreadInfo(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("active", wintypes.HWND),
        ("focus", wintypes.HWND),
        ("capture", wintypes.HWND),
        ("menu_owner", wintypes.HWND),
        ("move_size", wintypes.HWND),
        ("caret", wintypes.HWND),
        ("caret_rect", wintypes.RECT),
    ]


class NotepadWindow:
    def __init__(self):
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.GetWindowThreadProcessId.argtypes = (
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
        self.user.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.user.GetGUIThreadInfo.argtypes = (
            wintypes.DWORD, ctypes.POINTER(GuiThreadInfo))
        self.user.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        self.user.GetAncestor.restype = wintypes.HWND
        self.user.GetClassNameW.argtypes = (
            wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
        self.user.GetWindowTextW.argtypes = (
            wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
        self.user.IsWindowVisible.argtypes = (wintypes.HWND,)
        self.user.SetForegroundWindow.argtypes = (wintypes.HWND,)
        self.user.SwitchToThisWindow.argtypes = (wintypes.HWND, wintypes.BOOL)
        self.user.SwitchToThisWindow.restype = None
        self.user.SendMessageTimeoutW.argtypes = (
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
            wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t))
        self.user.SendMessageTimeoutW.restype = wintypes.LPARAM
        self.user.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
        self.owner = None

    def foreground(self):
        return self.user.GetForegroundWindow()

    def handles(self, notepad_pids):
        handles = []
        callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @callback
        def visit(hwnd, _):
            pid = wintypes.DWORD()
            self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in notepad_pids and self.user.IsWindowVisible(hwnd):
                name = ctypes.create_unicode_buffer(128)
                self.user.GetClassNameW(hwnd, name, len(name))
                if name.value == "Notepad":
                    handles.append(hwnd)
            return True

        self.user.EnumWindows.argtypes = (callback, wintypes.LPARAM)
        if not self.user.EnumWindows(visit, 0):
            raise RuntimeError("could not enumerate visible Notepad windows")
        return handles

    def activate(self, hwnd):
        if self.foreground() != hwnd and not self.user.SetForegroundWindow(hwnd):
            self.user.SwitchToThisWindow(hwnd, True)
        return self.foreground() == hwnd

    def is_untitled(self, hwnd):
        title = ctypes.create_unicode_buffer(256)
        self.user.GetWindowTextW(hwnd, title, len(title))
        return title.value.casefold().startswith("untitled")

    def require_foreground(self):
        hwnd = self.foreground()
        if not self.owner or self.user.GetAncestor(hwnd, 3) != self.owner:
            raise RuntimeError("the mission Notepad window lost foreground")
        return hwnd

    def type_text(self, text):
        foreground = self.require_foreground()
        thread = self.user.GetWindowThreadProcessId(foreground, None)
        info = GuiThreadInfo(size=ctypes.sizeof(GuiThreadInfo))
        if not self.user.GetGUIThreadInfo(thread, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not info.focus or self.user.GetAncestor(info.focus, 3) != self.owner:
            raise RuntimeError("the focused control is outside the mission window")
        for char in text:
            self.require_foreground()
            if self.user.GetAncestor(info.focus, 3) != self.owner:
                raise RuntimeError("the Notepad control changed ownership")
            result = ctypes.c_size_t()
            if not self.user.SendMessageTimeoutW(
                    info.focus, 0x0102, ord(char), 1, 0x22, 250,
                    ctypes.byref(result)):
                raise RuntimeError("Notepad did not accept the character message")

    def release_foreground(self):
        if self.owner and self.user.GetAncestor(self.foreground(), 3) == self.owner:
            self.user.ShowWindow(self.owner, 6)  # Minimize only the new window.


class NotepadScreen:
    def __init__(self, window):
        self.window = window
        self.last_png = None

    def capture(self, target):
        from PIL import ImageGrab

        hwnd = self.window.require_foreground()
        frame = ImageGrab.grab(window=hwnd)
        if self.window.require_foreground() != hwnd:
            raise RuntimeError("the Notepad window changed during capture")
        if all(low == high for low, high in frame.getextrema()):
            raise RuntimeError("window-scoped capture returned uniform pixels")
        png = io.BytesIO()
        frame.save(png, format="PNG", compress_level=1)
        self.last_png = png.getvalue()
        return Capture("windows-notepad", target, self.last_png,
                       fingerprint=fingerprint(self.last_png))
