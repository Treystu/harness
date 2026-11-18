"""#336: signed, reversible ledger compaction with pinned protection.

The ledger is hash-chained, so deletion is not an option: removing a row breaks
verification and destroys the evidence a receipt points at. This module folds
low-relevance rows of an *old sealed segment* into a signed
``compaction_checkpoint`` whose coverage runs let a verifier cross the omitted
rows when -- and only when -- the signed boundaries match both neighbours.

The rules are the filed decision record (issue #336, record 6971447653):

* newest three sealed segments stay in full; size-only eviction is rejected;
* a row is compactable only when it is unprotected, in an old sealed segment,
  and 30 full days past the later of its timestamp and its qualifying evidence;
* ``jev_eval``, the trust/model/plan/evidence families, the segment,
  checkpoint, citation, classification, migration and restoration records are
  never compactable; one-off and unrecognised event names are protected by
  default;
* exactly three qualifying cases: trusted test/repro provenance (a historical
  phantom ``defer_midtask`` additionally needs a reviewed manifest naming its
  sequence and hash), an explicit superseding replacement, and a successful
  unpinned ``canary_probe``;
* the checkpoint is signed with a key whose material is pinned outside the
  mutable ledger, and undo restores the exact original bytes plus a receipt.

Nothing here decides *when* to compact: :meth:`harness.ledger.AutonomyLedger`
calls :func:`compact_segment` from rotation and from the daily sweep.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .config import CONFIG_DIR
from .errors import HarnessError

#: The policy this module implements. Recorded on every checkpoint so a deep
#: audit can re-run eligibility at the version the decision was made under.
POLICY_VERSION = "ledger-compaction-2026-11-17"

#: Sealed segments kept in full. Older ones are eligible for evaluation.
KEEP_SEGMENTS = 3

#: A compactable row must be this far past its qualifying evidence.
ELIGIBLE_AGE_SECONDS = 30 * 86400

SIGNING_ALGORITHM = "hmac-sha256"
ENVIRONMENT_KEY_VAR = "HARNESS_LEDGER_SIGNING_KEY"

#: Never compactable, whatever the row says about itself.
PROTECTED_EVENTS = frozenset({
    "jev_eval", "trust_gate", "trust_escalation", "model_result",
    "plan_verdict", "complete", "evidence", "readiness", "escalate",
    "segment", "compaction_checkpoint", "citation",
    "classification_manifest", "migration", "restoration",
})

#: Classified for compaction evaluation. Anything else is protected by
#: default: a new event name needs an explicit reviewed classification first.
KNOWN_EVENTS = PROTECTED_EVENTS | frozenset({
    "offer", "defer_midtask", "brief_built", "canary_probe",
    "consent_accept", "consent_defer", "consent_decline",
    "consent_renew_defer", "dispatch", "deny", "cancel",
})

_ELIGIBLE_CASES = ("offer", "defer_midtask", "brief_built", "canary_probe")
_TRUSTED_CALLER_PREFIXES = ("test:", "tests/", "tests\\")


def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_ts(text: Any) -> Optional[float]:
    try:
        moment = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def _utc_iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


# --- signing ---------------------------------------------------------------

def signing_key_path() -> str:
    """Where the signing key lives: outside every mutable ledger directory."""
    override = os.environ.get(ENVIRONMENT_KEY_VAR)
    return override or os.path.join(CONFIG_DIR, "keys", "ledger_signing.key")


def load_or_create_signing_key(path: Optional[str] = None) -> bytes:
    """Read the pinned key, creating it once if this install has none."""
    target = path or signing_key_path()
    try:
        with open(target, "rb") as handle:
            data = handle.read()
    except OSError:
        data = b""
    if len(data) >= 32:
        return data
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    key = os.urandom(32)
    with open(target, "wb") as handle:
        handle.write(key)
    return key


def existing_signing_key(path: Optional[str] = None) -> bytes:
    """The pinned key if this install already has one; never creates one.

    Read paths (verify, chain_status) use this: a missing key means no
    checkpoint coverage can be trusted, so a gap fails closed instead of
    crossing on an unsigned claim.
    """
    try:
        with open(path or signing_key_path(), "rb") as handle:
            data = handle.read()
    except OSError:
        return b""
    return data if len(data) >= 32 else b""


def key_id(key: bytes) -> str:
    return _sha256(b"ledger-signing:" + key)[:16]


#: The signed payload, in one place: the ledger adds its envelope (seq, ts,
#: prev_hash, hash, caller) when it appends this entry, and those are covered
#: by the chain hash, not by this signature.
CHECKPOINT_FIELDS = (
    "schema_version", "ledger_id", "policy_version", "evaluated_at_utc",
    "previous_checkpoint_hash", "segment_name", "archive_ref", "byte_length",
    "segment_sha256", "first_seq", "last_seq", "first_ts", "last_ts",
    "first_prev_hash", "first_entry_hash", "last_entry_hash", "entry_count",
    "kept_count", "dropped_count", "counts_by_event", "counts_by_reason",
    "coverage_runs",
)


def checkpoint_payload(checkpoint: Dict[str, Any]) -> Dict[str, Any]:
    """Everything the signature covers, and nothing the chain already fixes."""
    return {name: checkpoint.get(name) for name in CHECKPOINT_FIELDS}


def sign(key: bytes, payload: Dict[str, Any]) -> str:
    return hmac.new(key, _canon({"payload": payload}).encode("utf-8"),
                    hashlib.sha256).hexdigest()


def verify_checkpoint(checkpoint: Dict[str, Any], key: bytes) -> bool:
    """True only for a checkpoint this key signed over these exact fields."""
    if not isinstance(checkpoint, dict):
        return False
    if checkpoint.get("signature_algorithm") != SIGNING_ALGORITHM:
        return False
    if checkpoint.get("signer_key_id") != key_id(key):
        return False
    supplied = str(checkpoint.get("signature") or "")
    if not supplied:
        return False
    return hmac.compare_digest(sign(key, checkpoint_payload(checkpoint)),
                               supplied)


# --- classification --------------------------------------------------------

def trusted_provenance(entry: Dict[str, Any]) -> bool:
    """A test/repro row states its own provenance; a task ID is not enough."""
    if entry.get("harness_test") is True:
        return True
    caller = str(entry.get("caller") or "")
    return caller.startswith(_TRUSTED_CALLER_PREFIXES)


def _replacement_for(entry: Dict[str, Any],
                     rows: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The retained row that names this entry's sequence and hash as superseded."""
    seq, digest = entry.get("seq"), entry.get("hash")
    for row in rows:
        if row.get("seq") == seq:
            continue
        supersedes = row.get("supersedes")
        if isinstance(supersedes, dict) and supersedes.get("seq") == seq \
                and supersedes.get("hash") == digest:
            return row
    return None


