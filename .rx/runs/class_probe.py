import ctypes
import os
import subprocess
import time
from ctypes import wintypes

u = ctypes.windll.user32
u.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
u.GetClassNameW.restype = ctypes.c_int
u.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
u.GetWindowTextW.restype = ctypes.c_int
u.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
u.IsWindowVisible.argtypes = (wintypes.HWND,)

py = os.path.join(os.environ["TEMP"], "harness-notepad-venv-20261122", "Scripts", "python.exe")
proc = subprocess.Popen([py, "-c", "import time; time.sleep(10)"])
time.sleep(2.5)

found = []


@ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
def enum(hwnd, _):
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == proc.pid:
        name = ctypes.create_unicode_buffer(128)
        title = ctypes.create_unicode_buffer(512)
        u.GetClassNameW(hwnd, name, 128)
        u.GetWindowTextW(hwnd, title, 512)
        found.append((hwnd, name.value, title.value, bool(u.IsWindowVisible(hwnd))))
    return True


u.EnumWindows(enum, 0)
fg = u.GetForegroundWindow()
print("pid", proc.pid, "foreground", fg)
for row in found:
    print("window", row)
proc.wait(timeout=20)
