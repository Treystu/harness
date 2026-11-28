"""Prove, predicate by predicate, why the two pending #684 dispatches are unclaimed."""
import json, re, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from scripts import windows_freebuff_watch as w

now = datetime.now(timezone.utc)
docs = [json.loads(Path(p).read_text(encoding="utf-8"))
        for p in ("../Harness/.d7145072019.json", "../Harness/.d7146588401.json")]
allc = json.loads(Path("../Harness/.d684-since.json").read_text(encoding="utf-8"))

for c in docs:
    body = (c.get("body") or "").strip()
    flat = re.sub(r"\s+", " ", body)
    print("=" * 72)
    print("dispatch", c["id"], "created", c["created_at"])
    print("owner           ", w.owner(c))
    print("banner match    ", bool(w.DISPATCH_BANNER.match(body)))
    print("restart_dispatch", w.restart_dispatch(body))
    print("RUNNER_ACTION   ", bool(w.RUNNER_ACTION.search(body)),
          "| action lines:",
          [ln for ln in body.splitlines() if "action" in ln.lower()][:3])
    print("continue quoted ", f'"{w.CONTINUATION}"' in flat or f"'{w.CONTINUATION}'" in flat)
    print("lane thread     ", w._lane_thread_from_dispatch(body))
    print("lane line       ", re.findall(r"^Lane:\s*(.+)$", body, re.I | re.M))
    print("filed_on_issue  ", w.filed_on_issue(allc, c["id"]))
    print("parse_dynamic   ", w.parse_dynamic_dispatch(c, now=now))
