"""Per-attempt HTTP facts for panel and Jev calls (#475).

The retry/breaker Champion brief needs an attempt timeline it can replay: for
each call, the HTTP status of every attempt and when that attempt started and
ended. Nothing in the record carried them (`docs/found-in-use.md` row
`audit-traces-not-persisted`, #475 filing `6995705970`); the only time value
was the row's single ``ts``, which is when the result was booked.

This module is **not** a second event stream. It is the collection point the
existing writers read from:

* ``harness/_http.py`` performs every wire attempt, so it calls
  :func:`record_wire_attempt` as each attempt resolves. A transport that does
  not go through it (a hermetic double) simply records no wire attempt.
* The lane that made the call calls :func:`record_call` once with the final
  status and the wall-clock bounds of the call.
* The row writers that already exist -- ``model_result`` in ``panel.py`` and
  ``jev_eval`` in ``jev_policy.py`` -- call :func:`take_call` and put the
  result on the row they were already writing. No new ledger event, table,
  file or reader is created.

Everything here is inert until a lane opens a call: with no active call the
recorder neither reads the clock nor keeps state, so a run that does not ask
for attempt facts behaves exactly as before.

Landed rows stay readable. :func:`timeline` returns ``[]`` for a row written
before this module existed and says so through :func:`has_timeline`, so a
reader never has to special-case old JSONL.
"""
from __future__ import annotations

import time
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

#: Field on a result row carrying the per-attempt timeline.
ATTEMPTS_FIELD = "attempts"
#: Field on a result row carrying the final HTTP status of the call.
HTTP_STATUS_FIELD = "http_status"

_WIRE: ContextVar[Optional[List[Dict[str, Any]]]] = ContextVar(
    "harness_wire_attempts", default=None)
_CALL: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "harness_call_attempts", default=None)


def _iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def active() -> bool:
    """True when a lane has opened a call on this thread."""
    return _WIRE.get() is not None or _CALL.get() is not None


def reset_wire() -> None:
    """Start a fresh wire-attempt list for the call about to be made."""
    _WIRE.set([])


def record_wire_attempt(*, http_status: Optional[int] = None,
                        started_at: Optional[float] = None,
                        elapsed_s: Optional[float] = None,
                        outcome: str = "response",
                        retry_reason: Optional[str] = None,
                        retry_delay_s: Optional[float] = None) -> None:
    """Record one wire attempt. No-op when no lane opened a call.

    ``started_at``/``elapsed_s`` come from the transport's own monotonic
    measurement; the wall clock is read here, once per attempt, only while a
    call is active.
    """
    wire = _WIRE.get()
    if wire is None:
        return
    ended = time.time()
    start_wall = ended - float(elapsed_s) if elapsed_s is not None else ended
    attempt = {
        "attempt": len(wire) + 1,
        "http_status": http_status,
        "outcome": outcome,
        "started_at": _iso(start_wall),
        "ended_at": _iso(ended),
    }
    if elapsed_s is not None:
        attempt["duration_ms"] = int(round(float(elapsed_s) * 1000))
    if retry_reason:
        attempt["retry_reason"] = retry_reason
    if retry_delay_s is not None:
        attempt["retry_delay_s"] = round(float(retry_delay_s), 3)
    wire.append(attempt)


def note_retry(*, retry_reason: Optional[str],
               retry_delay_s: Optional[float]) -> None:
    """Annotate the attempt that is about to be retried. No-op when idle."""
    wire = _WIRE.get()
    if not wire:
        return
    attempt = wire[-1]
    if retry_reason:
        attempt["retry_reason"] = retry_reason
    if retry_delay_s is not None:
        attempt["retry_delay_s"] = round(float(retry_delay_s), 3)


def record_call(*, http_status: Optional[int], started_at: float,
                ended_at: Optional[float] = None,
                model: Optional[str] = None) -> None:
    """Close the call the lane just made, keeping its wire attempts."""
    wire = _WIRE.get() or []
    if not wire:
        # A transport that does not go through ``_http`` (a double) still made
        # exactly one attempt: the call itself.
        wire = [{
            "attempt": 1,
            "http_status": http_status,
            "outcome": "response" if http_status else "error",
            "started_at": _iso(started_at),
            "ended_at": _iso(ended_at if ended_at is not None else time.time()),
        }]
    _CALL.set({
        HTTP_STATUS_FIELD: http_status,
        "attempts": wire,
        "attempt_started_at": wire[0]["started_at"],
        "attempt_ended_at": wire[-1]["ended_at"],
        "attempt_count": len(wire),
        "attempt_model": model,
    })


def take_call() -> Optional[Dict[str, Any]]:
    """Return the closed call's facts once, then forget them."""
    call = _CALL.get()
    _CALL.set(None)
    _WIRE.set(None)
    return call


def row_fields(call: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The subset of a closed call that belongs on a result row."""
    if not call:
        return {}
    return {
        HTTP_STATUS_FIELD: call.get(HTTP_STATUS_FIELD),
        ATTEMPTS_FIELD: list(call.get("attempts") or []),
        "attempt_started_at": call.get("attempt_started_at"),
        "attempt_ended_at": call.get("attempt_ended_at"),
    }


def timeline(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Read a row's attempt timeline; ``[]`` for a pre-#475 row."""
    attempts = row.get(ATTEMPTS_FIELD) if isinstance(row, dict) else None
    if not isinstance(attempts, list):
        return []
    return [dict(item) for item in attempts if isinstance(item, dict)]


def has_timeline(row: Dict[str, Any]) -> bool:
    """Whether a landed row carries an attempt timeline at all."""
    return isinstance(row.get(ATTEMPTS_FIELD), list)


def recovered_calls(row_or_rows: Any) -> int:
    """Attempts that failed and whose next attempt succeeded.

    The brief's recovered-call rate, read straight off the recorded timeline:
    a failed attempt followed by an attempt with HTTP 200.
    """
    rows = [row_or_rows] if isinstance(row_or_rows, dict) else list(row_or_rows)
    recovered = 0
    for row in rows:
        previous_failed = False
        for attempt in timeline(row):
            status = attempt.get("http_status")
            if previous_failed and status == 200:
                recovered += 1
            previous_failed = status is not None and status != 200
    return recovered
