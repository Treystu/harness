"""Remove test-run rows an unguarded suite left in an operator ledger (#656).

DRY RUN BY DEFAULT. Nothing is written unless ``--apply`` is passed, and the
count that would be (or was) removed is printed either way.

What counts as a test row is a heuristic, so it is explicit and reviewable:

- the record's ``caller`` / ``source`` / ``origin`` / ``task_id`` /
  ``session_id`` field contains one of ``--marker`` (default: ``test``,
  ``pytest``, ``unittest``, ``temp``, ``harness-test-home``), or
- ``--since`` / ``--until`` bound a window the operator has identified as a test
  run, or
- ``--task-id`` names exact task ids to remove.

The script never guesses silently: every removed line's identifying fields are
printed, and ``--backup`` (default on) writes ``<ledger>.bak-test-cleanup``
before the rewrite.

Usage:
    python scripts/cleanup_test_records.py --ledger ~/.config/harness/ledger.jsonl
    python scripts/cleanup_test_records.py --ledger ... --apply
"""
import argparse
import json
import os
import shutil
import sys

DEFAULT_MARKERS = ("test", "pytest", "unittest", "temp", "harness-test-home")
MATCH_KEYS = ("caller", "source", "origin", "task_id", "session_id",
              "run_id", "model")


def default_ledger_path():
    configured = os.environ.get("HARNESS_LEDGER")
    if configured:
        return os.path.expanduser(configured)
    config_dir = os.environ.get("HARNESS_CONFIG_DIR") or "~/.config/harness"
    return os.path.join(os.path.expanduser(config_dir), "ledger.jsonl")


def _identify(record):
    return " | ".join(f"{k}={record[k]}" for k in MATCH_KEYS if record.get(k))


def is_test_record(record, *, markers, task_ids, since=None, until=None):
    if task_ids and str(record.get("task_id")) in task_ids:
        return True
    haystack = " ".join(str(record.get(k) or "") for k in MATCH_KEYS).lower()
    if any(marker.lower() in haystack for marker in markers):
        return True
    stamp = str(record.get("timestamp") or record.get("ts") or "")
    if stamp:
        if since and stamp >= since:
            return True
        if until and stamp <= until:
            return True
    return False


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="cleanup_test_records",
        description="Remove test-run rows from a harness ledger (dry run "
                    "unless --apply).")
    ap.add_argument("--ledger", default=default_ledger_path(),
                    help="JSONL ledger to clean (default: $HARNESS_LEDGER or "
                         "~/.config/harness/ledger.jsonl)")
    ap.add_argument("--apply", action="store_true",
                    help="rewrite the ledger; without this nothing is written")
    ap.add_argument("--marker", action="append", default=None,
                    help="case-insensitive marker (repeatable; replaces the "
                         "default test markers)")
    ap.add_argument("--task-id", action="append", default=None,
                    help="exact task id to remove (repeatable)")
    ap.add_argument("--since", default=None,
                    help="ISO-8601 lower bound on a record timestamp")
    ap.add_argument("--until", default=None,
                    help="ISO-8601 upper bound on a record timestamp")
    ap.add_argument("--backup", default=True, action=argparse.BooleanOptionalAction,
                    help="write <ledger>.bak-test-cleanup before rewriting "
                         "(default: on)")
    opts = ap.parse_args(argv)

    path = os.path.abspath(opts.ledger)
    if not os.path.isfile(path):
        print(f"[cleanup] no ledger at {path}; nothing to do", file=sys.stderr)
        return 2
    markers = tuple(opts.marker or DEFAULT_MARKERS)
    task_ids = set(opts.task_id or ())

    kept, removed = [], []
    with open(path, encoding="utf-8") as fh:
        for number, line in enumerate(fh, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except ValueError:
                kept.append(line)  # An unreadable line is not ours to delete.
                continue
            if not isinstance(record, dict):
                kept.append(line)
                continue
            if is_test_record(record, markers=markers, task_ids=task_ids,
                              since=opts.since, until=opts.until):
                removed.append((number, _identify(record)))
            else:
                kept.append(line)

    total = len(kept) + len(removed)
    verb = "removed" if opts.apply else "would remove"
    print(f"[cleanup] ledger: {path}")
    print(f"[cleanup] records: {total} total, {len(removed)} test rows, "
          f"{len(kept)} kept")
    for number, label in removed[:50]:
        print(f"[cleanup]   line {number}: {label}")
    if len(removed) > 50:
        print(f"[cleanup]   ... {len(removed) - 50} more")
    print(f"[cleanup] {verb} {len(removed)} of {total} records")

    if not opts.apply:
        print("[cleanup] dry run: no file was written (pass --apply to rewrite)")
        return 0
    if not removed:
        return 0
    if opts.backup:
        backup = path + ".bak-test-cleanup"
        shutil.copy2(path, backup)
        print(f"[cleanup] backup: {backup}")
    tmp = path + ".cleanup-tmp"
    with open(tmp, "w", encoding="utf-8") as out:
        for line in kept:
            out.write(line if line.endswith("\n") else line + "\n")
    os.replace(tmp, path)
    print(f"[cleanup] {verb} {len(removed)} of {total} records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
