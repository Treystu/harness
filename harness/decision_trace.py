"""One home for durable decision traces: the ``trace_v1`` event family.

Adopted design (#466 decision record 7002802650, D5-1): every mechanism that
knows a decision fact writes ONE versioned event family into the existing
hash-chained ledger, through one stdlib writer and one reader that spans the
active file and archived segments. Receipts that already exist (``jev_eval``,
panel votes, settlements) are referenced by identity, never duplicated.

What this module owns:

* the ``trace_v1`` envelope (``event_id``, ``kind``, subject/call/attempt/
  causal ids, ``happened_at``/``appended_at``, ``spec_ref``);
* the shared terminal payload (a state that can be ``refused``/``failed`` and a
  path that can name a ``fallback``);
* the writer (``DecisionTrace.record``) and the reader
  (``read_trace_events``) over active + retained segments;
* archive pinning (``pin_window``): a per-brief window manifest that retains the
  segments, their hashes and the ledger positions an audit relied on, with the
  per-producer coverage and known gaps stated rather than implied;
* the campaign event kind, so the campaign emitter's histories stop being
  discarded (#469).

The sink-unavailable clause is deliberately narrow, per the filed constraint:
a caller that declares ``audit_enabled=True`` fails closed when the sink
cannot take the record; ordinary product traffic never defers, and gaps are
exposed by the reader.
"""
import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .ledger import AutonomyLedger

TRACE_VERSION = "trace_v1"

#: Shared terminal vocabulary: a trace that ends must say how it ended.
TERMINAL_STATES = ("completed", "refused", "failed", "interrupted", "skipped")
TERMINAL_PATHS = ("primary", "fallback", "local_gate", "none")

#: Envelope keys, in one place: the reader and the window manifest both rely
#: on exact names, and the design says field sets and join keys are not
#: negotiable.
ENVELOPE_KEYS = (
    "event_id",
    "kind",
    "trace_version",
    "subject_id",
    "call_id",
    "attempt_id",
    "causal_id",
    "happened_at",
    "appended_at",
    "spec_ref",
)

CAMPAIGN_EVENT = "campaign.event"


class TraceError(Exception):
    """A trace record or window manifest that cannot be written faithfully."""


