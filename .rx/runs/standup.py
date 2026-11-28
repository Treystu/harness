"""One standup through the published driver: no hand-driving, no new adapters."""
import hashlib, json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.windows_freebuff_runner import execute

thread = sys.argv[1]
dispatch = int(sys.argv[2])
item = f"standup-{sys.argv[3]}-{thread}"
mission = {"thread": thread, "dispatch": dispatch,
           "phases": ("search", "query", "select", "prepare", "send"),
           "phase_timeout": 420}
digest = hashlib.sha256(f"{dispatch}-{thread}-{item}".encode()).hexdigest()
state = execute(Path(os.environ["LOCALAPPDATA"]) / "harness-freebuff-runner" / item,
                item, mission, digest, ())
print("STATE:", state)