def classify(entry: Dict[str, Any], *, now: float,
             rows: Sequence[Dict[str, Any]] = (),
             manifests: Set[Tuple[int, str]] = frozenset(),
             pins: Set[Tuple[int, str]] = frozenset()) -> Dict[str, Any]:
    """One row's disposition, with a reason a reader can act on."""
    identity = (entry.get("seq"), str(entry.get("hash") or ""))
    event = str(entry.get("event") or "")
    if identity in pins:
        return {"disposition": "keep", "reason": "cited"}
    if event in PROTECTED_EVENTS:
        return {"disposition": "keep", "reason": "protected_class:" + event}
    if event not in KNOWN_EVENTS:
        return {"disposition": "keep", "reason": "unknown_event"}
    if event not in _ELIGIBLE_CASES:
        return {"disposition": "keep", "reason": "no_qualifying_case"}
    stamp = _parse_ts(entry.get("ts"))
    evidence = entry.get("ts")
    replacement = _replacement_for(entry, rows) if event == "brief_built" else None
    if replacement is not None:
        evidence = replacement.get("ts") or evidence
    evidence_stamp = _parse_ts(evidence)
    age_anchor = max(stamp or 0.0, evidence_stamp or 0.0)
    if stamp is None or now - age_anchor < ELIGIBLE_AGE_SECONDS:
        return {"disposition": "keep", "reason": "insufficient_age"}
    if event == "canary_probe":
        if entry.get("canary") is True and entry.get("ok") is True:
            return {"disposition": "drop", "reason": "canary_success"}
        return {"disposition": "keep", "reason": "canary_not_successful"}
    if event == "defer_midtask":
        if identity in manifests:
            return {"disposition": "drop", "reason": "documented_phantom"}
        return {"disposition": "keep", "reason": "unproven_phantom"}
    if replacement is not None:
        return {"disposition": "drop", "reason": "superseded",
                "supporting_seq": replacement.get("seq"),
                "supporting_hash": replacement.get("hash")}
    if trusted_provenance(entry):
        return {"disposition": "drop", "reason": "test_provenance"}
    return {"disposition": "keep", "reason": "no_qualifying_case"}


