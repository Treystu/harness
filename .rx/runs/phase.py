"""Run a driver mission with an explicit phase list, through the published runner."""
import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.windows_freebuff_runner import execute

thread, dispatch, tag, phases = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4].split(",")
item = f"standup-{tag}-{thread}"
mission = {"thread": thread, "dispatch": dispatch, "phases": tuple(phases), "phase_timeout": 420}
digest = hashlib.sha256(f"{dispatch}-{thread}-{item}".encode()).hexdigest()
state = execute(Path(os.environ["LOCALAPPDATA"]) / "harness-freebuff-runner" / item,
                item, mission, digest, ())
print("STATE:", state)
