"""Additive-only tool versioning, enforced instead of merely documented (issue #286).

``harness/mcp.py`` and ``docs/mcp.md`` both state the policy: a tool schema may
gain optional fields, but removing, renaming or retyping one -- or making an
optional field required -- needs a new tool name, because a client that cached
the old contract must never be silently surprised. Until this module existed,
nothing checked that. The policy was prose, and a schema edit that broke every
cached client would have been reviewed like any other diff.

This module keeps the invariant record of the surface that shipped
(``packs/mcp/tool-surface.snapshot.json``) and compares the live catalog to it.
Breaking edits are violations with the tool, the field and what changed;
additive edits (a new tool, a new optional property) are reported as additions
and allowed. Descriptions, titles and other prose are free to change -- the
contract is the shape.

Run it directly to check a working tree::

    python -m harness.mcp_surface --check

or rewrite the snapshot after an intentional additive change::

    python -m harness.mcp_surface --write
"""
import argparse
import json
import os
import sys

SNAPSHOT_SCHEMA = "mcp-tool-surface@1"

#: Violation kinds. Each one is a breaking change for a cached client.
VIOLATIONS = (
    "tool_removed",
    "property_removed",
    "property_retyped",
    "property_newly_required",
)


class SurfaceError(ValueError):
    """A schema change that the additive-only policy refuses."""


def default_snapshot_path(root=None):
    base = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "packs", "mcp", "tool-surface.snapshot.json")


def _type_of(prop):
    if not isinstance(prop, dict):
        return "untyped"
    value = prop.get("type")
    if isinstance(value, list):
        return "|".join(sorted(str(item) for item in value))
    return str(value) if value is not None else "untyped"


def surface(schemas):
    """The contract-relevant shape of a catalog: names, properties, types, required."""
    if not isinstance(schemas, (list, tuple)) or not schemas:
        raise SurfaceError("a catalog must be a non-empty sequence of schemas")
    out = {}
    for schema in schemas:
        if not isinstance(schema, dict):
            raise SurfaceError(f"schema {schema!r} is not a mapping")
        name = schema.get("name")
        if not isinstance(name, str) or not name.strip():
            raise SurfaceError("every tool schema needs a name")
        if name in out:
            raise SurfaceError(f"duplicate tool name {name!r}")
        spec = schema.get("inputSchema")
        spec = spec if isinstance(spec, dict) else {}
        props = spec.get("properties")
        props = props if isinstance(props, dict) else {}
        required = spec.get("required")
        required = [str(item) for item in required] if isinstance(required, list) else []
        for item in required:
            if item not in props:
                raise SurfaceError(
                    f"tool {name!r} requires {item!r}, which it does not declare")
        out[name] = {
            "required": sorted(required),
            "properties": {str(key): _type_of(value) for key, value in props.items()},
        }
    return out


def snapshot(schemas):
    """A snapshot document for the given catalog."""
    return {"schema": SNAPSHOT_SCHEMA, "tools": surface(schemas)}


def load_snapshot(path):
    """Load a snapshot document, refusing one that cannot pin a surface."""
    with open(path, encoding="utf-8") as handle:
        try:
            doc = json.load(handle)
        except ValueError as exc:
            raise SurfaceError(f"{path} is not valid JSON: {exc}") from None
    if not isinstance(doc, dict) or doc.get("schema") != SNAPSHOT_SCHEMA:
        raise SurfaceError(f"{path} is not a {SNAPSHOT_SCHEMA} snapshot")
    tools = doc.get("tools")
    if not isinstance(tools, dict) or not tools:
        raise SurfaceError(f"{path} pins no tools")
    for name, entry in tools.items():
        if not isinstance(entry, dict):
            raise SurfaceError(f"{path}: {name!r} is not a mapping")
        props = entry.get("properties")
        if not isinstance(props, dict):
            raise SurfaceError(f"{path}: {name!r} declares no properties mapping")
        required = entry.get("required", [])
        if not isinstance(required, list):
            raise SurfaceError(f"{path}: {name!r} required is not a list")
    return doc


