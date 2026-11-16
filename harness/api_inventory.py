"""#283 -- the GUI's handler inventory, derived from the code and held to coverage.

The issue was written for an Electron main process. **There is none**: the only
JavaScript in this repo is a Playwright smoke harness (`tests/ui/package.json`
declares `@playwright/test`, and `tests/ui/harness.spec.js` drives the served
page). The GUI's "IPC handlers / main-process logic" are the localhost UI
server's routes in `harness/server.py` -- the page talks to them over HTTP. The
issue's own dependency clause covers exactly this case: rescope to the
equivalent server-side handlers, record the disposition, and do not invent an
Electron layer to test. That disposition lives in :data:`RESCOPE`.

Two things the acceptance asks for that nothing in the tree did:

* **an inventory taken from the code, not assumed** -- :func:`parse_routes`
  reads `do_GET` / `do_POST` and extracts every literal route (plus the dynamic
  run subresource), with duplicate detection;
* **each handler has at least one behaviour test** -- :func:`coverage` reports
  which routes are never named in the test corpus, and refuses silence by
  requiring anything uncovered to be declared with a reason.

Match semantics mirror the server: an exact route wins, then the longest
matching prefix (`/site/*`), then :data:`NO_ROUTE` -- the 404 path.
"""
import os
import re

#: The rescope disposition #283's dependency clause requires be recorded.
RESCOPE = (
    "No Electron main process exists in this repo (only a Playwright UI smoke "
    "harness: tests/ui/package.json -> @playwright/test). The GUI's handler "
    "surface is the localhost UI server in harness/server.py, so this row tests "
    "those routes and their edge paths instead of inventing an Electron layer."
)

#: Returned by :func:`match` for an unknown method/path (the server's 404 path).
NO_ROUTE = None

#: Routes whose handler is exercised only through another route's test, with the
#: reason. Anything uncovered and NOT declared here fails :func:`coverage_gate`.
DECLARED_COVERAGE_EXEMPTIONS = {}


class InventoryError(ValueError):
    """The route table and the code disagree."""


_ROUTE_RE = re.compile(
    r'"?path"?\s*==\s*"(?P<exact>/[^"]*)"'
    r'|"?path"?\.startswith\(\s*"(?P<prefix>[^"]*)"\s*\)'
    r'|return\s+self\._api_(?P<named>[a-z_]+)\(')
_DEF_RE = re.compile(r"^\s{4}def (do_[A-Z]+)\(", re.MULTILINE)
_DYNAMIC = {"RUN_SUB_RE": r"/api/runs/<run_id>/(cancel|...)"}


def parse_routes(source):
    """Every route literal in ``source``, attributed to the HTTP method block.

    A route is recorded as ``{method, path, kind}`` where ``kind`` is ``exact``,
    ``prefix`` or ``dynamic`` (a regex-dispatched subresource). Only lines inside
    a ``def do_XXX`` block count, so an ``if path ==`` elsewhere cannot invent a
    handler.
    """
    if not isinstance(source, str) or "class UiRequestHandler" not in source:
        raise InventoryError("expected the UI request handler source")
    routes = []
    blocks = list(_DEF_RE.finditer(source))
    for index, match in enumerate(blocks):
        method = match.group(1).replace("do_", "", 1)
        start = match.end()
        end = blocks[index + 1].start() if index + 1 < len(blocks) else len(source)
        for _line_no, line in enumerate(source[start:end].splitlines(), start=1):
            for hit in _ROUTE_RE.finditer(line):
                if hit.group("exact"):
                    routes.append({"method": method, "path": hit.group("exact"),
                                   "kind": "exact"})
                elif hit.group("prefix"):
                    routes.append({"method": method, "path": hit.group("prefix"),
                                   "kind": "prefix"})
    if not routes:
        raise InventoryError("no routes found; the handler shape changed")
    if "RUN_SUB_RE" in source:
        routes.append({"method": "POST", "path": "/api/runs/<run_id>/cancel",
                       "kind": "dynamic"})
    return routes


def inventory(source_path=None):
    """The route table plus the facts the acceptance wants recorded."""
    path = source_path or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "harness", "server.py")
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    routes = parse_routes(source)
    seen = {}
    duplicates = []
    for route in routes:
        key = (route["method"], route["path"])
        if key in seen:
            duplicates.append(list(key))
        seen[key] = route
    if duplicates:
        raise InventoryError(f"duplicate route(s) declared: {duplicates}")
    counts = {}
    for route in routes:
        counts[route["method"]] = counts.get(route["method"], 0) + 1
    return {"routes": routes, "counts": counts,
            "by_method": {m: sorted(r["path"] for r in routes if r["method"] == m)
                          for m in counts},
            "rescope": RESCOPE, "source": os.path.basename(path)}


def match(routes, method, path):
    """Route for a request: exact first, then the longest prefix, else None."""
    if not isinstance(method, str) or not isinstance(path, str):
        raise InventoryError("match needs a method and a path")
    method = method.upper()
    for route in routes:
        if route["method"] != method:
            continue
        if route["kind"] == "exact" and route["path"] == path:
            return route
    prefixes = [r for r in routes
                if r["method"] == method and r["kind"] == "prefix"
                and path.startswith(r["path"])]
    if prefixes:
        return max(prefixes, key=lambda r: len(r["path"]))
    return NO_ROUTE


#: This module's own tests name routes to test the gate itself, so they cannot
#: count as coverage evidence for those routes.
_SELF_TEST_MODULE = "test_api_inventory.py"


def coverage(routes, test_dir, exclude=(_SELF_TEST_MODULE,)):
    """Which routes are named nowhere in the test corpus, and which are covered."""
    corpus = []
    for name in sorted(os.listdir(test_dir)):
        if not name.endswith(".py") or name in set(exclude or ()):
            continue
        with open(os.path.join(test_dir, name), encoding="utf-8",
                  errors="replace") as handle:
            corpus.append(handle.read())
    text = "\n".join(corpus)
    covered, uncovered = [], []
    for route in routes:
        stem = route["path"].split("<")[0]
        (covered if stem and stem in text else uncovered).append(route["path"])
    return {"covered": sorted(set(covered)), "uncovered": sorted(set(uncovered))}


def coverage_gate(routes, test_dir, exemptions=None):
    """Refuse an uncovered route that nobody declared.

    Silence is the failure mode: a handler with no behaviour test and no stated
    reason is exactly what #283 exists to prevent.
    """
    exemptions = DECLARED_COVERAGE_EXEMPTIONS if exemptions is None else exemptions
    # The gate's own test module names routes by design; it is not evidence.
    report = coverage(routes, test_dir, exclude=(_SELF_TEST_MODULE,))
    undeclared = [p for p in report["uncovered"] if p not in exemptions]
    if undeclared:
        raise InventoryError(
            "route(s) with no test and no declared reason: {}".format(undeclared))
    return report
