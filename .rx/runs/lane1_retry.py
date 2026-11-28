"""One direct Lane 1 restart through the published driver, then the 25s observation."""
import hashlib
import io
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PIL import Image
from driver_core.observation import GUI, Target
from scripts.windows_freebuff_capture import FreeBuffWindow
from scripts.windows_freebuff_dispatch import Dispatch
from scripts.windows_freebuff_runner import execute
from scripts.windows_notepad_window import WindowsWindowScreen

stamp = sys.argv[1]
thread = "315608d2"
item = f"restore-7100931819-{thread}-scoped-{stamp}"
mission = {"thread": thread, "dispatch": 7100931819, "standing": True, "phase_timeout": 240}
digest = hashlib.sha256(f"7100931819-{thread}-{item}".encode()).hexdigest()
out = Path(os.environ["LOCALAPPDATA"]) / "harness-freebuff-runner" / item
print("ITEM", item)
state = execute(out, item, mission, digest, ())
print("STATE", state)

time.sleep(25)
capture = WindowsWindowScreen(FreeBuffWindow(), source="windows-freebuff").capture(
    Target("post-start", GUI))
png = out / "post25.png"
png.write_bytes(capture.payload)
image = Image.open(io.BytesIO(capture.payload))
print(json.dumps({"post25": str(png), "size": image.size,
                  "stop": Dispatch.stop_visible(image) if image.size == (1800, 1131) else None,
                  "sha256": hashlib.sha256(capture.payload).hexdigest()}))