def check(pinned, schemas):
    """Compare a snapshot to a live catalog.

    Returns ``{"violations": [...], "additions": [...]}`` where every violation
    is ``{tool, kind, detail}`` and every addition is ``{tool, kind, detail}``.
    A break never hides behind an addition: they are reported separately so a
    reviewer sees which side of the policy a change falls on.
    """
    live = surface(schemas)
    pinned_tools = pinned["tools"] if isinstance(pinned, dict) else {}
    violations = []
    additions = []
    for name in sorted(pinned_tools):
        if name not in live:
            violations.append({"tool": name, "kind": "tool_removed",
                               "detail": "the tool is gone; clients that call it break"})
            continue
        before = pinned_tools[name]
        after = live[name]
        old_props = before.get("properties") or {}
        new_props = after["properties"]
        for prop in sorted(old_props):
            if prop not in new_props:
                violations.append({
                    "tool": name, "kind": "property_removed",
                    "detail": f"{prop!r} was declared and is gone "
                              f"(removing or renaming needs a new tool name)"})
                continue
            if old_props[prop] != new_props[prop]:
                violations.append({
                    "tool": name, "kind": "property_retyped",
                    "detail": f"{prop!r} changed type {old_props[prop]!r} -> "
                              f"{new_props[prop]!r}"})
        old_required = set(before.get("required") or [])
        new_required = set(after["required"])
        for prop in sorted(new_required - old_required):
            if prop in old_props:
                detail = (f"{prop!r} was optional and is now required; a cached "
                          f"client that omits it is refused")
            else:
                detail = (f"new field {prop!r} arrives already required; every "
                          f"cached client that omits it is refused")
            violations.append({"tool": name, "kind": "property_newly_required",
                               "detail": detail})
        for prop in sorted(set(new_props) - set(old_props)):
            additions.append({"tool": name, "kind": "property_added",
                              "detail": f"optional property {prop!r}"})
    for name in sorted(set(live) - set(pinned_tools)):
        additions.append({"tool": name, "kind": "tool_added",
                          "detail": "new tool"})
    return {"violations": violations, "additions": additions}


def assert_additive(pinned_path, schemas):
    """Raise unless the catalog is an additive change from the pinned snapshot.

    Returns the number of additive changes so a successful check says what it
    allowed; the violation list goes into the error so a refusal is actionable.
    """
    result = check(load_snapshot(pinned_path), schemas)
    if result["violations"]:
        lines = [
            f"MCP tool surface is not additive-only ({len(result['violations'])} violation(s)):"
        ]
        for item in result["violations"]:
            lines.append("  - {} [{}] {}".format(item["tool"], item["kind"],
                                             item["detail"]))
        lines.append("A breaking change needs a new tool name; see docs/mcp.md.")
        raise SurfaceError("\n".join(lines))
    return len(result["additions"])


def write_snapshot(path, schemas):
    """Pin the current catalog. Only after an intentional additive change."""
    doc = snapshot(schemas)
    target = os.path.dirname(os.path.abspath(path))
    if target:
        os.makedirs(target, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(doc, handle, indent=1, sort_keys=True)
        handle.write("\n")
    return len(doc["tools"])


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m harness.mcp_surface",
        description="Check the MCP tool surface against the additive-only policy.")
    parser.add_argument("--check", action="store_true",
                        help="fail when the catalog is not an additive change")
    parser.add_argument("--write", action="store_true",
                        help="re-pin the snapshot from the current catalog")
    parser.add_argument("--snapshot", default=None,
                        help="snapshot path (default packs/mcp/tool-surface.snapshot.json)")
    parser.add_argument("--quiet", action="store_true", help="only print failures")
    args = parser.parse_args(argv)
    if args.check == args.write:
        parser.error("choose exactly one of --check or --write")
    from .mcp_schemas import TOOL_SCHEMAS
    path = args.snapshot or default_snapshot_path()
    if args.write:
        count = write_snapshot(path, TOOL_SCHEMAS)
        print(f"[surface] pinned {count} tools -> {path}")
        return 0
    try:
        allowed = assert_additive(path, TOOL_SCHEMAS)
    except SurfaceError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not args.quiet:
        print(f"[surface] additive-only: {len(TOOL_SCHEMAS)} tools, "
              f"{allowed} additive change(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
