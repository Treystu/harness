"""Lockfile/pyproject agreement for the uv migration (issue #289).

The migration's guardrail is that the uv path must be *equivalent* to the pip
path before anything is removed, and that a green CI run gates it. Neither is
true if the lockfile has quietly drifted from ``pyproject.toml``: a lock that
still says the old project version, or that lacks an extra the project declares,
installs a different world than the one the project describes, and the drift is
invisible until someone runs ``uv sync --frozen``.

This module makes the drift visible without a network: it parses both files and
reports every disagreement -- project version, ``requires-python``, per-extra
membership, lock schema shape, and any locked package without a name or version.
``python -m harness.deps_lock --check`` exits non-zero on a disagreement.

It cannot re-resolve: that needs a registry. It does not need one to say the
files disagree, which is the failure mode that actually bites.
"""
import argparse
import os
import sys

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - the repo supports 3.9+
    import tomli as tomllib  # type: ignore[no-redef]

#: Lock schema versions this checker understands (``uv.lock`` ``version`` field).
SUPPORTED_LOCK_VERSIONS = (1,)


class LockError(ValueError):
    """A lockfile or pyproject that cannot be checked honestly."""


def load(root):
    """Load ``pyproject.toml`` and ``uv.lock`` from a project root."""
    pyproject_path = os.path.join(root, "pyproject.toml")
    lock_path = os.path.join(root, "uv.lock")
    for path in (pyproject_path, lock_path):
        if not os.path.exists(path):
            raise LockError(f"{path} is missing")
    try:
        with open(pyproject_path, "rb") as handle:
            pyproject = tomllib.load(handle)
        with open(lock_path, "rb") as handle:
            lock = tomllib.load(handle)
    except (OSError, ValueError) as exc:
        raise LockError(f"cannot read the dependency files under {root}: {exc}") from None
    project = pyproject.get("project")
    if not isinstance(project, dict):
        raise LockError(f"{pyproject_path} has no [project] table")
    return project, lock


def _requirement_names(requirements):
    """Bare package names from PEP 508-ish requirement strings."""
    names = []
    for item in requirements or []:
        text = str(item).strip()
        for index, char in enumerate(text):
            if char in " <>=!~[;@(":
                text = text[:index]
                break
        if text:
            names.append(text)
    return names


def root_package(lock, name):
    for entry in lock.get("package") or []:
        if isinstance(entry, dict) and entry.get("name") == name:
            return entry
    return None


def check(project, lock):
    """Compare pyproject against uv.lock. Returns ``{"drift": [...], "facts": {...}}``."""
    drift = []
    facts = {}
    lock_version = lock.get("version")
    facts["lock_version"] = lock_version
    if lock_version not in SUPPORTED_LOCK_VERSIONS:
        drift.append({
            "kind": "unsupported_lock_version",
            "detail": f"uv.lock version {lock_version!r} is not one of "
                      f"{list(SUPPORTED_LOCK_VERSIONS)}",
        })
    name = project.get("name")
    version = project.get("version")
    facts["project"] = name
    facts["project_version"] = version
    root = root_package(lock, name)
    if root is None:
        drift.append({"kind": "project_not_locked",
                      "detail": f"uv.lock has no package named {name!r}"})
        return {"drift": drift, "facts": facts}
    facts["locked_version"] = root.get("version")
    if root.get("version") != version:
        drift.append({
            "kind": "project_version_drift",
            "detail": f"pyproject says {version!r}, uv.lock pins {root.get('version')!r}; "
                      f"run `uv lock` and commit the result",
        })
    wants = project.get("requires-python")
    has = lock.get("requires-python")
    facts["requires_python"] = {"pyproject": wants, "lock": has}
    if wants != has:
        drift.append({
            "kind": "requires_python_drift",
            "detail": f"pyproject requires-python {wants!r}, uv.lock {has!r}",
        })
    declared = project.get("optional-dependencies") or {}
    locked = root.get("optional-dependencies") or {}
    facts["extras"] = {"pyproject": sorted(declared), "lock": sorted(locked)}
    for extra in sorted(declared):
        if extra not in locked:
            drift.append({
                "kind": "extra_missing_from_lock",
                "detail": f"pyproject declares the {extra!r} extra; uv.lock has no "
                          f"such group, so `uv sync --extra {extra}` installs a "
                          f"different world than the project describes",
            })
            continue
        want_names = set(_requirement_names(declared[extra]))
        have_names = {str(item.get("name")) for item in locked[extra]
                      if isinstance(item, dict)}
        missing = sorted(want_names - have_names)
        if missing:
            drift.append({
                "kind": "extra_member_missing",
                "detail": f"the {extra!r} extra locks {sorted(have_names)} but "
                          f"pyproject declares {sorted(want_names)}; missing {missing}",
            })
    for extra in sorted(set(locked) - set(declared)):
        drift.append({
            "kind": "extra_not_declared",
            "detail": f"uv.lock carries a {extra!r} group that pyproject does not declare",
        })
    packages = lock.get("package") or []
    facts["locked_packages"] = len(packages)
    for entry in packages:
        if not isinstance(entry, dict):
            drift.append({"kind": "malformed_package", "detail": repr(entry)[:80]})
            continue
        if not entry.get("name") or not entry.get("version"):
            drift.append({
                "kind": "package_without_identity",
                "detail": f"locked entry {entry.get('name')!r} has no name/version",
            })
    return {"drift": drift, "facts": facts}


def render(result):
    lines = ["[deps] project={} version={} locked={} packages={}".format(result["facts"].get("project"), result["facts"].get("project_version"),
                result["facts"].get("locked_version"),
                result["facts"].get("locked_packages"))]
    for item in result["drift"]:
        lines.append(f"[deps] DRIFT {item['kind']:<28} {item['detail']}")
    status_str = "IN SYNC" if not result["drift"] else f"{len(result['drift'])} drift(s)"
    lines.append(f"[deps] {status_str}")
    return "\n".join(lines)


def default_root(root=None):
    return root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m harness.deps_lock",
        description="Check uv.lock against pyproject.toml without a network.")
    parser.add_argument("--check", action="store_true",
                        help="verify the lock against the project (the default action)")
    parser.add_argument("--root", default=None, help="project root (default: repo root)")
    parser.add_argument("--quiet", action="store_true", help="print only drift")
    args = parser.parse_args(argv)
    # ``--check`` is the only action; accepting it explicitly keeps the documented
    # command (`python -m harness.deps_lock --check`) working.
    try:
        project, lock = load(default_root(args.root))
        result = check(project, lock)
    except LockError as exc:
        print(f"[deps] {exc}", file=sys.stderr)
        return 2
    if args.quiet and not result["drift"]:
        return 0
    print(render(result))
    return 0 if not result["drift"] else 1


if __name__ == "__main__":
    sys.exit(main())
