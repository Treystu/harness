#!/usr/bin/env python3
"""ProofGate v2 — Tier 0 deterministic receipt checker (no LLM).

WHY v2 (cold-review cures, 2026-11-26): v1 checked the *working tree*
(`git status`), so on any clean CI checkout it passed vacuously, and its
"evidence" was any non-empty string. v2 checks a commit RANGE and binds
every claim to content hashes.

Usage:
  proofgate.py REPO RECEIPT_JSON BASE_SHA HEAD_SHA   # range mode (the gate)
  proofgate.py REPO RECEIPT_JSON --worktree          # pre-commit local mode

Receipt schema (exactly what the code reads — no other fields are used):
  {
    "head": "<full 40-hex sha; must equal HEAD_SHA (range) or HEAD (worktree)>",
    "claims": [
      {"file": "<path>", "evidence": ["sha256:<hex>", ...],
       "renamed_from": "<old path>"        # only for renames
      }, ...
    ],
    "sorry_free": true,
    "axioms_declared": ["<axiom name>", ...]   # exact set across claimed .lean files
  }

Rules enforced (range mode):
  * BASE != HEAD (an empty range FAILS — no vacuous pass).
  * Census = `git diff --name-status -z BASE HEAD` (renames and paths with
    spaces/non-ASCII handled by -z). Claimed files must equal the census
    exactly: new/modified/renamed-to paths plus deleted paths.
  * Every claim's evidence must contain sha256:<hex> of the file's content
    at HEAD — or at BASE for a deleted file (and for a rename's old path).
    Editing a file after the receipt is written breaks the hash → FAIL.
  * For claimed .lean files: the set of `axiom NAME` declarations in the
    HEAD content must equal "axioms_declared" exactly, and the content must
    not contain `native_decide` (a soundness hole the hash cannot see).
    The authoritative Lean gate is lean_ci.sh; this is defense in depth.
  * "sorry_free" must be exactly true. It is an attestation; its backing is
    the .lean scan above plus lean_ci.sh in CI, and it is labelled as such.

Known limits (stated, not hidden): files covered by .gitignore are outside
the git census by definition; evidence hashes bind content, they do not
judge whether a claim's *statement* is true — that stays with Jev/house
verification. Malformed receipts FAIL with a diagnostic, never a traceback.
"""
import hashlib, json, re, subprocess, sys

def git(repo, *args, text=True):
    return subprocess.check_output(["git", "-C", repo, *args], text=text)

def blob_sha256(repo, rev, path):
    data = git(repo, "show", f"{rev}:{path}", text=False)
    return hashlib.sha256(data).hexdigest()

def fail(errors):
    print("PROOFGATE FAIL")
    for e in errors:
        print(" -", e)
    sys.exit(1)

def load_receipt(path):
    try:
        r = json.load(open(path))
    except Exception as e:
        fail([f"MALFORMED RECEIPT: cannot parse JSON ({e})"])
    if not isinstance(r, dict):
        fail(["MALFORMED RECEIPT: top level must be an object"])
    errs = []
    if not (isinstance(r.get("head"), str) and re.fullmatch(r"[0-9a-f]{40}", r["head"])):
        errs.append("MALFORMED RECEIPT: 'head' must be a full 40-hex sha")
    if not isinstance(r.get("claims"), list):
        errs.append("MALFORMED RECEIPT: 'claims' must be a list")
    else:
        for i, c in enumerate(r["claims"]):
            if not isinstance(c, dict) or not isinstance(c.get("file"), str):
                errs.append(f"MALFORMED RECEIPT: claims[{i}] needs a 'file' string")
            elif not (isinstance(c.get("evidence"), list)
                      and all(isinstance(x, str) for x in c["evidence"])):
                errs.append(f"MALFORMED RECEIPT: claims[{i}].evidence must be a list of strings")
    if not isinstance(r.get("axioms_declared", []), list):
        errs.append("MALFORMED RECEIPT: 'axioms_declared' must be a list")
    if errs:
        fail(errs)
    return r

