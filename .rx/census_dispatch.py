"""Census of #684 owner dispatches against the claim ledger, using the watch's own parser."""
import json, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from scripts import windows_freebuff_watch as w

comments = json.loads(Path("../Harness/.d684-census.json").read_text(encoding="utf-8"))
known = set(Path("../Harness/.ledger-claims.txt").read_text(encoding="utf-8").split())
now = datetime.now(timezone.utc)

rows = []
for c in sorted(comments, key=lambda x: x.get("id", 0)):
    body = c.get("body") or ""
    if not (w.owner(c) and w.restart_dispatch(body)):
        continue
    parsed = w.parse_dynamic_dispatch(c, now=now)
    cid = c["id"]
    if parsed is None:
        rows.append((cid, c["created_at"], "-", "UNPARSEABLE", "no thread/instruction"))
        continue
    thread = parsed["thread"]
    claim = f"claim-dyn-{cid}-{thread}.json"
    claimed = claim in known
    rows.append((cid, c["created_at"], thread, parsed["kind"], "claimed" if claimed else "unclaimed"))

newest = {}
for cid, created, thread, kind, state in rows:
    if kind == "restart":
        newest[thread] = max(newest.get(thread, 0), cid)

print(f"{'dispatch':>12}  {'created':22}  {'lane':10} {'kind':12} {'claim'}")
for cid, created, thread, kind, state in rows:
    tag = state
    if kind == "restart" and state == "unclaimed" and newest.get(thread) != cid:
        tag = "SUPERSEDED"
    elif kind == "restart" and state == "unclaimed" and newest.get(thread) == cid:
        tag = "LIVE"
    print(f"{cid:>12}  {created:22}  {thread:10} {kind:12} {tag}")
