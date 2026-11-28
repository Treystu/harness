"""Pinned runtime home for the laptop driver watch (G4).

The watch executes whatever bytes happen to be in the checkout it is imported
from, and it refused every tick while those bytes were dirty. Measured cost on
2026-11-27: twelve refusals, "uncommitted changes under scripts/ in the driver
worktree", each one a lane session editing the cure it was about to test in the
same tree the watch runs from.

The cure is a copy of the executing code at a named commit, materialized
outside the dev tree, with a manifest that pins the exact bytes. The watch then
reads its identity from that pin instead of from the dev tree's git state, so
dev dirtiness is never its input - and a runtime home whose bytes drifted from
its pin refuses by name rather than running unverified code.

Layout of a home::

    <home>/scripts/...            tracked code at the pinned commit
    <home>/driver_core/...        tracked code at the pinned commit
    <home>/.runtime-pin.json      {"sha": ..., "manifest": {rel: sha256, ...}}

``install`` reads the source through ``git archive``, so only committed bytes
are ever copied; an uncommitted edit in the source cannot leak into a home.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile

RUNTIME_PATHS = ("scripts", "driver_core")
PIN_NAME = ".runtime-pin.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hidden_kwargs() -> dict:
    if sys.platform != "win32":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {"startupinfo": startupinfo,
            "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}


def _git(source: Path, *args: str, binary: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(source), *args],
                          capture_output=True, text=not binary, timeout=120,
                          check=False, **_hidden_kwargs())


def resolve_sha(source: Path, sha: str | None = None) -> str:
    """Resolve ``sha`` (or HEAD) in ``source`` to a full commit id, or refuse."""
    wanted = (sha or "HEAD").strip() or "HEAD"
    result = _git(source, "rev-parse", "--verify", f"{wanted}^{{commit}}")
    resolved = (result.stdout or "").strip()
    if result.returncode != 0 or not resolved:
        raise RuntimeError(f"cannot resolve {wanted!r} in {source}: "
                           f"{(result.stderr or '').strip() or 'no commit found'}")
    return resolved


def manifest(root: Path) -> dict[str, str]:
    """``{relative path: sha256}`` for the executable code under ``root``."""
    entries: dict[str, str] = {}
    for name in RUNTIME_PATHS:
        base = Path(root) / name
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            rel = path.relative_to(root).as_posix()
            entries[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return entries


def write_pin(home: Path, sha: str, *, source: str = "") -> dict:
    """Record the current bytes of ``home`` as pinned at ``sha``."""
    home = Path(home)
    code = manifest(home)
    if not any(rel.endswith("windows_freebuff_watch.py") for rel in code):
        raise RuntimeError(f"{home} does not carry scripts/windows_freebuff_watch.py")
    pin = {"sha": sha, "source": source, "installed_at": _utc_now(),
           "paths": list(RUNTIME_PATHS), "manifest": code}
    (home / PIN_NAME).write_text(json.dumps(pin, indent=2, sort_keys=True) + "\n",
                                 encoding="utf-8")
    return pin


def read_pin(home: Path) -> dict | None:
    """The pin recorded in ``home``, or ``None`` when it is not a pinned home."""
    path = Path(home) / PIN_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("manifest"), dict):
        return None
    return data


def verify(home: Path, pin: dict | None = None) -> tuple[bool, str]:
    """Whether the bytes in ``home`` are exactly the pinned bytes.

    Returns ``(ok, detail)``; ``detail`` names the drift so a refusal is
    actionable rather than a boolean nobody can act on.
    """
    home = Path(home)
    pin = pin if pin is not None else read_pin(home)
    if not pin:
        return False, f"{home} carries no pin"
    expected = pin.get("manifest") or {}
    actual = manifest(home)
    missing = sorted(set(expected) - set(actual))
    added = sorted(set(actual) - set(expected))
    changed = sorted(rel for rel in set(expected) & set(actual)
                     if expected[rel] != actual[rel])
    if not (missing or added or changed):
        return True, "matches the pin"
    parts = []
    if changed:
        parts.append("changed: " + ", ".join(changed[:5]))
    if missing:
        parts.append("missing: " + ", ".join(missing[:5]))
    if added:
        parts.append("not in the pin: " + ", ".join(added[:5]))
    return False, "; ".join(parts)


def install(source: Path, home: Path, *, sha: str | None = None) -> dict:
    """Materialize tracked code at ``sha`` from ``source`` into ``home``.

    Only committed bytes travel: the source is read through ``git archive``,
    so an uncommitted edit in the dev tree cannot reach the runtime home.
    """
    source, home = Path(source), Path(home)
    resolved = resolve_sha(source, sha)
    archive = _git(source, "archive", "--format=tar", resolved, *RUNTIME_PATHS, binary=True)
    if archive.returncode != 0:
        raise RuntimeError(f"git archive {resolved[:8]} failed: "
                           f"{(archive.stderr or b'').decode('utf-8', 'replace').strip()}")
    home.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            name = member.name.replace("\\", "/")
            if any(part == ".." for part in name.split("/")):
                continue
            target = home / name
            target.parent.mkdir(parents=True, exist_ok=True)
            extracted = tar.extractfile(member)
            if extracted is not None:
                target.write_bytes(extracted.read())
    return write_pin(home, resolved, source=str(source))


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="driver-runtime-home",
        description="Materialize or verify the pinned runtime home for the watch (G4).")
    parser.add_argument("action", choices=("install", "verify", "manifest"), default="verify", nargs="?")
    parser.add_argument("--source", default=".", help="Checkout the code is pinned from")
    parser.add_argument("--home", required=True, help="Pinned runtime home directory")
    parser.add_argument("--sha", default=None, help="Commit to pin (default: the source's HEAD)")
    parser.add_argument("--json", action="store_true")
    opts = parser.parse_args(argv)
    home = Path(opts.home)
    if opts.action == "install":
        result = install(Path(opts.source), home, sha=opts.sha)
        payload = {"state": "installed", "home": str(home), "sha": result["sha"],
                   "files": len(result["manifest"])}
    elif opts.action == "manifest":
        payload = {"home": str(home), "manifest": manifest(home)}
    else:
        ok, detail = verify(home)
        payload = {"state": "verified" if ok else "refused", "home": str(home), "detail": detail,
                   "sha": (read_pin(home) or {}).get("sha", "")}
    print(json.dumps(payload, indent=2) if opts.json else
          f"driver-runtime-home {payload['state']} {payload.get('sha', '')[:8]} {payload.get('detail', '')}".strip())
    return 0 if payload["state"] != "refused" else 1


if __name__ == "__main__":
    raise SystemExit(_main())
