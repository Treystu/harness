"""#281 -- a versioned, sanitized bench results bundle for the Proof Bench.

The pieces exist and do not meet: `harness/bench.py` runs manifests but its
report carries no schema, no manifest hash, no harness version and no timestamp;
`harness/site_export.py` sanitizes and publishes bundles but knows nothing about
a bench run's identity. The issue asks for the seam between them:

* a **versioned** results document -- schema, manifest hash, harness version,
  timestamp, per-task outcomes, cost -- so two runs of the same manifest are
  comparable and a third party can tell what produced a number;
* a document **the existing export path accepts**: same sanitizer posture (no
  paths, no prompt text, no error strings), the same credential scan, and bench
  rows already in the shape `site_export.build_bench_rows` emits;
* a documented **one-command reproduction** carrying the manifest and the cost
  ceiling it was run under.

Identity is content, not wall clock: ``bundle_id`` hashes everything except
``generated_at``, so re-running an unchanged manifest yields the same id (the
site's dedupe key must be stable across re-runs).
"""
import hashlib
import json
import ntpath
import os
import posixpath
import re
from datetime import datetime, timezone

#: Bundle schema version. Bump when a field changes meaning.
SCHEMA = "bench-results-v1"

#: Mirror of the exporter's byte cap: a bench bundle is a curated sample too.
MAX_BUNDLE_BYTES = 512 * 1024

#: The task fields a manifest hash covers. Identity is the *work asked for*:
#: instruction, fixture file, verify command and budget -- not file order,
#: JSON whitespace or the absolute path the manifest happened to live at.
_HASHED_TASK_FIELDS = ("name", "file", "instruction", "verify",
                       "task_max_cost", "max_rounds")

#: The per-task fields a public row may carry. Nothing else is copied.
_RESULT_FIELDS = ("task", "status", "rounds", "rotations", "cost", "model", "tier")

