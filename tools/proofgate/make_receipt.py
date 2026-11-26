#!/usr/bin/env python3
"""ProofGate receipt generator — the deterministic companion to proofgate.py.

Usage:
  make_receipt.py REPO BASE_SHA HEAD_SHA OUT_JSON

Builds the receipt proofgate.py verifies: the census of
`git diff --name-status -z BASE HEAD` (parsed exactly as the checker parses
it), one claim per changed path whose evidence carries the sha256 of the
file's content at HEAD (at BASE for deletions; a rename claim carries both
the new path's HEAD hash and the source path's BASE hash and declares
`renamed_from`), the exact set of `axiom NAME` declarations across claimed
.lean files at HEAD, and the sorry_free attestation (the checker's own
.lean scan plus lean_ci.sh are the backing enforcement; this generator
never judges statement truth).

The receipt is generated, never committed: a committed receipt would have
to claim its own hash. CI archives the generated receipt as a build
artifact, pinning exactly what was checked for the range.
"""
import hashlib, json, re, subprocess, sys


def git(repo, *args, text=True):
    return subprocess.check_output(["git", "-C", repo, *args], text=text)


def blob_sha256(repo, rev, path):
    data = git(repo, "show", f"{rev}:{path}", text=False)
    return hashlib.sha256(data).hexdigest()


def range_census(repo, base, head):
    """{path: (status, old_path_or_None)} — identical parse to proofgate.py."""
    raw = git(repo, "diff", "--name-status", "-z", base, head, text=False)
    parts = raw.decode("utf-8", "surrogateescape").split("\0")
    census, i = {}, 0
    while i < len(parts):
        status = parts[i].strip()
        if not status:
            i += 1
            continue
        code = status[0]
        if code in ("R", "C"):
            old, new = parts[i + 1], parts[i + 2]
            census[new] = (code, old)
            i += 3
        else:
            census[parts[i + 1]] = (code, None)
            i += 2
    return census


def main():
    if len(sys.argv) != 5:
        print("usage: make_receipt.py REPO BASE_SHA HEAD_SHA OUT_JSON", file=sys.stderr)
        return 2
    repo, base, head, out = sys.argv[1:5]
    head = git(repo, "rev-parse", head).strip()
    base = git(repo, "rev-parse", base).strip()
    if base == head:
        print("EMPTY RANGE: base == head — no receipt can be generated", file=sys.stderr)
        return 1
    census = range_census(repo, base, head)
    claims, axioms = [], set()
    for path in sorted(census):
        status, old = census[path]
        if status == "D":
            evidence = ["sha256:" + blob_sha256(repo, base, path)]
        else:
            evidence = ["sha256:" + blob_sha256(repo, head, path)]
        claim = {"file": path, "evidence": evidence}
        if old:
            claim["renamed_from"] = old
            evidence.append("sha256:" + blob_sha256(repo, base, old))
        if path.endswith(".lean") and status != "D":
            content = git(repo, "show", f"{head}:{path}")
            axioms |= set(re.findall(r"(?m)^\s*axiom\s+([A-Za-z_][A-Za-z0-9_]*)", content))
        claims.append(claim)
    receipt = {
        "head": head,
        "claims": claims,
        "sorry_free": True,
        "axioms_declared": sorted(axioms),
    }
    with open(out, "w") as f:
        json.dump(receipt, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"receipt written: {out} files={len(claims)} axioms={len(axioms)} head={head[:8]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
