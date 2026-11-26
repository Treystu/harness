"""#419: local health, backend reachability and request state are reported apart.

The defect: the desktop API answered ``status=ok`` while the configured MCP
backend could not be reached and the run list was empty, so a reader could not
tell "the request stopped" from "its status is unavailable". One healthy
verdict was standing in for three different questions.

This module keeps them separate and makes the inference impossible:

* **local** -- the process serving this response. If the client is reading it,
  this component is ``ok``; it says nothing about anything else.
* **backend** -- the configured MCP backend, probed through the same callable
  the doctor uses (``doctor.check_mcp_stdio``), with the last successful check
  kept and a concise, actionable error when it cannot be reached.
* **requests** -- the durable request state, with the one rule that matters: a
  backend that cannot confirm a request must produce ``unknown`` (or keep the
  terminal state the checkpoint itself recorded), never an invented
  ``completed``, ``failed`` or ``cancelled``.

Nothing here dispatches, resumes or spends. ``report_requests`` is a pure
function over records already read from disk, so reconciling after the backend
returns cannot duplicate work: the same request ids reappear with their
durable state and no provider call is made.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional

from . import __version__
from .run_recovery import redact

BACKEND_OK = "ok"
BACKEND_UNREACHABLE = "unreachable"
BACKEND_UNKNOWN = "unknown"

#: What "the backend" means in this tree: the MCP surface the desktop talks to,
#: spoken over stdio by exactly the command the doctor probes.
BACKEND_ENDPOINT = "stdio: python -m harness.mcp"
BACKEND_NEXT_ACTION = (
    "Check the MCP host and its SSH tunnel, then the MCP configuration, "
    "provider key access and `harness-mcp --help`.")

#: Durable states that the checkpoint itself recorded as final. These are
#: reported as-is when the backend is down -- but never as *backend confirmed*,
#: because a recorded outcome is not a live one.
_TERMINAL_DURABLE = ("completed", "failed")


def _iso(moment: Optional[float]) -> Optional[str]:
    if moment is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(moment)))


def _short(text: Any, limit: int = 300) -> str:
    return " ".join(str(text or "").split())[:limit]


def _scrub(text: Any, secrets: Iterable[str] = ()) -> str:
    """Redact credential shapes *and* the live tokens this process knows."""
    out = str(text or "")
    for secret in secrets:
        if secret:
            out = out.replace(str(secret), "[redacted]")
    return redact(out)


def local_component(identity: Optional[Dict[str, Any]] = None,
                    started_at: Optional[float] = None,
                    now: Optional[float] = None) -> Dict[str, Any]:
    """The one component a served response can honestly claim: itself."""
    moment = time.time() if now is None else float(now)
    started = float(started_at if started_at is not None else moment)
    ident = identity or {}
    return {
        "state": "ok",
        "started_at": _iso(started),
        "started_epoch": started,
        "uptime_seconds": round(max(0.0, moment - started), 3),
        # The version is the package's own; the commit is whatever identity the
        # serving process bound at start, when the tree has one.
        "version": ident.get("version") or __version__,
        "commit": ident.get("commit"),
    }


class BackendMonitor:
    """Reachability of the configured backend, with the last good check kept.

    ``probe`` is the seam: it returns the doctor's check dict (``status``,
    ``detail``, ``next``) or raises. A raising probe is an unreachable backend,
    not a crash of the local server -- that separation is the whole point of
    this module. The result is cached for ``ttl_seconds`` so a status page that
    polls does not spawn a probe per request.
    """

    def __init__(self, probe: Callable[[], Dict[str, Any]], *,
                 clock: Callable[[], float] = time.time,
                 ttl_seconds: float = 30.0,
                 endpoint: str = BACKEND_ENDPOINT,
                 secrets: Iterable[str] = ()):
        self._probe = probe
        self._clock = clock
        self._ttl = float(ttl_seconds)
        self._endpoint = endpoint
        self._secrets = tuple(s for s in secrets if s)
        self._lock = threading.Lock()
        self._last: Optional[Dict[str, Any]] = None
        self._checked_at = 0.0
        self._last_ok_at: Optional[float] = None

    # -- read ---------------------------------------------------------------
    def component(self, force: bool = False) -> Dict[str, Any]:
        with self._lock:
            now = self._clock()
            if (not force and self._last is not None
                    and now - self._checked_at < self._ttl):
                return dict(self._last)
            self._last = self._probe_once(now)
            self._checked_at = now
            return dict(self._last)

    # -- write --------------------------------------------------------------
    def _probe_once(self, now: float) -> Dict[str, Any]:
        try:
            check = self._probe() or {}
        except Exception as exc:  # a probe that raises is an unreachable backend
            return self._failure(now, "{}: {}".format(type(exc).__name__, exc))
        status = str(check.get("status") or "").upper()
        if status == "OK":
            self._last_ok_at = now
            return {
                "state": BACKEND_OK,
                "endpoint": self._endpoint,
                "checked_at": _iso(now),
                "last_ok_at": _iso(now),
                "error": None,
                "detail": _short(_scrub(check.get("detail"), self._secrets)),
                "next_action": "",
            }
        if status == "UNKNOWN":
            return {
                "state": BACKEND_UNKNOWN,
                "endpoint": self._endpoint,
                "checked_at": _iso(now),
                "last_ok_at": _iso(self._last_ok_at),
                "error": None,
                "detail": _short(_scrub(check.get("detail"), self._secrets)),
                "next_action": _short(check.get("next") or ""),
            }
        return {
            "state": BACKEND_UNREACHABLE,
            "endpoint": self._endpoint,
            "checked_at": _iso(now),
            "last_ok_at": _iso(self._last_ok_at),
            "error": _short(_scrub(check.get("detail") or "backend unreachable",
                                   self._secrets)),
            "detail": "",
            "next_action": _short(check.get("next") or BACKEND_NEXT_ACTION),
        }

    def _failure(self, now: float, message: str) -> Dict[str, Any]:
        return {
            "state": BACKEND_UNREACHABLE,
            "endpoint": self._endpoint,
            "checked_at": _iso(now),
            "last_ok_at": _iso(self._last_ok_at),
            "error": _short(_scrub(message, self._secrets)),
            "detail": "",
            "next_action": BACKEND_NEXT_ACTION,
        }


def report_requests(records: Iterable[Dict[str, Any]],
                    backend: Optional[Dict[str, Any]], *,
                    confirmed_ids: Optional[Iterable[str]] = None
                    ) -> List[Dict[str, Any]]:
    """Attach the backend's confidence to each durable request record.

    The rule the issue asks for: with the backend unreachable, a request that
    was not already recorded as final is reported ``unknown``. A final state
    the checkpoint itself wrote stays visible (calling it unknown would be a
    lie in the other direction) but is never marked backend-confirmed.

    ``confirmed_ids`` names the requests a request-specific read actually
    reconciled with the backend. The generic probe proves connectivity only,
    so a reachable backend alone never marks a record confirmed (#35).
    """
    reachable = str((backend or {}).get("state") or "") == BACKEND_OK
    evidenced = {str(item) for item in (confirmed_ids or ()) if str(item)}
    out: List[Dict[str, Any]] = []
    for record in records:
        durable = str(record.get("durable_state")
                      or record.get("state") or "unknown")
        resumable = bool(record.get("resumable"))
        if reachable:
            state = durable
            reason = str(record.get("reason") or "confirmed against the backend")
        elif durable in _TERMINAL_DURABLE:
            state = durable
            reason = ("recorded by the durable checkpoint; the backend could "
                      "not confirm it")
        else:
            state = "unknown"
            reason = ("the backend could not be reached, so this request's "
                      "state is not confirmed")
        moment = record.get("updated_at")
        # Confirmation requires request-specific evidence, which the generic
        # backend probe does not obtain (#35). Keep it false unless such
        # evidence is supplied, while preserving the durable checkpoint state
        # and the independently reported backend reachability.
        identity = str(record.get("request_id") or record.get("id") or "")
        confirmed = bool(identity and identity in evidenced)
        out.append({
            "id": record.get("id"),
            "request_id": record.get("request_id") or record.get("id"),
            "state": state,
            "durable_state": durable,
            "confirmed": confirmed,
            "reason": reason,
            "prompt": record.get("prompt") or "",
            "resumable": resumable,
            "stage": record.get("stage") or "",
            "lane": record.get("lane") or "",
            "last_confirmed_at": moment,
            "last_confirmed_iso": _iso(moment),
            "next_step": record.get("next_step") or "",
        })
    return out


def diagnostics_text(report: Dict[str, Any],
                     secrets: Iterable[str] = ()) -> str:
    """A copyable summary: endpoints, timestamps, states, never a token."""
    local = report.get("local") or {}
    backend = report.get("backend") or {}
    requests = report.get("requests") or []
    lines = ["harness diagnostics",
             "local: {} (started {}; uptime {}s; {} at {})".format(
                 local.get("state"), local.get("started_at"),
                 local.get("uptime_seconds"), local.get("version"),
                 local.get("commit")),
             "backend: {} ({})".format(backend.get("state"),
                                       backend.get("endpoint")),
             "  checked: {}".format(backend.get("checked_at")),
             "  last ok: {}".format(backend.get("last_ok_at") or "never")]
    if backend.get("error"):
        lines.append("  error: {}".format(backend.get("error")))
    if backend.get("next_action"):
        lines.append("  next: {}".format(backend.get("next_action")))
    unknown = sum(1 for item in requests
                  if str(item.get("state")) == "unknown")
    lines.append("requests: {}{}".format(
        len(requests), " ({} unknown)".format(unknown) if unknown else ""))
    for item in requests:
        lines.append("  {}: {} (durable: {}; last confirmed {})".format(
            item.get("id"), item.get("state"), item.get("durable_state"),
            item.get("last_confirmed_iso") or item.get("last_confirmed_at")))
        if item.get("prompt"):
            lines.append("    prompt: {}".format(item.get("prompt")))
        if item.get("next_step"):
            lines.append("    next: {}".format(item.get("next_step")))
    return "\n".join(_scrub(line, secrets) for line in lines)
