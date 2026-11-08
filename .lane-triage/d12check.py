"""Local D12 probe: which added harness lines do MY tests execute?

Uses the audit's own diff parser and statement finder, so the answer is the
same shape D12 computes -- it just traces the two new test modules instead of
the whole 5,300-test battery.
"""
import subprocess
import sys
import trace
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "audits" / "self"))
sys.path.insert(0, str(ROOT))
import audit  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "5eb9c3639b2ae89016447904d555b06bded2ee5e"

diff = subprocess.run(
    ["git", "diff", "--unified=0", BASE, "--", "harness/"],
    cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8").stdout
added = audit._parse_added_lines(diff)
print("added files:", {k: len(v) for k, v in added.items()})

runner = unittest.TextTestRunner(stream=open("nul", "w"))
tracer = trace.Trace(count=1, trace=0, ignoredirs=[sys.prefix, sys.exec_prefix])
suite = unittest.defaultTestLoader.loadTestsFromNames(
    ["tests.test_routing_table", "tests.test_economics_cli"])
def _run():
    runner.run(suite)
tracer.runfunc(_run)
counts = tracer.results().counts

executed = {}
for (fname, lineno), hits in counts.items():
    try:
        rel = str(Path(fname).resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        continue
    if hits:
        executed.setdefault(rel, set()).add(lineno)

checked = done = 0
for rel in sorted(added):
    src = (ROOT / rel).read_text(encoding="utf-8")
    stmts = audit._statement_lines(src)
    mine = sorted(ln for ln in added[rel] if ln in stmts)
    hit = [ln for ln in mine if ln in executed.get(rel, set())]
    missing = [ln for ln in mine if ln not in executed.get(rel, set())]
    checked += len(mine)
    done += len(hit)
    if missing:
        print(f"  {rel}: {len(hit)}/{len(mine)} executed; MISSING {missing}")
    else:
        print(f"  {rel}: {len(hit)}/{len(mine)} executed")
print(f"TOTAL {done}/{checked} = {done / checked:.1%}" if checked else "no executable added lines")
