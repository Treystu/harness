"""Window-scoped Windows capture and typing for the Notepad proof."""

import ctypes
import io
from ctypes import wintypes
from threading import Event
from time import monotonic

from driver_core.observation import Capture, fingerprint


class NotepadWindow:
    def __init__(self):
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.GetWindowThreadProcessId.argtypes = (
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
        self.user.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.user.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        self.user.GetAncestor.restype = wintypes.HWND
        self.user.GetClassNameW.argtypes = (
            wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
        self.user.GetWindowTextW.argtypes = (
            wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
        self.user.IsWindowVisible.argtypes = (wintypes.HWND,)
        self.user.IsWindowEnabled.argtypes = (wintypes.HWND,)
        self.user.SetForegroundWindow.argtypes = (wintypes.HWND,)
        self.user.SwitchToThisWindow.argtypes = (wintypes.HWND, wintypes.BOOL)
        self.user.SwitchToThisWindow.restype = None
        self.user.SendMessageTimeoutW.argtypes = (
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
            wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t))
        self.user.SendMessageTimeoutW.restype = wintypes.LPARAM
        self.user.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
        callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.callback = callback
        self.user.EnumWindows.argtypes = (callback, wintypes.LPARAM)
        self.user.EnumChildWindows.argtypes = (wintypes.HWND, callback, wintypes.LPARAM)
        self.owner = None
        self.owner_pid = None

    def foreground(self):
        return self.user.GetForegroundWindow()

    def handles(self, notepad_pids):
        handles = []

        @self.callback
        def visit(hwnd, _):
            if (self.pid(hwnd) in notepad_pids and self.user.IsWindowVisible(hwnd)
                    and self.class_name(hwnd) == "Notepad"):
                handles.append(hwnd)
            return True

        if not self.user.EnumWindows(visit, 0):
            raise RuntimeError("could not enumerate visible Notepad windows")
        return handles

    def pid(self, hwnd):
        pid = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    def class_name(self, hwnd):
        name = ctypes.create_unicode_buffer(128)
        self.user.GetClassNameW(hwnd, name, len(name))
        return name.value

    def activate(self, hwnd):
        if self.foreground() != hwnd and not self.user.SetForegroundWindow(hwnd):
            self.user.SwitchToThisWindow(hwnd, True)
        return self.foreground() == hwnd

    def is_untitled(self, hwnd):
        title = ctypes.create_unicode_buffer(256)
        self.user.GetWindowTextW(hwnd, title, len(title))
        return title.value.casefold().startswith("untitled")

    def bind(self, hwnd):
        self.owner = hwnd
        self.owner_pid = self.pid(hwnd)
        self.require_window()

    def require_window(self):
        if (not self.owner_pid or self.pid(self.owner) != self.owner_pid
                or self.class_name(self.owner) != "Notepad"):
            raise RuntimeError("the mission Notepad window is no longer available")
        return self.owner

    def editor(self):
        owner = self.require_window()
        if not self.user.IsWindowEnabled(owner):
            raise RuntimeError("an owned dialog blocks the Notepad editor")
        editors = []

        @self.callback
        def visit(hwnd, _):
            if (self.pid(hwnd) == self.owner_pid and self.user.IsWindowVisible(hwnd)
                    and self.class_name(hwnd) in ("RichEditD2DPT", "Edit")):
                editors.append(hwnd)
            return True

        self.user.EnumChildWindows(owner, visit, 0)
        if len(editors) != 1:
            raise RuntimeError("could not identify one editor in the mission Notepad window")
        return editors[0]

    def send_editor_message(self, editor, message, value=0, data=0):
        owner = self.require_window()
        if self.pid(editor) != self.owner_pid or self.user.GetAncestor(editor, 2) != owner:
            raise RuntimeError("the Notepad control changed ownership")
        result = ctypes.c_size_t()
        if not self.user.SendMessageTimeoutW(
                editor, message, value, data, 0x22, 250, ctypes.byref(result)):
            raise RuntimeError("the Notepad editor did not answer the window message")
        return result.value

    def text_length(self):
        return self.send_editor_message(self.editor(), 0x000E)  # WM_GETTEXTLENGTH

    def type_text(self, text):
        editor = self.editor()
        for char in text:
            self.send_editor_message(editor, 0x0102, ord(char), 1)  # WM_CHAR

    def release_foreground(self):
        if self.owner and self.pid(self.owner) == self.owner_pid:
            self.user.ShowWindow(self.owner, 6)  # Minimize only the new window.


class NotepadScreen:
    def __init__(self, window):
        self.window = window
        self.last_png = None
        self.capture_seconds = None

    def capture(self, target):
        from PIL import Image
        from windows_capture import WindowsCapture

        started = monotonic()
        hwnd = self.window.require_window()
        capture = WindowsCapture(window_hwnd=hwnd, cursor_capture=False, secondary_window=False)
        ready = Event()
        images = []

        @capture.event
        def on_frame_arrived(frame, control):
            try:
                images.append(Image.frombytes(
                    "RGB", (frame.width, frame.height), frame.frame_buffer.tobytes(),
                    "raw", "BGRX"))
            finally:
                control.stop()
                ready.set()

        @capture.event
        def on_closed():
            ready.set()

        session = capture.start_free_threaded()
        if not ready.wait(1.5):
            session.stop()
            raise RuntimeError("Notepad compositor capture did not return a frame")
        session.wait()
        if not images:
            raise RuntimeError("the Notepad capture closed without a frame")
        frame = images[0]
        if self.window.require_window() != hwnd:
            raise RuntimeError("the Notepad window changed during capture")
        if all(low == high for low, high in frame.getextrema()):
            raise RuntimeError("window-scoped capture returned uniform pixels")
        png = io.BytesIO()
        frame.save(png, format="PNG", compress_level=1)
        self.last_png = png.getvalue()
        self.capture_seconds = round(monotonic() - started, 3)
        return Capture("windows-notepad", target, self.last_png,
                       fingerprint=fingerprint(self.last_png))