def _coverage_runs(rows: Sequence[Dict[str, Any]],
                   verdicts: Dict[int, Dict[str, Any]],
                   raw: Dict[int, bytes]) -> List[Dict[str, Any]]:
    """Contiguous runs, covering every original sequence exactly once."""
    runs: List[Dict[str, Any]] = []
    for row in rows:
        seq = row.get("seq")
        verdict = verdicts[seq]
        key = (verdict["disposition"], verdict["reason"])
        if runs and runs[-1]["_key"] == key:
            run = runs[-1]
            run["last_seq"] = seq
            run["terminal_hash"] = row.get("hash")
            run["_chunks"].append(raw[seq])
            continue
        runs.append({
            "_key": key,
            "first_seq": seq, "last_seq": seq,
            "predecessor_hash": row.get("prev_hash"),
            "terminal_hash": row.get("hash"),
            "disposition": verdict["disposition"],
            "reason": verdict["reason"],
            "supporting_record": (
                "seq:{}/hash:{}".format(verdict.get("supporting_seq"),
                                        verdict.get("supporting_hash"))
                if "supporting_seq" in verdict else ""),
            "_chunks": [raw[seq]],
        })
    for run in runs:
        run["byte_length"] = sum(len(chunk) for chunk in run["_chunks"])
        run["byte_sha256"] = _sha256(b"".join(run["_chunks"]))
        run.pop("_chunks")
    return runs


def plan_compaction(rows: Sequence[Dict[str, Any]],
                    raw: Dict[int, bytes], *, now: float,
                    manifests: Set[Tuple[int, str]] = frozenset(),
                    pins: Set[Tuple[int, str]] = frozenset()
                    ) -> Dict[str, Any]:
    """Decide every row of one sealed segment; never drops without a reason."""
    verdicts = {row.get("seq"): classify(row, now=now, rows=rows,
                                         manifests=manifests, pins=pins)
                for row in rows}
    kept = [row for row in rows
            if verdicts[row.get("seq")]["disposition"] == "keep"]
    dropped = [row for row in rows
               if verdicts[row.get("seq")]["disposition"] == "drop"]
    by_event: Dict[str, int] = {}
    by_reason: Dict[str, int] = {}
    for row in rows:
        event = str(row.get("event") or "")
        by_event[event] = by_event.get(event, 0) + 1
        reason = verdicts[row.get("seq")]["reason"]
        by_reason[reason] = by_reason.get(reason, 0) + 1
    return {
        "kept": kept, "dropped": dropped, "verdicts": verdicts,
        "coverage_runs": _coverage_runs(rows, verdicts, raw),
        "counts": {
            "entry_count": len(rows), "kept_count": len(kept),
            "dropped_count": len(dropped),
            "by_event": by_event, "by_reason": by_reason,
            "protected_count": sum(1 for v in verdicts.values()
                                   if v["disposition"] == "keep"),
            "canary_count": sum(1 for row in rows
                                if row.get("canary") is True),
        },
    }


# --- archive + checkpoint --------------------------------------------------

def segment_rows(data: bytes) -> Tuple[List[Dict[str, Any]], Dict[int, bytes]]:
    """Parse a sealed segment into rows plus their exact original line bytes."""
    rows: List[Dict[str, Any]] = []
    raw: Dict[int, bytes] = {}
    for line in data.splitlines():
        text = line.strip()
        if not text:
            continue
        entry = json.loads(text)
        rows.append(entry)
        raw[entry["seq"]] = line + b"\n"
    return rows, raw