class TraceSinkUnavailable(TraceError):
    """An audit-enabled entry point could not persist its record."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def envelope(kind: str, *, subject_id=None, call_id=None, attempt_id=None,
             causal_id=None, spec_ref=None, happened_at=None,
             event_id=None) -> Dict[str, Any]:
    """Build the ``trace_v1`` envelope every trace event carries."""
    if not isinstance(kind, str) or not kind.strip():
        raise TraceError("a trace event needs a kind")
    return {
        "event_id": event_id or uuid.uuid4().hex,
        "kind": kind.strip(),
        "trace_version": TRACE_VERSION,
        "subject_id": subject_id,
        "call_id": call_id,
        "attempt_id": attempt_id,
        "causal_id": causal_id,
        "happened_at": happened_at or _now(),
        "spec_ref": spec_ref,
    }


def terminal(*, state: str, path: str = "primary", reason=None,
             detail=None) -> Dict[str, Any]:
    """The shared terminal payload; a refusal or failure is a record too."""
    if state not in TERMINAL_STATES:
        raise TraceError(f"unknown terminal state {state!r}")
    if path not in TERMINAL_PATHS:
        raise TraceError(f"unknown terminal path {path!r}")
    payload: Dict[str, Any] = {"state": state, "path": path}
    if reason is not None:
        payload["reason"] = str(reason)
    if detail is not None:
        payload["detail"] = detail
    return payload


class DecisionTrace:
    """The one writer: append ``decision_trace`` rows to the hash-chained ledger."""

    def __init__(self, ledger):
        self.ledger = ledger

    def record(self, kind: str, *, payload: Optional[Dict[str, Any]] = None,
               audit_enabled: bool = False, **envelope_fields) -> Dict[str, Any]:
        """Append one trace event and return the persisted entry.

        ``payload`` carries the per-artifact fields the design files for that
        kind (``terminal`` for a terminal fact). Everything in the envelope is
        computed here so callers cannot forget an identity field.
        """
        event = envelope(kind, **envelope_fields)
        extras = dict(payload or {})
        clash = sorted(set(extras) & set(ENVELOPE_KEYS))
        if clash:
            raise TraceError(f"payload redefines envelope keys: {clash}")
        fields = dict(event)
        fields.update(extras)
        fields["appended_at"] = _now()
        try:
            return self.ledger.append("decision_trace", **fields)
        except Exception as exc:  # noqa: BLE001 - narrowed by the clause below
            if audit_enabled:
                raise TraceSinkUnavailable(
                    f"audit-enabled trace sink unavailable: {exc}") from exc
            return {"kind": kind, "trace_version": TRACE_VERSION,
                    "unrecorded": True, "error": str(exc)}

    def campaign_event(self, event: str, *, campaign="", audit_enabled=False,
                       payload: Optional[Dict[str, Any]] = None,
                       subject_id=None, call_id=None) -> Dict[str, Any]:
        """The #469 producer: retain one campaign event durably.

        The campaign emitter already names its events (``pass_admitted``,
        ``pass_refused``, ``stop``, ``oscillation``, ``info_request``); this
        mirrors them into the trace family with their own payload intact, so a
        campaign history is replayable after the sidecar is gone.
        """
        if not isinstance(event, str) or not event.strip():
            raise TraceError("a campaign event needs a name")
        body = dict(payload or {})
        body.pop("event", None)  # the envelope's kind carries the name
        # A campaign payload may already use an envelope word (the oscillation
        # packet carries its own ``kind``). The envelope stays authoritative and
        # the producer's field is kept under ``campaign_<key>`` rather than
        # dropped: replay must not lose a field the sidecar still has.
        for key in [k for k in body if k in ENVELOPE_KEYS]:
            body["campaign_" + key] = body.pop(key)
        body["campaign"] = campaign
        body["campaign_event"] = event.strip()
        return self.record(CAMPAIGN_EVENT, payload=body,
                           audit_enabled=audit_enabled,
                           subject_id=subject_id or (campaign or None),
                           call_id=call_id,
                           spec_ref=f"campaign.event:{event.strip()}")


def _segment_paths(ledger) -> List[str]:
    segments = getattr(ledger, "segment_paths", None)
    if callable(segments):
        return list(segments())
    path = getattr(ledger, "path", None)
    if path:
        return [path]
    raise TraceError("reader needs a ledger or a path")


def _iter_lines(path: str) -> Iterable[Dict[str, Any]]:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                yield json.loads(text)
            except json.JSONDecodeError as exc:
                raise TraceError(f"{path}:{number} is not JSON ({exc})") from exc


def read_trace_events(source, *, kinds: Optional[Sequence[str]] = None,
                      campaign: Optional[str] = None) -> List[Dict[str, Any]]:
    """Read trace events across the active file and retained segments, oldest first.

    ``source`` is an ``AutonomyLedger`` or a ledger path. Non-trace rows are
    skipped; a trace row from another ``trace_version`` is returned as-is (the
    reader never silently upgrades a record it cannot interpret).
    """
    if isinstance(source, str):
        # The archive belongs to the ledger: resolving a bare path through the
        # ledger's own enumeration keeps one owner of what a segment is, so a
        # rotated ledger's path reads its retained segments too (row 55).
        paths = AutonomyLedger(source).segment_paths()
    elif isinstance(source, (list, tuple)):
        paths = list(source)
    else:
        paths = _segment_paths(source)
    wanted = set(kinds) if kinds else None
    events: List[Dict[str, Any]] = []
    for path in paths:
        for row in _iter_lines(path):
            if row.get("event") != "decision_trace":
                continue
            kind = row.get("kind")
            if wanted is not None and kind not in wanted:
                continue
            if campaign is not None and row.get("campaign") != campaign:
                continue
            events.append(row)
    return events


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pin_window(ledger, *, brief: str, revision: str, selector: str,
               unit_ids: Sequence[str], out_path: str,
               coverage: Optional[Dict[str, Any]] = None,
               gaps: Optional[Sequence[str]] = None,
               kinds: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Retain the evidence set an audit relies on (D3), and write its manifest.

    The manifest names the brief revision, the population selector, the
    selected unit ids, every ledger position and hash for the selected units,
    the segments with their file hashes, and the per-producer coverage and
    known gaps. Deployment cannot repair a past omission, so gaps are written
    down rather than left to be inferred.
    """
    if not brief or not revision or not selector:
        raise TraceError("a window manifest needs brief, revision and selector")
    unit_set = [str(unit) for unit in unit_ids]
    paths = _segment_paths(ledger)
    directory = os.path.dirname(os.path.abspath(out_path)) or "."
    # The active ledger file is mutable: an ordinary append after this return
    # would leave the manifest's hash describing bytes no longer at that path.
    # Seal a byte-for-byte copy of every segment beside the manifest and hash
    # the copy, so the pinned set is reproducible after rotation (row 53).
    snapshot_dir = os.path.join(directory,
                                os.path.basename(out_path) + ".segments")
    segments = []
    for path in paths:
        if not os.path.exists(path):
            continue
        os.makedirs(snapshot_dir, exist_ok=True)
        sealed = os.path.join(snapshot_dir, os.path.basename(path))
        shutil.copyfile(path, sealed)
        segments.append({"path": os.path.basename(path),
                         "snapshot": sealed,
                         "sha256": _sha256_file(sealed),
                         "bytes": os.path.getsize(sealed)})
    rows = read_trace_events(ledger, kinds=kinds)
    selected = [{"event_id": row.get("event_id"), "kind": row.get("kind"),
                 "subject_id": row.get("subject_id"), "seq": row.get("seq"),
                 "hash": row.get("hash"), "happened_at": row.get("happened_at")}
                for row in rows if row.get("subject_id") in set(unit_set)]
    manifest = {
        "window_version": TRACE_VERSION,
        "brief": brief,
        "revision": revision,
        "selector": selector,
        "unit_ids": unit_set,
        "ledger_positions": selected,
        "segments": segments,
        "coverage": dict(coverage or {}),
        "known_gaps": [str(gap) for gap in (gaps or ())],
        "pinned_at": _now(),
    }
    os.makedirs(directory, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return manifest
