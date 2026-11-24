"""One direct SCMessenger restart through the published driver, then the 25s observation."""
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
thread = "2ae32937"
dispatch = 7097835295
item = f"restore-{dispatch}-{thread}-scoped-{stamp}"
mission = {"thread": thread, "dispatch": dispatch, "standing": True, "phase_timeout": 600}
digest = hashlib.sha256(f"{dispatch}-{thread}-{item}".encode()).hexdigest()
out = Path(os.environ["LOCALAPPDATA"]) / "harness-freebuff-runner" / item
print("ITEM", item, flush=True)
state = execute(out, item, mission, digest, ())
print("STATE", state, flush=True)

time.sleep(25)
capture = WindowsWindowScreen(FreeBuffWindow(), source="windows-freebuff").capture(
    Target("post-start", GUI))
png = out / "post25.png"
png.write_bytes(capture.payload)
image = Image.open(io.BytesIO(capture.payload))
print(json.dumps({"post25": str(png), "size": image.size,
                  "stop": Dispatch.stop_visible(image) if image.size == (1800, 1131) else None,
                  "sha256": hashlib.sha256(capture.payload).hexdigest()}), flush=True)