def archive_segment(data: bytes, archive_dir: str,
                    segment_name: str) -> Dict[str, Any]:
    """Copy the exact original bytes outside rotation and verify by read-back."""
    os.makedirs(archive_dir, exist_ok=True)
    digest = _sha256(data)
    name = "{}.{}.archive".format(segment_name, digest[:12])
    target = os.path.join(archive_dir, name)
    with open(target, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    with open(target, "rb") as handle:
        restored = handle.read()
    if _sha256(restored) != digest:
        raise HarnessError(
            "compaction archive failed read-back verification: " + target)
    return {"archive_ref": os.path.join(os.path.basename(archive_dir), name),
            "archive_path": target, "byte_length": len(data),
            "segment_sha256": digest}


def build_checkpoint(*, ledger_id: str, segment_name: str,
                     archive: Dict[str, Any], plan: Dict[str, Any],
                     rows: Sequence[Dict[str, Any]], evaluated_at: datetime,
                     previous_checkpoint_hash: Optional[str],
                     key: bytes) -> Dict[str, Any]:
    """The signed checkpoint entry; the live chain continues from it."""
    counts = plan["counts"]
    payload = {
        "schema_version": 1,
        "ledger_id": ledger_id,
        "policy_version": POLICY_VERSION,
        "evaluated_at_utc": _utc_iso(evaluated_at),
        "previous_checkpoint_hash": previous_checkpoint_hash,
        "segment_name": segment_name,
        "archive_ref": archive["archive_ref"],
        "byte_length": archive["byte_length"],
        "segment_sha256": archive["segment_sha256"],
        "first_seq": rows[0]["seq"],
        "last_seq": rows[-1]["seq"],
        "first_ts": rows[0].get("ts"),
        "last_ts": rows[-1].get("ts"),
        "first_prev_hash": rows[0].get("prev_hash"),
        "first_entry_hash": rows[0].get("hash"),
        "last_entry_hash": rows[-1].get("hash"),
        "entry_count": counts["entry_count"],
        "kept_count": counts["kept_count"],
        "dropped_count": counts["dropped_count"],
        "counts_by_event": counts["by_event"],
        "counts_by_reason": counts["by_reason"],
        "coverage_runs": plan["coverage_runs"],
    }
    checkpoint = dict(payload)
    checkpoint["signature_algorithm"] = SIGNING_ALGORITHM
    checkpoint["signer_key_id"] = key_id(key)
    checkpoint["signature"] = sign(key, payload)
    return checkpoint


def compact_segment(path: str, *, archive_dir: str, ledger_id: str,
                    evaluated_at: datetime, previous_checkpoint_hash:
                    Optional[str], key: bytes,
                    append_checkpoint,
                    manifests: Set[Tuple[int, str]] = frozenset(),
                    pins: Set[Tuple[int, str]] = frozenset()) -> Dict[str, Any]:
    """Archive, stage, checkpoint, then switch -- or leave the source intact."""
    with open(path, "rb") as handle:
        data = handle.read()
    if not data.strip():
        raise HarnessError("compaction refused: empty segment " + path)
    rows, raw = segment_rows(data)
    plan = plan_compaction(rows, raw, now=evaluated_at.timestamp(),
                           manifests=manifests, pins=pins)
    if not plan["dropped"]:
        return {"compacted": False, "reason": "no eligible rows",
                "kept_count": len(plan["kept"])}
    archive = archive_segment(data, archive_dir, os.path.basename(path))
    staged = path + ".compact.tmp"
    with open(staged, "wb") as handle:
        for row in plan["kept"]:
            handle.write(raw[row["seq"]])
        handle.flush()
        os.fsync(handle.fileno())
    checkpoint = build_checkpoint(
        ledger_id=ledger_id, segment_name=os.path.basename(path),
        archive=archive, plan=plan, rows=rows, evaluated_at=evaluated_at,
        previous_checkpoint_hash=previous_checkpoint_hash, key=key)
    try:
        written = append_checkpoint(checkpoint)
    except Exception:
        try:
            os.unlink(staged)
        except OSError:
            pass
        raise
    os.replace(staged, path)
    return {"compacted": True, "checkpoint": written,
            "archive_ref": archive["archive_ref"],
            "kept_count": plan["counts"]["kept_count"],
            "dropped_count": plan["counts"]["dropped_count"],
            "coverage_runs": plan["coverage_runs"]}


def restore_segment(archive_path: str, target_path: str,
                    expected_sha256: str) -> Dict[str, Any]:
    """Undo compaction: restore the exact original bytes, verified."""
    with open(archive_path, "rb") as handle:
        data = handle.read()
    digest = _sha256(data)
    if digest != expected_sha256:
        raise HarnessError("restore refused: archive no longer matches "
                           "its checkpoint")
    staged = target_path + ".restore.tmp"
    with open(staged, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(staged, target_path)
    return {"restored": True, "byte_length": len(data),
            "segment_sha256": digest}


def gap_runs(checkpoints: Iterable[Dict[str, Any]], key: bytes
             ) -> List[Dict[str, Any]]:
    """Signed drop runs a verifier may cross, from verified checkpoints only."""
    runs: List[Dict[str, Any]] = []
    for checkpoint in checkpoints:
        if not verify_checkpoint(checkpoint, key):
            continue
        for run in checkpoint.get("coverage_runs") or []:
            if run.get("disposition") == "drop":
                runs.append({
                    "first_seq": run.get("first_seq"),
                    "last_seq": run.get("last_seq"),
                    "predecessor_hash": run.get("predecessor_hash"),
                    "terminal_hash": run.get("terminal_hash"),
                    "checkpoint_seq": checkpoint.get("seq"),
                })
    return runs


def crosses_gap(prev_seq: Optional[int], prev_hash: Optional[str],
                entry: Dict[str, Any], runs: Sequence[Dict[str, Any]]) -> bool:
    """A gap is crossed only when a signed run's boundaries match both sides."""
    seq = entry.get("seq")
    if not isinstance(seq, int) or not isinstance(prev_seq, int):
        return False
    for run in runs:
        if run["first_seq"] == prev_seq + 1 and run["last_seq"] == seq - 1 \
                and run["predecessor_hash"] == prev_hash \
                and run["terminal_hash"] == entry.get("prev_hash"):
            return True
    return False
