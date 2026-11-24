"""Remove test-run rows from an operator's conversation-memory document (#656).

The unit suite used to append its fixtures to the live operator home: the
durable memory at ``$HARNESS_CONFIG_DIR/chat_history/conversation_memory.json``
had collected fixture paths from temporary directories. ``tests/__init__.py``
now pins ``HARNESS_HOME`` and ``HARNESS_CONFIG_DIR`` at one ephemeral directory
per process, so the leak stops at the source; this script cleans a document
that already collected rows.

It only removes rows it can identify as a test artifact: a fact whose value is
a path under the operating system's temporary directory, or one that runs
through a ``tempfile`` directory -- a path component shaped like
``tmpk3j2h1a``/``.tmpRjtqKW``, which is how ``tempfile.mkdtemp`` names a
scratch directory wherever it lives (the audit's own
``audits/self/_runs/tmp/tmp...`` runs, a ``uv`` build cache). Temporary paths
are never durable operator memory -- they do not survive a reboot or a cleaned
cache -- so the rule needs no history of which test wrote what. A real operator
path containing a component spelled ``tmp`` plus six or more characters is the
one false positive this rule can have, and the backup makes it recoverable.

The memory projection is plain JSON, not the hash-chained ledger. The chain is
untouched by design: editing it would break the chain. Pointing this script at a
``ledger.jsonl`` is refused.

Dry run by default. ``--apply`` writes a timestamped backup beside the document
before rewriting it atomically, and reports the count it removed. A second run
removes nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

#: A ``tempfile.mkdtemp`` directory component, wherever it was created.
_TEMP_COMPONENT_RE = re.compile(r"^\.?tmp[A-Za-z0-9_]{6,}$")

def default_memory_path() -> Path:
    """The operator memory document this script cleans by default."""
    base = os.environ.get("HARNESS_CONFIG_DIR", "").strip()
    root = Path(base).expanduser() if base else Path("~/.config/harness").expanduser()
    return root / "chat_history" / "conversation_memory.json"


def _temp_roots() -> list[str]:
    roots = {tempfile.gettempdir()}
    for name in ("TMPDIR", "TEMP", "TMP"):
        value = os.environ.get(name, "").strip()
        if value:
            roots.add(value)
    return sorted({os.path.normcase(os.path.abspath(r)) for r in roots if r})


def _candidate_forms(value: str) -> list[str]:
    """The value as written, plus its un-doubled form for escaped paths."""
    forms = [value]
    while "\\\\" in value:
        value = value.replace("\\\\", "\\")
        forms.append(value)
    return forms


def is_test_row(fact) -> bool:
    """True when a fact's value names a temporary (scratch) path."""
    if not isinstance(fact, dict):
        return False
    value = fact.get("value")
    if not isinstance(value, str) or not value.strip():
        return False
    roots = _temp_roots()
    for form in _candidate_forms(value.strip()):
        parts = [p for p in re.split(r"[\\/]+", form) if p]
        if any(_TEMP_COMPONENT_RE.match(part) for part in parts):
            return True
        try:
            resolved = os.path.normcase(os.path.abspath(os.path.expanduser(form)))
        except (OSError, ValueError):
            continue
        for root in roots:
            if resolved == root or resolved.startswith(root + os.sep):
                return True
    return False


def test_rows(memory) -> list:
    """Every fact in ``memory`` that this script would remove."""
    if not isinstance(memory, dict):
        return []
    facts = memory.get("facts")
    if not isinstance(facts, list):
        return []
    return [fact for fact in facts if is_test_row(fact)]


def load(path) -> dict:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def clean(path, *, apply: bool) -> dict:
    """Classify and (when ``apply``) remove the test rows in ``path``."""
    path = Path(path)
    report = {
        "path": str(path),
        "exists": path.exists(),
        "applied": bool(apply),
        "removed": 0,
        "kept": 0,
        "backup": None,
    }
    if not report["exists"]:
        return report
    if path.name == "ledger.jsonl" or path.name.startswith("ledger.jsonl."):
        raise SystemExit(
            "refusing to edit {0}: the ledger is a hash-chained evidence store;"
            " only the memory projection is cleanable".format(path))
    memory = load(path)
    rows = test_rows(memory)
    facts = memory.get("facts") if isinstance(memory, dict) else None
    if not isinstance(facts, list):
        return report
    report["removed"] = len(rows)
    report["kept"] = len(facts) - len(rows)
    if not rows or not apply:
        return report
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    backup = path.with_name(path.name + ".bak-" + stamp)
    shutil.copy2(path, backup)
    report["backup"] = str(backup)
    removed_ids = {id(fact) for fact in rows}
    memory["facts"] = [fact for fact in facts if id(fact) not in removed_ids]
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(memory, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    os.replace(tmp, path)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", default=None,
                        help="memory document (default: $HARNESS_CONFIG_DIR/"
                             "chat_history/conversation_memory.json)")
    parser.add_argument("--apply", action="store_true",
                        help="remove the rows (default is a dry run)")
    opts = parser.parse_args(argv)
    target = Path(opts.path) if opts.path else default_memory_path()
    report = clean(target, apply=opts.apply)
    if not report["exists"]:
        print("no memory document at {0}; nothing to do".format(report["path"]))
        return 0
    mode = "removed" if report["applied"] else "would remove"
    print("{0}: {1} {2} test-run row(s), keeping {3} durable fact(s)".format(
        report["path"], mode, report["removed"], report["kept"]))
    if not report["applied"]:
        print("dry-run: nothing written; re-run with --apply to remove them")
    elif report["backup"]:
        print("backup: {0}".format(report["backup"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
