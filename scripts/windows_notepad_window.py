"""Window-scoped Windows capture and typing for the Notepad proof."""

import ctypes
import io
from ctypes import wintypes
from threading import Event
from time import monotonic, sleep

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
        self.user.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
        self.user.GetWindow.restype = wintypes.HWND
        self.user.GetLastActivePopup.argtypes = (wintypes.HWND,)
        self.user.GetLastActivePopup.restype = wintypes.HWND
        self.user.GetDlgCtrlID.argtypes = (wintypes.HWND,)
        self.user.PostMessageW.argtypes = (
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
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
        return self.title(hwnd).casefold().startswith("untitled")

    def title(self, hwnd):
        title = ctypes.create_unicode_buffer(256)
        self.user.GetWindowTextW(hwnd, title, len(title))
        return title.value

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

    def send_message(self, hwnd, message, value=0, data=0):
        owner = self.require_window()
        if self.pid(hwnd) != self.owner_pid or self.user.GetAncestor(hwnd, 3) != owner:
            raise RuntimeError("the Notepad target changed ownership")
        result = ctypes.c_size_t()
        if not self.user.SendMessageTimeoutW(
                hwnd, message, value, data, 0x22, 750, ctypes.byref(result)):
            raise RuntimeError("the Notepad target did not answer the window message")
        return result.value

    def text_length(self):
        return self.send_message(self.editor(), 0x000E)  # WM_GETTEXTLENGTH

    def type_text(self, text):
        editor = self.editor()
        for char in text:
            self.send_message(editor, 0x0102, ord(char), 1)  # WM_CHAR

    def save_dialog(self):
        owner = self.require_window()
        popup = self.user.GetLastActivePopup(owner)
        if (popup and popup != owner and self.user.GetWindow(popup, 4) == owner
                and self.pid(popup) == self.owner_pid and self.class_name(popup) == "#32770"
                and self.title(popup).casefold() == "save as"):
            return popup
        return None

    def dialog_control(self, dialog, control_id, class_name):
        controls = []

        @self.callback
        def visit(hwnd, _):
            if (self.pid(hwnd) == self.owner_pid and self.class_name(hwnd) == class_name
                    and self.user.GetDlgCtrlID(hwnd) == control_id):
                controls.append(hwnd)
            return True

        self.user.EnumChildWindows(dialog, visit, 0)
        if len(controls) != 1:
            raise RuntimeError(f"could not identify Save As {class_name} control {control_id}")
        return controls[0]

    def save_to(self, destination):
        deadline = monotonic() + 3
        dialog = self.save_dialog()
        while dialog is None and monotonic() < deadline:
            sleep(0.1)
            dialog = self.save_dialog()
        if dialog is None:
            raise RuntimeError("the resolved Notepad window has no owned Save As dialog")
        entry = self.dialog_control(dialog, 1001, "Edit")
        self.dialog_control(dialog, 1, "Button")
        name = ctypes.create_unicode_buffer(str(destination))
        self.send_message(entry, 0x000C, 0, ctypes.addressof(name))  # WM_SETTEXT
        readback = ctypes.create_unicode_buffer(len(name))
        self.send_message(entry, 0x000D, len(readback), ctypes.addressof(readback))
        if readback.value != str(destination) or destination.exists():
            raise RuntimeError("Save As filename readback or destination changed")
        if self.save_dialog() != dialog or self.user.GetAncestor(entry, 3) != self.owner:
            raise RuntimeError("the owned Save As filename control changed")
        # Queue Enter for this edit control so the dialog message loop invokes Save.
        if not self.user.PostMessageW(entry, 0x0100, 0x0D, 0x001C0001):  # WM_KEYDOWN
            raise RuntimeError("Notepad refused the Save As Enter message")

    def submit_dialog(self, dialog, control_id, button):
        if self.save_dialog() != dialog:
            raise RuntimeError("the owned Save As dialog changed")
        if not self.user.PostMessageW(dialog, 0x0111, control_id, button):  # WM_COMMAND
            raise RuntimeError("Notepad refused the Save As command")

    def cancel_save(self):
        dialog = self.save_dialog()
        if dialog:
            button = self.dialog_control(dialog, 2, "Button")
            self.submit_dialog(dialog, 2, button)

    def release_foreground(self):
        if self.owner and self.pid(self.owner) == self.owner_pid:
            self.user.ShowWindow(self.owner, 7)  # Minimize without activating another window.


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
