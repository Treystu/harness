#!/usr/bin/env python3
"""Frozen theorem-statement hashes (cold-review cure: statement weakening
was undetectable). A statement = text from `theorem NAME` through the first
line containing `:=`, whitespace-normalised, sha256'd. Changing a frozen
statement is a gate/rulebook change: regenerate with --freeze deliberately,
never in passing."""
import hashlib, re, sys, glob

def statements():
    out = {}
    for f in sorted(glob.glob("Pilot/*.lean") + glob.glob("Pilot.lean")):
        lines = open(f).read().splitlines()
        i = 0
        while i < len(lines):
            m = re.match(r"\s*theorem\s+([A-Za-z_][A-Za-z0-9_.]*)", lines[i])
            if m:
                chunk = [lines[i]]
                while ":=" not in lines[i] and i + 1 < len(lines):
                    i += 1
                    chunk.append(lines[i])
                text = re.sub(r"\s+", " ", " ".join(chunk)).strip()
                out[m.group(1)] = hashlib.sha256(text.encode()).hexdigest()[:16]
            i += 1
    return out

if __name__ == "__main__":
    cur = statements()
    if "--freeze" in sys.argv:
        with open("FROZEN.txt", "w") as fh:
            for name in sorted(cur):
                fh.write(f"{name} {cur[name]}\n")
        print(f"FROZEN.txt written: {len(cur)} statements")
        sys.exit(0)
    frozen = {}
    try:
        for line in open("FROZEN.txt"):
            n, h = line.split()
            frozen[n] = h
    except FileNotFoundError:
        print("FROZEN CHECK FAIL: FROZEN.txt missing"); sys.exit(1)
    bad = []
    for n, h in sorted(cur.items()):
        if n not in frozen:
            bad.append(f"NEW STATEMENT not in FROZEN.txt: {n} (freeze deliberately via the gate process)")
        elif frozen[n] != h:
            bad.append(f"STATEMENT CHANGED: {n} frozen={frozen[n]} current={h}")
    for n in frozen:
        if n not in cur:
            bad.append(f"STATEMENT REMOVED: {n}")
    if bad:
        print("FROZEN CHECK FAIL"); [print(" -", b) for b in bad]; sys.exit(1)
    print(f"FROZEN CHECK PASS: {len(cur)} statements unchanged")
