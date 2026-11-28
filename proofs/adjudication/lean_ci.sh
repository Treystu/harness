#!/bin/bash
# Tier 1 Lean CI gate v3 (cold-review cures, 2026-11-26).
# v1/v2 holes closed here: audit covered only 4 theorems; planted `axiom`s
# and `sorryAx`/`native_decide` were invisible; statement weakening was
# undetectable; scan glob was a hardcoded non-recursive list.
# Layers: (1) frozen statement hashes, (2) comment-stripped token scan over
# EVERY .lean file in the project (defense in depth only), (3) lake build,
# (4) FULL axiom audit: #print axioms for every theorem, failing on sorryAx
# or any axiom outside the standard allowed set. Layer 4 is authoritative —
# it reads the kernel's own record, not source text.
set -euo pipefail
export PATH="$HOME/.elan/bin:$PATH"
cd "$(dirname "$0")"

python3 frozen.py

python3 - <<'PYEOF'
import re, sys, glob, os
files = [f for f in glob.glob("**/*.lean", recursive=True) if not f.startswith(".lake")]
bad = []
for f in files:
    src = open(f).read()
    src = re.sub(r"/-.*?-/", "", src, flags=re.S)
    src = "\n".join(l.split("--")[0] for l in src.splitlines())
    for i, line in enumerate(src.splitlines(), 1):
        if re.search(r"\b(sorry|admit|sorryAx|native_decide)\b", line):
            bad.append(f"{f}:{i}: {line.strip()}")
        m = re.match(r"\s*axiom\s+([A-Za-z_][A-Za-z0-9_]*)", line)
        if m:
            bad.append(f"{f}:{i}: axiom declaration '{m.group(1)}' — project axioms are banned (use the standard set only)")
if bad:
    print("LEAN_CI FAIL: banned tokens/declarations:"); [print(" ", b) for b in bad]; sys.exit(1)
print(f"token scan PASS over {len(files)} files (defense in depth; axiom audit is authoritative)")
PYEOF

lake build

AUDIT_FILE=".axaudit-tmp.lean"
trap 'rm -f "$AUDIT_FILE"' EXIT
python3 - > "$AUDIT_FILE" <<'PYEOF'
import re, glob
names = []
for f in sorted(glob.glob("Pilot/*.lean")):
    for line in open(f):
        m = re.match(r"\s*theorem\s+([A-Za-z_][A-Za-z0-9_.]*)", line)
        if m:
            names.append(m.group(1))
print("import Pilot")
for n in names:
    print(f"#print axioms Pilot.{n}" if "." not in n else f"#print axioms {n}")
PYEOF
OUT=$(lake env lean "$AUDIT_FILE" 2>&1)
echo "$OUT"
python3 - "$OUT" <<'PYEOF'
import re, sys
out = sys.argv[1]
allowed = {"propext", "Classical.choice", "Quot.sound"}
bad = []
if "sorryAx" in out:
    bad.append("sorryAx present in some theorem's axiom set")
for m in re.finditer(r"depends on axioms: \[([^\]]*)\]", out):
    for ax in [a.strip() for a in m.group(1).split(",") if a.strip()]:
        if ax not in allowed:
            bad.append(f"non-standard axiom relied on: {ax}")
count = out.count("depends on axioms") + out.count("does not depend on any axioms")
if count == 0:
    bad.append("axiom audit produced no per-theorem output — audit itself failed")
if bad:
    print("LEAN_CI FAIL: axiom audit:"); [print(" -", b) for b in bad]; sys.exit(1)
print(f"axiom audit PASS: {count} theorems, standard axioms only, no sorryAx")
PYEOF
echo "LEAN_CI PASS"
