"""Read-only capture of the current FreeBuff surface via the driver's own path."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from driver_core.observation import GUI, Target
from scripts.windows_freebuff_capture import FreeBuffWindow
from scripts.windows_notepad_window import WindowsWindowScreen

out = Path(__file__).resolve().parent / "now.png"
window = FreeBuffWindow()
print("HANDLE", window.handle, "PID", window.pid(window.handle), "TITLE", window.api.title_of(window.handle))
capture = WindowsWindowScreen(window, source="windows-freebuff").capture(Target("existing FreeBuff desktop", GUI))
out.write_bytes(capture.payload)
print("WROTE", out, len(capture.payload))
