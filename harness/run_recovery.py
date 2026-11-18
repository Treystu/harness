"""#418: restart recovery for requests that outlive their process.

The defect: the desktop API answered ``status=ok`` with ``run_count=0`` while a
durable checkpoint still said ``running``, so a long-running request had no
visible handle, state or result to reconnect to. The in-memory run registry
dies with the process; the checkpoint does not.

This module reads the durable state (the per-session lifecycle checkpoint under
``<history>/chat_checkpoints/``) in a **fresh** process and classifies each
request honestly:

* ``running``   -- a checkpoint that claims to be running, discovered by a
                   process that did not start it. It is reported as
                   ``interrupted``: the owner is gone, and saying "running"
                   would be the original lie.
* ``interrupted`` -- stopped mid-flight (running, deferred or cancelled).
* ``completed`` / ``failed`` -- terminal checkpoint statuses.
* ``stale``    -- past the retention window; kept only as a tombstone.
* ``unknown``  -- unreadable, unparsable or invalid state; never guessed at.

Nothing here dispatches, resumes or spends: discovery is read-only, so a
restart can never duplicate a provider call or a side effect. A resumable
record carries its preserved prompt (redacted) so the operator can resume or
start a fresh consent-bound request.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

#: How long a checkpoint stays recoverable. Past this it is reported as
#: ``stale`` -- kept as a tombstone so the prompt is not silently lost, but no
#: longer offered as resumable. Documented in docs/ui-readiness.md.
RECOVERY_RETENTION_SECONDS = 7 * 86400

#: Most records one listing will return (newest first).
RECOVERY_MAX_RECORDS = 50

#: Largest checkpoint this reader will load, matching the lifecycle's own cap
#: behavior in spirit: an oversized blob is invalid state, not a request.
_MAX_CHECKPOINT_BYTES = 4 * 1024 * 1024

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\b\s*[=:]\s*\S+"),
)
_HEX_SECRET = re.compile(r"\b[0-9a-fA-F]{32,}\b")

_TERMINAL = {"complete": "completed", "completed": "completed",
             "failed": "failed", "error": "failed"}
_INTERRUPTED = {"running", "interrupted", "cancelled", "deferred", "pending"}
_REFUSAL_KEYS = ("refused", "refusal", "consent_required", "requires_consent")


def redact(text: str) -> str:
    """Remove credential-shaped material from a preserved prompt."""
    if not isinstance(text, str):
        return ""
    out = text
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub("[redacted]", out)
    out = _HEX_SECRET.sub("[redacted]", out)
    return out


def _read_checkpoint(path: Path) -> Optional[Dict[str, object]]:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        with path.open("rb") as stream:
            raw = stream.read(_MAX_CHECKPOINT_BYTES + 1)
        if len(raw) > _MAX_CHECKPOINT_BYTES:
            return None
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _prompt_of(payload: Dict[str, object]) -> str:
    for key in ("original_request", "prompt"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("prompt", "original_request", "question"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ""


def _refused(payload: Dict[str, object]) -> bool:
    data = payload.get("data")
    if isinstance(data, dict) and any(
            data.get(key) for key in _REFUSAL_KEYS):
        return True
    review = payload.get("review")
    if isinstance(review, dict) and review.get("decision") == "refused":
        return True
    return False


def classify(payload: Optional[Dict[str, object]], *, age_seconds: float
             ) -> Dict[str, object]:
    """The honest state of one checkpoint, with the reason stated."""
    if payload is None:
        return {"state": "unknown", "resumable": False,
                "reason": "the checkpoint could not be read or parsed"}
    if age_seconds > RECOVERY_RETENTION_SECONDS:
        return {
            "state": "stale", "resumable": False,
            "reason": "past the {}-day recovery retention".format(
                RECOVERY_RETENTION_SECONDS // 86400),
        }
    status = str(payload.get("status") or "").strip().lower()
    if status in _TERMINAL:
        return {"state": _TERMINAL[status], "resumable": False,
                "reason": "the checkpoint is terminal ({})".format(status)}
    if status in _INTERRUPTED:
        if _refused(payload):
            return {
                "state": "interrupted", "resumable": False,
                "reason": "the candidate was refused and consent must be "
                          "renewed before dispatch",
            }
        return {
            "state": "interrupted", "resumable": bool(payload.get("stage")),
            "reason": "no live owner: the process that started it is gone",
        }
    return {"state": "unknown", "resumable": False,
            "reason": "the checkpoint status '{}' is not recognised".format(
                status or "(empty)")}


def discover_requests(history_dir=None, *, now: Optional[float] = None
                      ) -> List[Dict[str, object]]:
    """Read durable request state for a listing, newest first. Read-only."""
    from .history import get_default_history_dir

    root = Path(history_dir) if history_dir is not None else Path(
        get_default_history_dir())
    checkpoint_dir = root / "chat_checkpoints"
    if checkpoint_dir.is_symlink() or not checkpoint_dir.is_dir():
        return []
    moment = time.time() if now is None else float(now)
    records: List[Dict[str, object]] = []
    try:
        paths = sorted(checkpoint_dir.glob("*.json"))
    except OSError:
        return []
    for path in paths:
        try:
            updated_at = path.stat().st_mtime
        except OSError:
            continue
        age = max(0.0, moment - updated_at)
        payload = _read_checkpoint(path)
        verdict = classify(payload, age_seconds=age)
        session_id = str((payload or {}).get("session_id") or "")
        request_id = str((payload or {}).get("request_id") or path.stem)
        prompt = _prompt_of(payload or {})
        records.append({
            "id": "rec" + re.sub(r"[^A-Za-z0-9]", "", request_id)[:12],
            "request_id": request_id,
            "session_id": session_id,
            "kind": "recovered",
            "task_id": "recovered/" + re.sub(
                r"[^A-Za-z0-9]", "", request_id)[:12],
            "state": verdict["state"],
            "checkpoint_status": str((payload or {}).get("status") or ""),
            "stage": str((payload or {}).get("stage") or ""),
            "lane": str((payload or {}).get("lane") or ""),
            "prompt": redact(prompt),
            "resumable": bool(verdict["resumable"]),
            "reason": verdict["reason"],
            "next_step": ("resume from the saved checkpoint, or start a fresh "
                          "request from the preserved prompt"
                          if verdict["resumable"] else
                          "start a fresh request; nothing was replayed"),
            "recovered": True,
            "created_at": updated_at,
            "updated_at": updated_at,
            "age_seconds": round(age, 3),
            "retention_days": RECOVERY_RETENTION_SECONDS // 86400,
        })
    records.sort(key=lambda record: record["updated_at"], reverse=True)
    return records[:RECOVERY_MAX_RECORDS]


def recovery_summary(records: List[Dict[str, object]]) -> Dict[str, object]:
    """Counts by state, for a status surface that must not infer success."""
    counts: Dict[str, int] = {}
    for record in records:
        state = str(record.get("state") or "unknown")
        counts[state] = counts.get(state, 0) + 1
    return {"total": len(records), "by_state": counts,
            "retention_days": RECOVERY_RETENTION_SECONDS // 86400}
