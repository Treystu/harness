from pathlib import Path
line = "from .ledger_canary import evidence_rows"
for rel, anchor in [
    ("harness/capability.py", "from .errors import"),
    ("harness/refine.py", "from .errors import"),
    ("harness/saturation.py", "from .errors import"),
    ("harness/site_export.py", "from .errors import"),
]:
    p = Path(rel); s = p.read_text(encoding="utf-8")
    if line in s:
        print(rel, "already"); continue
    idx = s.index(anchor)
    end = s.index("\n", s.index(")", idx) if "(" in s[idx:s.index("\n", idx)] else s.index("\n", idx))
    # simple: insert before the anchor line
    start = s.rindex("\n", 0, idx) + 1
    s = s[:start] + line + "\n" + s[start:]
    p.write_text(s, encoding="utf-8")
    print(rel, "imported")
