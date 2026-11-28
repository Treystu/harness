import json, re, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from scripts import windows_freebuff_watch as w
comments = json.loads(Path("../Harness/.d684-census.json").read_text(encoding="utf-8"))
ids = (7117989632, 7121037795, 7131314944, 7135450398, 7138681649, 7140150416)
for c in comments:
    if c["id"] not in ids:
        continue
    body = (c.get("body") or "").strip()
    flat = re.sub(r"\s+", " ", body)
    print("=" * 78)
    print(c["id"], c["created_at"])
    print("FIRST LINE:", body.splitlines()[0][:150])
    print("banner:", bool(w.DISPATCH_BANNER.match(body)), "| restart:", w.restart_dispatch(body),
          "| action:", bool(w.RUNNER_ACTION.search(body)),
          "| quoted:", f'"{w.CONTINUATION}"' in flat,
          "| lane:", w._lane_thread_from_dispatch(body))
    print("ACTION LINES:", [l[:120] for l in body.splitlines() if re.match(r"^(Runner\s+)?Action\b", l, re.I)][:3])
    print("HEAD:", flat[:400])