def range_census(repo, base, head):
    """Returns {path: (status, old_path_or_None)} from a -z name-status diff."""
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
    args = [a for a in sys.argv[1:]]
    if len(args) < 2:
        fail(["usage: proofgate.py REPO RECEIPT (BASE HEAD | --worktree)"])
    repo, receipt_path = args[0], args[1]
    receipt = load_receipt(receipt_path)
    errors = []
    worktree = "--worktree" in args
    if worktree:
        head = git(repo, "rev-parse", "HEAD").strip()
        raw = git(repo, "status", "--porcelain", "-z", text=False)
        names = [p for p in raw.decode("utf-8", "surrogateescape").split("\0") if p.strip()]
        census = {}
        for entry in names:
            census[entry[3:]] = ("W", None)
        base = head
    else:
        if len(args) < 4:
            fail(["range mode needs BASE and HEAD shas (no default — an empty range must never pass silently)"])
        base, head = args[2], args[3]
        if base == head:
            fail(["EMPTY RANGE: base == head — nothing to verify, refusing vacuous pass"])
        census = range_census(repo, base, head)
    if receipt["head"] != head:
        errors.append(f"STALE HEAD: receipt {receipt['head']} != checked head {head}")
    claims = {c["file"]: c for c in receipt["claims"]}
    if sorted(claims) != sorted(census):
        errors.append(f"CENSUS MISMATCH: claimed {sorted(claims)} != changed {sorted(census)}")
    declared_axioms = set(receipt.get("axioms_declared", []))
    found_axioms = set()
    for path, claim in claims.items():
        status, old = census.get(path, ("?", None))
        # content-hash evidence binding
        try:
            if status == "D":
                want = blob_sha256(repo, base, path)
                where = "at BASE (deleted file)"
            elif worktree:
                import os
                want = hashlib.sha256(open(os.path.join(repo, path), "rb").read()).hexdigest()
                where = "in working tree"
            else:
                want = blob_sha256(repo, head, path)
                where = "at HEAD"
        except Exception:
            errors.append(f"UNREADABLE: cannot read {path} {where if 'where' in dir() else ''}")
            continue
        hashes = [e[7:] for e in claim["evidence"] if e.startswith("sha256:")]
        if want not in hashes:
            errors.append(f"EVIDENCE HASH MISMATCH: {path} needs sha256:{want} ({where})")
        if old and not worktree:
            if claim.get("renamed_from") != old:
                errors.append(f"RENAME NOT DECLARED: {old} -> {path}")
            try:
                old_hash = blob_sha256(repo, base, old)
                if old_hash not in hashes:
                    errors.append(f"EVIDENCE HASH MISMATCH: rename source {old} needs sha256:{old_hash} (at BASE)")
            except Exception:
                errors.append(f"UNREADABLE: rename source {old} at BASE")
        if path.endswith(".lean") and not worktree:
            try:
                content = git(repo, "show", f"{head}:{path}")
            except Exception:
                content = ""
            found_axioms |= set(re.findall(r"(?m)^\s*axiom\s+([A-Za-z_][A-Za-z0-9_]*)", content))
            if "native_decide" in content:
                errors.append(f"SOUNDNESS HOLE: native_decide in {path}")
            code = re.sub(r"/-.*?-/", "", content, flags=re.S)
            code = "\n".join(l.split("--")[0] for l in code.splitlines())
            if re.search(r"\b(sorry|admit)\b", code):
                errors.append(f"SORRY-EQUIVALENT in {path} (defense-in-depth scan; lean_ci.sh is authoritative)")
    if found_axioms != declared_axioms:
        errors.append(f"AXIOM SET MISMATCH: declared {sorted(declared_axioms)} != found {sorted(found_axioms)}")
    if receipt.get("sorry_free") is not True:
        errors.append("SORRY_FREE NOT ATTESTED (attestation backed by the .lean scan + lean_ci.sh)")
    if errors:
        fail(errors)
    mode = "worktree" if worktree else f"range {base[:8]}..{head[:8]}"
    print(f"PROOFGATE PASS mode={mode} head={head[:8]} files={len(census)} claims={len(claims)} axioms={len(found_axioms)}")

if __name__ == "__main__":
    main()