#: Defense-in-depth scan, same shapes the exporter refuses on.
_SECRET_PATTERNS = (
    re.compile(r"sk-or-v1-[0-9a-zA-Z]{16,}"),
    re.compile(r"apikey_[0-9a-zA-Z]{8,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)

REQUIRED_KEYS = ("schema", "bundle_id", "generated_at", "harness_version",
                 "manifest", "results", "totals", "calibration", "reproduction",
                 "export_rows")


class BenchBundleError(ValueError):
    """A bundle that would publish an unreproducible or unsafe claim."""


def _utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha16(value):
    return hashlib.sha256(_canon(value).encode("utf-8")).hexdigest()[:16]


def load_tasks(path):
    """Read a manifest the way `bench.load_manifest` does: a dir of JSONs or one file."""
    if not isinstance(path, str) or not path:
        raise BenchBundleError(f"manifest path must be a string, got {path!r}")
    if os.path.isdir(path):
        tasks = []
        # Two shipped layouts: a flat dir of task JSONs, and the bench/tasks
        # layout of one directory per task holding ``task.json``.
        for name in sorted(os.listdir(path)):
            candidate = os.path.join(path, name)
            if name.endswith(".json"):
                with open(candidate, encoding="utf-8") as handle:
                    tasks.append(json.load(handle))
            elif os.path.isdir(candidate):
                task_file = os.path.join(candidate, "task.json")
                if os.path.isfile(task_file):
                    with open(task_file, encoding="utf-8") as handle:
                        tasks.append(json.load(handle))
    elif os.path.isfile(path):
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        tasks = data if isinstance(data, list) else data.get("tasks")
    else:
        raise BenchBundleError(f"manifest not found: {path}")
    if not isinstance(tasks, list) or not tasks:
        raise BenchBundleError(f"manifest {path} declares no tasks")
    for task in tasks:
        if not isinstance(task, dict) or not task.get("name"):
            raise BenchBundleError(f"manifest {path} has a task without a name")
        if not task.get("instruction"):
            raise BenchBundleError(
                f"task {task['name']!r} has no instruction; a bench task without "
                "one is not a known-answer run")
    return tasks


def manifest_digest(tasks):
    """``(sha256, task_count)`` over the work the manifest asks for.

    Keyed by task name so file order and directory listing order cannot change
    the digest; only the declared fields above participate.
    """
    if not tasks:
        raise BenchBundleError("cannot hash an empty manifest")
    rows = []
    for task in tasks:
        row = {k: task.get(k) for k in _HASHED_TASK_FIELDS if task.get(k) is not None}
        row["name"] = task["name"]
        rows.append(row)
    rows.sort(key=lambda r: r["name"])
    return hashlib.sha256(_canon(rows).encode("utf-8")).hexdigest(), len(rows)


def _number(value, field):
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BenchBundleError(f"{field} must be numeric, got {value!r}")
    if value < 0:
        raise BenchBundleError(f"{field} must not be negative, got {value!r}")
    return value


def task_row(result):
    """One allowlisted public row from a bench result.

    Prompt text, absolute paths, error strings and gate output never enter a
    bundle: the exporter's own posture, applied here rather than re-derived at
    publish time.
    """
    if not isinstance(result, dict):
        raise BenchBundleError(f"a result must be a mapping, got {type(result).__name__}")
    name = result.get("name") or result.get("task")
    if not isinstance(name, str) or not name:
        raise BenchBundleError("a result needs a task name")
    rounds = result.get("rounds")
    if isinstance(rounds, list):
        rounds = len(rounds)
    row = {
        "task": name,
        "status": str(result.get("status") or "unknown"),
        "rounds": int(_number(rounds, "rounds")),
        "rotations": int(_number(result.get("rotations"), "rotations")),
        "cost": round(float(_number(result.get("cost"), "cost")), 9),
    }
    for optional in ("model", "tier"):
        if result.get(optional):
            row[optional] = str(result[optional])
    return {k: row[k] for k in _RESULT_FIELDS if k in row}


def _calibration_block(report, baseline):
    """Per-model observed rows, with deltas only where a baseline is given."""
    out = {}
    rows = ((report or {}).get("calibration") or {})
    base = ((baseline or {}).get("calibration") or {})
    for model in sorted(rows):
        row = rows[model] or {}
        entry = {
            "samples": int(row.get("samples") or 0),
            "structured_samples": int(row.get("structured_samples") or 0),
            "success_rate": row.get("success_rate"),
            "structured_success_rate": row.get("structured_success_rate"),
            "unusable_outputs": int(row.get("unusable_outputs") or 0),
        }
        before = (base.get(model) or {}).get("success_rate")
        now = entry["success_rate"]
        if before is not None and now is not None:
            entry["success_rate_delta"] = round(float(now) - float(before), 6)
        out[model] = entry
    return out


def reproduction_command(manifest_path, task_max_cost=None):
    """The one command that re-runs this manifest, with the ceiling it used."""
    if not isinstance(manifest_path, str) or not manifest_path:
        raise BenchBundleError("reproduction needs a manifest path")
    rel = manifest_path.replace("\\", "/")
    if ntpath.isabs(rel) or ntpath.splitdrive(rel)[0] or posixpath.isabs(rel):
        # A public bundle names the manifest by its repo-relative path only.
        marker = "/bench/"
        if marker in rel:
            rel = "bench/" + rel.split(marker, 1)[1]
        else:
            rel = posixpath.basename(rel)
    cmd = f"python -m harness.cli bench {rel}"
    if task_max_cost is not None:
        cmd += f" --task-max-cost {float(task_max_cost):g}"
    return cmd


def build_bundle(results, manifest_path, harness_version, report=None,
                 baseline_report=None, generated_at=None, task_max_cost=None):
    """Build the versioned bench results bundle.

    ``results`` are `bench.run_bench`'s per-task entries; ``manifest_path`` is
    the manifest they came from (hashed here, so a bundle always names the work
    that produced it).
    """
    if not isinstance(results, list) or not results:
        raise BenchBundleError("a bench bundle needs at least one result")
    if not isinstance(harness_version, str) or not harness_version.strip():
        raise BenchBundleError("a bench bundle needs the harness version that ran it")
    tasks = load_tasks(manifest_path)
    digest, declared = manifest_digest(tasks)
    rows = [task_row(r) for r in results]
    names = {r["task"] for r in rows}
    missing = [t["name"] for t in tasks if t["name"] not in names]
    if missing:
        raise BenchBundleError(
            f"results do not cover the manifest; missing {missing} - a partial "
            "run must not publish as a complete one")

    total = sum(r["cost"] for r in rows)
    completed = sum(1 for r in rows if r["status"] == "ok")
    total_rounds = sum(r["rounds"] for r in rows)
    bundle = {
        "schema": SCHEMA,
        "bundle_id": "",
        "generated_at": generated_at or _utc_now(),
        "harness_version": harness_version.strip(),
        "manifest": {
            "file": os.path.basename(manifest_path.rstrip("/\\")),
            "sha256": digest,
            "tasks": declared,
        },
        "results": sorted(rows, key=lambda r: r["task"]),
        "totals": {
            "tasks": len(rows),
            "completed": completed,
            "pass_rate": round(completed / len(rows), 4),
            "total_rounds": total_rounds,
            "mean_verify_rounds": round(total_rounds / len(rows), 4),
            "total_cost": round(total, 9),
            "tracked_cost": True,
        },
        "calibration": _calibration_block(report, baseline_report),
        "reproduction": reproduction_command(manifest_path, task_max_cost),
        "export_rows": [
            {
                "task_ref": r["task"],
                "model": r.get("model", ""),
                "tier": r.get("tier"),
                "passed": r["status"] == "ok",
                "rounds": r["rounds"],
                "cost": r["cost"],
                "gated": True,
            }
            for r in sorted(rows, key=lambda r: r["task"])
        ],
    }
    core = {k: v for k, v in bundle.items() if k not in ("bundle_id", "generated_at")}
    bundle["bundle_id"] = _sha16(core)
    return bundle


def scan_credentials(text):
    """The credential shapes the exporter refuses on, checked here first."""
    for pattern in _SECRET_PATTERNS:
        hit = pattern.search(text)
        if hit:
            return pattern.pattern
    return None


def serialize(bundle):
    """Canonical JSON, secret-scanned and capped before it can be written."""
    if not isinstance(bundle, dict):
        raise BenchBundleError("a bundle must be a mapping")
    payload = _canon(bundle)
    hit = scan_credentials(payload)
    if hit:
        raise BenchBundleError(
            f"refusing to serialize: credential-shaped content matched {hit!r}")
    size = len(payload.encode("utf-8"))
    if size > MAX_BUNDLE_BYTES:
        raise BenchBundleError(
            f"bundle is {size} bytes, over the {MAX_BUNDLE_BYTES}-byte cap; "
            "the exporter would refuse it")
    return payload


def verify_bundle(bundle):
    """Validate a bundle (fresh or read back from disk) against the schema.

    Refuses: wrong schema, a missing key, an absolute or traversing manifest
    path, a task count that disagrees with the results, a non-numeric or
    negative cost/rounds, a bundle id that does not match its content, and
    credential-shaped content.
    """
    if not isinstance(bundle, dict):
        raise BenchBundleError(f"a bundle must be a mapping, got {type(bundle).__name__}")
    missing = [k for k in REQUIRED_KEYS if k not in bundle]
    if missing:
        raise BenchBundleError(f"bundle is missing {missing}")
    if bundle["schema"] != SCHEMA:
        raise BenchBundleError(
            f"unknown schema {bundle['schema']!r}; this reader speaks {SCHEMA!r}")
    manifest = bundle["manifest"]
    if not isinstance(manifest, dict) or len(str(manifest.get("sha256") or "")) != 64:
        raise BenchBundleError("manifest.sha256 must be a full sha256 hex digest")
    fname = str(manifest.get("file") or "")
    if not fname or "/" in fname or "\\" in fname or fname in (".", ".."):
        raise BenchBundleError(
            f"manifest.file must be a bare name, got {fname!r} (a path leaks the machine)")
    results = bundle["results"]
    if not isinstance(results, list) or not results:
        raise BenchBundleError("results must be a non-empty list")
    if int(manifest.get("tasks") or 0) != len(results):
        raise BenchBundleError(
            f"manifest declares {manifest.get('tasks')} task(s) but {len(results)} "
            "result(s) are present")
    for row in results:
        if not isinstance(row, dict) or not row.get("task"):
            raise BenchBundleError("every result needs a task name")
        _number(row.get("rounds"), "rounds")
        _number(row.get("cost"), "cost")
        extra = set(row) - set(_RESULT_FIELDS)
        if extra:
            raise BenchBundleError(
                f"result {row['task']!r} carries unpublished field(s) {sorted(extra)}")
    totals = bundle["totals"]
    if totals.get("tasks") != len(results):
        raise BenchBundleError("totals.tasks disagrees with the results")
    core = {k: v for k, v in bundle.items() if k not in ("bundle_id", "generated_at")}
    if bundle["bundle_id"] != _sha16(core):
        raise BenchBundleError(
            "bundle_id does not match the content; the bundle was edited after "
            "it was built")
    hit = scan_credentials(_canon(bundle))
    if hit:
        raise BenchBundleError(f"bundle contains credential-shaped content: {hit!r}")
    return bundle
