"""public_share: the opt-in worldwide model-statistics surface (#407).

The separate public site publishes aggregate model usage, success, cost and
latency figures. This module is the ONE owner of that surface: the consent
record and its future-only revocation, the client's handoff queue, the
sufficient statistics a report carries, the anonymous-aggregation intake
validator, and the publisher that decides what may be shown.

The filed ruling (issue #407, record 6971448099) fixes the semantics:

* **Revocation is future-only.** Turning sharing off stops new submissions
  from this profile and discards unsent work. A report already handed to the
  anonymous intake stays eligible, including when publication happens later.
  The single-operator Proof Bench consent (``site-consent-v1``) does not
  authorize this surface. Withdrawal is serialized with the client's final
  handoff, and current, readable, correctly scoped consent is rechecked at
  handoff and before retrying a queued submission. Re-enabling starts a new
  consent period.
* **Nothing attributable leaves the machine.** A report carries protocol and
  metric versions, the consent surface and version, an opaque consent-period
  digest, the closed UTC month, an allowlisted public model id, a blinded
  commitment, secret shares of the sufficient statistics, and a proof bound to
  the round. Raw rows, ledger tips, precise consent timestamps, credentials,
  tokens, keys, paths and free text never go on the wire; extra fields are
  rejected and the serialized payload is secret-scanned.
* **The client cannot be trusted to be unique.** Distinct operators are
  established by an issuer voucher over a model-and-round-scoped derived
  token: one credential yields one token per model and round, so retries count
  once and ten uploads from one credential never lift nine operators over the
  floor.
* **Publication floor.** Ten distinct verified operators per model, month and
  metric, each with an eligible observation for that metric. A canary-only
  installation contributes zero. Undefined denominators are suppressed, and a
  companion total that would let a reader recover a suppressed cell by
  subtraction is suppressed too. Figures are computed from cohort totals, are
  published once after the round closes, and each names its cohort receipt.

Trust posture, stated rather than implied: a proof over private local evidence
establishes consistency with that evidence -- not that the operator reported
every task, and not that an outside provider delivered the recorded outcome.
No finite cohort protects an exact sum against an observer who knows every
other input.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .errors import HarnessError
from .ledger_canary import evidence_rows

PROTOCOL = "public-share-v1"
CONSENT_SCHEMA = "public-share-consent-v1"
CONSENT_SURFACE = "worldwide-model-site"
CONSENT_VERSION = 1
METRIC_VERSION = 1
FORMULA_VERSION = 1
FIGURE_SCHEMA = "public-figure-v1"

# Publication floor: distinct verified operators per model, month and metric.
PUBLICATION_FLOOR = 10

# Every report is split into this many shares; all of them are needed to open
# a value, so no single holder of a share can read a contributor's numbers.
SHARE_COUNT = 3

# The exact disclosure the operator accepts. Pinned in
# tests/test_docs_contracts.py and quoted verbatim in docs/worldwide-models.md.
DISCLOSURE = (
    "I choose to share aggregate model usage, success, cost, and latency "
    "statistics with the public worldwide model site. My raw ledger stays "
    "private. The site publishes figures only for qualifying groups. I can "
    "turn sharing off at any time. Turning it off discards unsent reports and "
    "stops new submissions from this profile. A report already sent may still "
    "be counted, even if its group has not yet been published. Previously "
    "contributed values cannot be withdrawn from a group, and previously "
    "published figures remain available."
)

# Sufficient statistics: integer counts, attributed cost in micro-USD, summed
# latency in milliseconds. Rates and means are computed from cohort totals.
STAT_FIELDS = ("calls", "tasks", "successes", "cost_micro_usd", "latency_ms",
               "timed_observations")
STAT_BOUNDS = {"calls": 10 ** 9, "tasks": 10 ** 9, "successes": 10 ** 9,
               "cost_micro_usd": 10 ** 15, "latency_ms": 10 ** 12,
               "timed_observations": 10 ** 9}

NO_DATA_TEXT = "No verified data"

CONSENT_FILENAME = "public-share-consent.json"
QUEUE_DIRNAME = "public-share-queue"

# The rung of the ladder is not part of this surface: an unknown public model
# is refused before anything is built.
_TOP_KEYS = frozenset({"protocol", "metric_version", "round", "model",
                       "commitment", "shares", "proof", "eligibility"})
_PROOF_KEYS = frozenset({"round", "model", "consent_surface", "consent_version",
                         "consent_period", "chain_verified", "coverage_rows",
                         "stats_digest", "evidence_digest"})
_SHARE_KEYS = frozenset({"x", "v"})

# The allowlists above are exact at every level -- top level, proof, every
# share, the eligibility block -- so a prohibited field (a raw row, a ledger
# tip, a consent timestamp, a path, a credential) has no place to sit. Nested
# additions are refused by the same exact-key checks, not by a name filter.

_SECRET_PATTERNS = (
    re.compile(r"sk-or-v1-[0-9a-zA-Z]{16,}"),
    re.compile(r"apikey_[0-9a-zA-Z]{8,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)

_ROUND_RE = re.compile(r"^\d{4}-\d{2}$")
_HEX_RE = re.compile(r"^[0-9a-f]+$")

# 2**127 - 1 (Mersenne prime): share arithmetic is exact and bounded well
# above the largest statistic a single report may carry.
PRIME = (1 << 127) - 1

_LOCKS: Dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)


def _digest(*parts: Any) -> str:
    return hashlib.sha256(_canon(list(parts)).encode("utf-8")).hexdigest()


def _hex16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _finite(value: Any) -> Optional[float]:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    if amount != amount or amount in (float("inf"), float("-inf")):
        return None
    return amount


def _allowed_models() -> frozenset:
    """The public model allowlist owns model identity, not the payload.

    Resolved from the routing table's tier map, so a model the harness cannot
    route to is never a public roster row.
    """
    from .routing_table import TIER_MODELS

    return frozenset(str(model) for models in TIER_MODELS.values()
                     for model in models)


# --------------------------------------------------------------------------
# consent: the record, the policy, and the future-only revocation
# --------------------------------------------------------------------------

def make_consent(*, accepted_at: Optional[str] = None,
                 period: Optional[str] = None) -> Dict[str, Any]:
    """A consent record for this surface: readable, scoped, and dated.

    ``period`` is a fresh opaque id, so re-enabling after a withdrawal starts
    a new consent period instead of silently extending the old one.
    """
    return {
        "schema": CONSENT_SCHEMA,
        "surface": CONSENT_SURFACE,
        "version": CONSENT_VERSION,
        "accepted_at": str(accepted_at or _utc_now_iso()),
        "period": str(period or secrets.token_hex(16)),
        "enabled": True,
        "disclosure": DISCLOSURE,
    }


def load_consent(path: str) -> Optional[Dict[str, Any]]:
    """Read a consent record; ``None`` when there is no readable one."""
    try:
        with open(path, encoding="utf-8-sig") as handle:
            record = json.load(handle)
    except OSError:
        return None
    except ValueError:
        return {"schema": "", "enabled": None, "malformed": True}
    return record if isinstance(record, dict) else {"malformed": True}


def policy_for(consent: Any) -> Dict[str, Any]:
    """Whether sharing may proceed, and why not when it may not.

    Fail-closed: a missing, malformed, revoked or wrongly-scoped consent
    record never authorizes a handoff, and the reason names which one it was.
    """
    if not isinstance(consent, dict):
        return {"share": False, "reason": "no consent record", "period": None}
    if consent.get("schema") != CONSENT_SCHEMA:
        return {"share": False, "reason": "malformed consent record",
                "period": None}
    if consent.get("surface") != CONSENT_SURFACE:
        return {"share": False, "reason": "consent is for another surface",
                "period": None}
    if consent.get("version") != CONSENT_VERSION:
        return {"share": False,
                "reason": "consent is for another disclosure version",
                "period": None}
    if consent.get("enabled") is not True:
        return {"share": False, "reason": "sharing is turned off",
                "period": None}
    period = str(consent.get("period") or "").strip()
    if not period:
        return {"share": False, "reason": "consent has no period",
                "period": None}
    return {"share": True, "reason": "sharing is on", "period": period}


class ShareProfile:
    """One operator profile: its consent, its queue, and its handoff.

    Withdrawal and handoff take the same in-process lock, so a report is
    either handed off under the consent that was current when the lock was
    taken, or dropped because that consent is gone by the time it is
    rechecked. Nothing survives a withdrawal in the queue.
    """

    def __init__(self, directory: str, *,
                 transport: Optional[Callable[[Dict[str, Any]], Any]] = None,
                 issuer: Optional["EligibilityIssuer"] = None,
                 credential: Optional[str] = None):
        self.directory = directory
        self.transport = transport
        self.issuer = issuer
        self.credential = credential

    @property
    def consent_path(self) -> str:
        return os.path.join(self.directory, CONSENT_FILENAME)

    @property
    def queue_dir(self) -> str:
        return os.path.join(self.directory, QUEUE_DIRNAME)

    def _lock(self) -> threading.Lock:
        key = os.path.realpath(self.directory)
        with _LOCKS_GUARD:
            lock = _LOCKS.get(key)
            if lock is None:
                lock = threading.Lock()
                _LOCKS[key] = lock
            return lock

    def consent(self) -> Optional[Dict[str, Any]]:
        return load_consent(self.consent_path)

    def policy(self) -> Dict[str, Any]:
        return policy_for(self.consent())

    def _write_consent(self, record: Dict[str, Any]) -> None:
        os.makedirs(self.directory, exist_ok=True)
        tmp = self.consent_path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(_canon(record))
        os.replace(tmp, self.consent_path)

    def enable(self, *, accepted_at: Optional[str] = None) -> Dict[str, Any]:
        """Turn sharing on: always a new consent period."""
        with self._lock():
            record = make_consent(accepted_at=accepted_at)
            self._write_consent(record)
        return record

    def disable(self, *, withdrawn_at: Optional[str] = None) -> Dict[str, Any]:
        """Turn sharing off: future-only, and unsent work is discarded."""
        with self._lock():
            record = self.consent() or {}
            if not isinstance(record, dict):
                record = {}
            record.update({
                "schema": CONSENT_SCHEMA, "surface": CONSENT_SURFACE,
                "version": CONSENT_VERSION, "enabled": False,
                "withdrawn_at": str(withdrawn_at or _utc_now_iso()),
            })
            self._write_consent(record)
            self._clear_queue()
        return record

    def _queue_paths(self) -> List[str]:
        try:
            names = sorted(os.listdir(self.queue_dir))
        except OSError:
            return []
        return [os.path.join(self.queue_dir, name) for name in names
                if name.endswith(".json")]

    def _clear_queue(self) -> int:
        dropped = 0
        for path in self._queue_paths():
            try:
                os.unlink(path)
                dropped += 1
            except OSError:
                continue
        return dropped

    def pending(self) -> List[Dict[str, Any]]:
        reports = []
        for path in self._queue_paths():
            try:
                with open(path, encoding="utf-8") as handle:
                    report = json.load(handle)
            except (OSError, ValueError):
                continue
            if isinstance(report, dict):
                reports.append(report)
        return reports

    def queue(self, report: Dict[str, Any]) -> str:
        """Stage a report for handoff; the name is content-addressed."""
        os.makedirs(self.queue_dir, exist_ok=True)
        path = os.path.join(self.queue_dir,
                            _hex16(_canon(report)) + ".json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(_canon(report))
        os.replace(tmp, path)
        return path

    def build_report(self, ledger: Any, *, model: str,
                     round_id: Optional[str] = None,
                     rng: Optional[Callable[[int], int]] = None) -> Dict[str, Any]:
        return build_report(ledger=ledger, model=model,
                            consent=self.consent(), round_id=round_id,
                            issuer=self.issuer, credential=self.credential,
                            rng=rng)

    def handoff(self, report: Dict[str, Any]) -> Dict[str, Any]:
        """Hand one report off, rechecking consent under the shared lock."""
        if self.transport is None:
            raise HarnessError("public sharing has no transport configured")
        with self._lock():
            policy = self.policy()
            if not policy["share"]:
                self._clear_queue()
                return {"sent": False, "dropped": True,
                        "reason": policy["reason"]}
            period = (report.get("proof") or {}).get("consent_period")
            if period and period != _hex16(policy["period"]):
                return {"sent": False, "dropped": True,
                        "reason": "the consent period changed"}
            self.transport(report)
            self._dequeue(report)
        return {"sent": True, "dropped": False, "reason": "handed off"}

    def _dequeue(self, report: Dict[str, Any]) -> None:
        """Drop the staged copy once the handoff succeeded."""
        path = os.path.join(self.queue_dir, _hex16(_canon(report)) + ".json")
        try:
            os.unlink(path)
        except OSError:
            return

    def submit(self, ledger: Any, *, model: str,
               round_id: Optional[str] = None,
               rng: Optional[Callable[[int], int]] = None) -> Dict[str, Any]:
        """Build, queue, and hand a report off in one acted sequence."""
        report = self.build_report(ledger, model=model, round_id=round_id,
                                   rng=rng)
        self.queue(report)
        return self.handoff(report)

    def upload_pending(self) -> Dict[str, Any]:
        """Retry queued reports; consent is rechecked before every retry."""
        if self.transport is None:
            raise HarnessError("public sharing has no transport configured")
        sent = dropped = retained = 0
        reason = ""
        with self._lock():
            for path in self._queue_paths():
                policy = self.policy()
                if not policy["share"]:
                    dropped += self._clear_queue()
                    reason = policy["reason"]
                    break
                try:
                    with open(path, encoding="utf-8") as handle:
                        report = json.load(handle)
                except (OSError, ValueError):
                    os.unlink(path)
                    dropped += 1
                    continue
                period = (report.get("proof") or {}).get("consent_period")
                if period != _hex16(policy["period"]):
                    # A new consent period is a new authorization. The queued
                    # report cites the old one, so it is discarded rather than
                    # sent on a permission nobody gave it.
                    try:
                        os.unlink(path)
                        dropped += 1
                    except OSError:
                        retained += 1
                    reason = "the consent period changed"
                    continue
                try:
                    self.transport(report)
                except HarnessError as exc:
                    retained += 1
                    reason = str(exc)
                    break
                os.unlink(path)
                sent += 1
        return {"sent": sent, "dropped": dropped, "retained": retained,
                "reason": reason}


# --------------------------------------------------------------------------
# evidence: closed UTC month, allowlisted model, sufficient statistics
# --------------------------------------------------------------------------

def closed_round(now: Optional[datetime] = None) -> str:
    """The most recent closed UTC calendar month, as ``YYYY-MM``."""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    first = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    previous = first.replace(year=first.year - 1, month=12) \
        if first.month == 1 else first.replace(month=first.month - 1)
    return previous.strftime("%Y-%m")


def _row_round(row: Dict[str, Any]) -> Optional[str]:
    text = str(row.get("ts") or "")
    return text[:7] if len(text) >= 7 and text[4] == "-" else None


def rows_for_round(ledger: Any, round_id: str) -> List[Dict[str, Any]]:
    """Canary-filtered rows of one closed month, through the common reader."""
    return [row for row in evidence_rows(ledger)
            if _row_round(row) == round_id]


def derive_stats(rows: List[Dict[str, Any]], model: str) -> Optional[Dict[str, int]]:
    """Sufficient statistics for one model, or ``None`` when evidence is short.

    Calls count only rows that recorded a cost, and tasks count only rows that
    recorded a terminal outcome: a checkpoint count is never a substitute for
    missing cost or outcome evidence. A canary row never reaches this function
    (it is filtered by the reader) and a canary-only installation contributes
    nothing.
    """
    stats = {field: 0 for field in STAT_FIELDS}
    for row in rows:
        if not isinstance(row, dict) or str(row.get("model") or "") != model:
            continue
        event = row.get("event")
        if event == "model_result":
            amount = _finite(row.get("cost"))
            if amount is None or amount < 0:
                continue
            stats["calls"] += 1
            stats["cost_micro_usd"] += int(round(amount * 1_000_000))
        elif event == "complete":
            status = str(row.get("status") or "")
            if status not in ("ok", "failed", "error"):
                continue
            stats["tasks"] += 1
            if status == "ok":
                stats["successes"] += 1
        elif event == "abort":
            # ``ApplyGate.terminal_failure`` records an ``abort`` with a
            # reason, never a ``complete`` with a failed status. Counting only
            # ``complete`` would leave failed apply runs out of the task
            # denominator while their model-call costs stayed in, which makes
            # a failure-heavy operator look faster and more reliable.
            if not str(row.get("reason") or "").strip():
                continue
            stats["tasks"] += 1
        else:
            continue
        latencies = _finite(row.get("latency_ms"))
        if latencies is not None and latencies >= 0:
            stats["latency_ms"] += int(round(latencies))
            stats["timed_observations"] += 1
    if stats["calls"] == 0 or stats["tasks"] == 0:
        return None
    return stats


def _stats_digest(stats: Dict[str, int]) -> str:
    return _digest("stats", FORMULA_VERSION,
                   {field: int(stats.get(field) or 0) for field in STAT_FIELDS})


def _evidence_digest(rows: List[Dict[str, Any]]) -> str:
    return _digest("evidence", sorted(_canon(row) for row in rows))


def commitment_for(stats: Dict[str, int], nonce: int, *,
                   round_id: str, model: str) -> str:
    """A binding commitment over the exact accepted values and the nonce."""
    return _digest("public-share-commit", PROTOCOL, round_id, model,
                   int(nonce), _stats_digest(stats))


# --------------------------------------------------------------------------
# secret sharing: every share is needed to open a value
# --------------------------------------------------------------------------

def _split_scalar(value: int, count: int, rng: Callable[[int], int]) -> List[int]:
    coefficients = [int(value) % PRIME] + [rng(127) % PRIME
                                           for _ in range(count - 1)]
    return [_eval_poly(coefficients, x) for x in range(1, count + 1)]


def _eval_poly(coefficients: List[int], x: int) -> int:
    total = 0
    for coefficient in reversed(coefficients):
        total = (total * x + coefficient) % PRIME
    return total


def _combine(points: List[tuple]) -> int:
    total = 0
    for index, (x_i, y_i) in enumerate(points):
        numerator = denominator = 1
        for other, (x_j, _) in enumerate(points):
            if other == index:
                continue
            numerator = (numerator * (-x_j)) % PRIME
            denominator = (denominator * (x_i - x_j)) % PRIME
        total = (total + y_i * numerator * pow(denominator, PRIME - 2, PRIME)) \
            % PRIME
    return total


def split_payload(stats: Dict[str, int], nonce: int, *,
                  count: int = SHARE_COUNT,
                  rng: Optional[Callable[[int], int]] = None) -> List[Dict[str, Any]]:
    """Secret-share the statistics and the nonce across ``count`` holders."""
    draw = rng or secrets.randbits
    vector = [int(stats[field]) for field in STAT_FIELDS] + [int(nonce)]
    columns = [_split_scalar(value, count, draw) for value in vector]
    return [{"x": x, "v": [columns[c][x - 1] for c in range(len(vector))]}
            for x in range(1, count + 1)]


def open_payload(shares: List[Dict[str, Any]], *, count: int = SHARE_COUNT) -> \
        Dict[str, Any]:
    """Reconstruct the statistics from a complete set of shares."""
    if not isinstance(shares, list) or len(shares) != count:
        raise HarnessError(f"a report needs exactly {count} shares")
    xs = []
    vectors = []
    for share in shares:
        if not isinstance(share, dict):
            raise HarnessError("a share must be an object")
        xs.append(int(share.get("x")))
        vectors.append([int(value) for value in share.get("v") or []])
    if sorted(xs) != list(range(1, count + 1)):
        raise HarnessError(f"share holders must be exactly 1..{count}")
    width = len(STAT_FIELDS) + 1
    if any(len(vector) != width for vector in vectors):
        raise HarnessError("share payload has the wrong width")
    ordered = [vector for _, vector in sorted(zip(xs, vectors))]
    columns = []
    for position in range(width):
        points = [(x, ordered[x - 1][position]) for x in range(1, count + 1)]
        columns.append(_combine(points))
    stats = {field: columns[index] for index, field in enumerate(STAT_FIELDS)}
    nonce = columns[-1]
    return {"stats": stats, "nonce": nonce}


# --------------------------------------------------------------------------
# eligibility: one credential, one token per model and round
# --------------------------------------------------------------------------

class EligibilityIssuer:
    """Vouches only the token a credential actually derives.

    A credential is issued once per profile; the client derives a
    model-and-round-scoped token from it and asks the issuer for a voucher.
    The voucher is an HMAC the client cannot compute, so a fabricated token is
    refused. The issuer re-derives the token from the presented credential,
    model and round and refuses anything else, so arbitrary tokens cannot be
    vouched by copying a report and swapping its eligibility block (#683
    finding 40). The credential is used for that check only, never stored, and
    one credential yields one token per model and round, so a retry cannot
    count twice.
    """

    def __init__(self, key: bytes):
        if not key:
            raise HarnessError("the eligibility issuer needs a key")
        self._key = bytes(key)

    def credential(self, profile_secret: str) -> str:
        if not str(profile_secret or "").strip():
            raise HarnessError("a credential needs a profile secret")
        return hmac.new(self._key, b"credential:" + profile_secret.encode(),
                        hashlib.sha256).hexdigest()

    def voucher(self, token: str, *, credential: str, model: str,
                round_id: str) -> str:
        """Vouch this credential's own model-and-round token, or refuse."""
        for name, value in (("token", token), ("credential", credential),
                            ("model", model), ("round_id", round_id)):
            if not isinstance(value, str) or not value.strip():
                raise HarnessError(f"a voucher needs a non-empty {name}")
        expected = eligibility_token(credential, model=model,
                                     round_id=round_id)
        if not hmac.compare_digest(expected, token):
            raise HarnessError(
                "voucher refused: the token is not derived from this "
                "credential for that model and round")
        return hmac.new(self._key, b"voucher:" + token.encode(),
                        hashlib.sha256).hexdigest()


def eligibility_token(credential: str, *, model: str, round_id: str) -> str:
    """The round-scoped token: unlinkable across rounds, stable within one."""
    return hmac.new(str(credential).encode(),
                    f"{PROTOCOL}:{model}:{round_id}".encode(),
                    hashlib.sha256).hexdigest()


def verify_eligibility(token: Any, voucher: Any, *,
                       verify_key: bytes) -> bool:
    if not isinstance(token, str) or not isinstance(voucher, str):
        return False
    expected = hmac.new(bytes(verify_key), b"voucher:" + token.encode(),
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, voucher)


# --------------------------------------------------------------------------
# the report: what may leave the machine
# --------------------------------------------------------------------------

def _chain_claim(ledger: Any) -> Dict[str, Any]:
    """Verify the local chain before a report may cite it."""
    verify = getattr(ledger, "verify", None)
    entries = getattr(ledger, "entries", None)
    if not callable(verify) or not callable(entries):
        raise HarnessError("a report needs a verifiable ledger")
    ok, first_bad = verify()
    if not ok:
        raise HarnessError(
            f"ledger hash chain FAILED verification at seq {first_bad}; "
            f"refusing to report public statistics")
    count = len(entries())
    if count == 0:
        raise HarnessError("ledger contains no entries; nothing to report")
    return {"verified_claim": True, "entries": count}


def build_report(*, ledger: Any, model: str, consent: Any,
                 round_id: Optional[str] = None,
                 issuer: Optional[EligibilityIssuer] = None,
                 credential: Optional[str] = None,
                 rng: Optional[Callable[[int], int]] = None) -> Dict[str, Any]:
    """Build one report: statistics over one closed month for one model."""
    policy = policy_for(consent)
    if not policy["share"]:
        raise HarnessError(f"sharing refused: {policy['reason']}")
    model = str(model or "")
    if model not in _allowed_models():
        raise HarnessError(f"{model!r} is not an allowlisted public model")
    target_round = round_id or closed_round()
    if not _ROUND_RE.match(target_round):
        raise HarnessError(f"round must be a closed UTC month, got {target_round!r}")
    claim = _chain_claim(ledger)
    rows = rows_for_round(ledger, target_round)
    stats = derive_stats(rows, model)
    if stats is None:
        raise HarnessError(
            f"no eligible evidence for {model} in {target_round}; "
            f"nothing to report")
    nonce = int((rng or secrets.randbits)(127))
    commitment = commitment_for(stats, nonce, round_id=target_round,
                                model=model)
    report = {
        "protocol": PROTOCOL,
        "metric_version": METRIC_VERSION,
        "round": target_round,
        "model": model,
        "commitment": commitment,
        "shares": split_payload(stats, nonce, rng=rng),
        "proof": {
            "round": target_round,
            "model": model,
            "consent_surface": CONSENT_SURFACE,
            "consent_version": CONSENT_VERSION,
            # A digest, never the timestamp: precise consent times fingerprint
            # an operator.
            "consent_period": _hex16(policy["period"]),
            "chain_verified": claim["verified_claim"],
            # A coarse count, never the head hash: a ledger tip fingerprints
            # an operator.
            "coverage_rows": len(rows),
            "stats_digest": _stats_digest(stats),
            "evidence_digest": _evidence_digest(rows),
        },
    }
    if issuer is not None and credential:
        token = eligibility_token(credential, model=model, round_id=target_round)
        report["eligibility"] = {
            "token": token,
            "voucher": issuer.voucher(token, credential=credential,
                                      model=model, round_id=target_round)}
    return report


# --------------------------------------------------------------------------
# intake: the validator every report passes before it can be counted
# --------------------------------------------------------------------------

def _require(condition: bool, message: str) -> None:
    if not condition:
        raise HarnessError(message)


def validate_submission(payload: Any, *, verify_key: bytes) -> Dict[str, Any]:
    """Refuse anything attributable, malformed, forged or out of protocol.

    The allowlist is exact at every level, prohibited field names are refused
    wherever they appear, the round and model must be ones this surface can
    publish, the eligibility voucher must verify, and the serialized payload is
    secret-scanned.
    """
    _require(isinstance(payload, dict), "a report must be an object")
    # Fail on a credential shape before anything else looks at the fields: a
    # report that needed redacting was built wrong, so it is refused, never
    # cleaned.
    serialized = _canon(payload)
    for pattern in _SECRET_PATTERNS:
        _require(pattern.search(serialized) is None,
                 "report carries secret-shaped content")
    keys = set(payload)
    _require(keys == set(_TOP_KEYS),
             "report fields are not the allowlisted set: "
             f"missing={sorted(_TOP_KEYS - keys)} extra={sorted(keys - _TOP_KEYS)}")
    _require(payload.get("protocol") == PROTOCOL,
             f"protocol must be {PROTOCOL!r}")
    _require(payload.get("metric_version") == METRIC_VERSION,
             f"metric_version must be {METRIC_VERSION}")
    round_id = payload.get("round")
    _require(isinstance(round_id, str) and bool(_ROUND_RE.match(round_id)),
             "round must be a closed UTC month")
    model = payload.get("model")
    _require(isinstance(model, str) and model in _allowed_models(),
             "model is not on the public allowlist")
    proof = payload.get("proof")
    _require(isinstance(proof, dict), "proof must be an object")
    _require(set(proof) == set(_PROOF_KEYS),
             "proof fields are not the allowlisted set")
    _require(proof.get("round") == round_id and proof.get("model") == model,
             "proof is not bound to this round and model")
    _require(proof.get("consent_surface") == CONSENT_SURFACE,
             "proof does not cite this consent surface")
    _require(proof.get("consent_version") == CONSENT_VERSION,
             "proof cites another disclosure version")
    _require(proof.get("chain_verified") is True,
             "proof does not claim a verified local chain")
    _require(isinstance(proof.get("coverage_rows"), int)
             and proof["coverage_rows"] >= 1,
             "proof carries no coverage for the round")
    for field in ("consent_period", "stats_digest", "evidence_digest"):
        _require(isinstance(proof.get(field), str) and _HEX_RE.match(proof[field]),
                 f"proof {field} is not a digest")
    commitment = payload.get("commitment")
    _require(isinstance(commitment, str) and _HEX_RE.match(commitment),
             "commitment is not a digest")
    shares = payload.get("shares")
    _require(isinstance(shares, list) and len(shares) == SHARE_COUNT,
             f"a report carries exactly {SHARE_COUNT} shares")
    xs = []
    for share in shares:
        _require(isinstance(share, dict) and set(share) == set(_SHARE_KEYS),
                 "share fields are not the allowlisted set")
        _require(isinstance(share.get("x"), int), "share index must be an int")
        xs.append(share["x"])
        vector = share.get("v")
        _require(isinstance(vector, list) and len(vector) == len(STAT_FIELDS) + 1,
                 "share payload has the wrong width")
        _require(all(isinstance(value, int) and 0 <= value < PRIME
                     for value in vector),
                 "share payload is out of range")
    _require(sorted(xs) == list(range(1, SHARE_COUNT + 1)),
             f"share indices must be exactly 1..{SHARE_COUNT}")
    eligibility = payload.get("eligibility")
    _require(isinstance(eligibility, dict)
             and set(eligibility) == {"token", "voucher"},
             "eligibility must carry exactly a token and a voucher")
    _require(verify_eligibility(eligibility.get("token"),
                                eligibility.get("voucher"),
                                verify_key=verify_key),
             "eligibility voucher does not verify")
    opened = open_payload(shares)
    _require(commitment == commitment_for(opened["stats"], opened["nonce"],
                                          round_id=round_id, model=model),
             "commitment does not open to the submitted shares")
    _require(proof["stats_digest"] == _stats_digest(opened["stats"]),
             "proof does not bind the submitted statistics")
    return {"round": round_id, "model": model, "token": eligibility["token"],
            "commitment": commitment, "stats": opened["stats"]}


# --------------------------------------------------------------------------
# publisher: the floor, the receipts, and the no-data state
# --------------------------------------------------------------------------

def _rate(numerator: int, denominator: int) -> Optional[float]:
    return round(numerator / denominator, 4) if denominator else None


class PublicPublisher:
    """Collects validated reports for a round and publishes the cells.

    During the round a contribution is stored as its round-scoped token and
    its shares -- never an identity, never a plaintext vector joined to one.
    Sealing keeps only cohort records: the round id, model, versions, the
    aggregate commitment root, the verified cohort count, the totals of a
    qualifying cell, its receipt and the site signature.
    """

    def __init__(self, verify_key: bytes, *, site_key: bytes = b"public-site",
                 floor: int = PUBLICATION_FLOOR):
        if not site_key:
            raise HarnessError("the publisher needs a site signing key")
        self._verify_key = bytes(verify_key)
        self._site_key = bytes(site_key)
        self.floor = int(floor)
        self._open: Dict[str, Dict[str, Any]] = {}
        self._sealed: Dict[str, Dict[str, Any]] = {}

    def accept(self, payload: Any) -> Dict[str, Any]:
        """Validate and hold one report; a repeated token counts once."""
        accepted = validate_submission(payload, verify_key=self._verify_key)
        round_id = accepted["round"]
        bucket = self._open.setdefault(round_id, {"tokens": {}, "order": []})
        if accepted["token"] in bucket["tokens"]:
            return {"accepted": False, "duplicate": True,
                    "round": round_id, "model": accepted["model"]}
        bucket["tokens"][accepted["token"]] = {
            "model": accepted["model"],
            "commitment": accepted["commitment"],
            "shares": payload["shares"],
        }
        bucket["order"].append(accepted["token"])
        return {"accepted": True, "duplicate": False, "round": round_id,
                "model": accepted["model"]}

    def _cell(self, contributions: List[Dict[str, Any]]) -> Dict[str, Any]:
        totals = {field: 0 for field in STAT_FIELDS}
        for contribution in contributions:
            opened = open_payload(contribution["shares"])
            for field in STAT_FIELDS:
                totals[field] += opened["stats"][field]
        return totals

    def _figures(self, model: str, totals: Dict[str, int],
                 operators: int) -> Dict[str, Any]:
        """One model's metrics; each needs its own denominator above the floor."""
        definitions = {
            "calls": ("calls", int(totals["calls"]) or None),
            "success_rate": ("tasks", _rate(totals["successes"], totals["tasks"])),
            "cost_per_success_micro_usd": (
                "successes",
                _rate(totals["cost_micro_usd"], totals["successes"])),
            "mean_latency_ms": (
                "timed_observations",
                _rate(totals["latency_ms"], totals["timed_observations"])),
        }
        figures = {}
        for metric, (denominator, value) in definitions.items():
            if operators < self.floor or value is None:
                figures[metric] = {"state": "suppressed", "text": NO_DATA_TEXT,
                                   "reason": "below the publication floor"
                                   if operators < self.floor
                                   else "undefined denominator"}
                continue
            core = {
                "schema": FIGURE_SCHEMA, "state": "published",
                "round": "", "model": model,
                "metric": metric, "value": value,
                "formula_version": FORMULA_VERSION,
                "cohort": {"operators": operators,
                           "denominator": int(totals[denominator]),
                           "totals": {field: int(totals[field])
                                      for field in STAT_FIELDS}},
            }
            figures[metric] = core
        return figures

    def seal(self, round_id: str, *, sealed_at: Optional[str] = None) -> Dict[str, Any]:
        """Close a round and publish the cells that clear the floor.

        Idempotent: sealing the same round again returns the stored result and
        never double-counts a contribution.
        """
        if round_id in self._sealed:
            return self._sealed[round_id]
        bucket = self._open.get(round_id) or {"tokens": {}, "order": []}
        by_model: Dict[str, List[Dict[str, Any]]] = {}
        roots = []
        for token in bucket["order"]:
            contribution = bucket["tokens"][token]
            by_model.setdefault(contribution["model"], []).append(contribution)
            roots.append(contribution["commitment"])
        models = {}
        published = suppressed = 0
        for model in sorted(by_model):
            contributions = by_model[model]
            totals = self._cell(contributions)
            figures = self._figures(model, totals, len(contributions))
            for metric, figure in figures.items():
                if figure["state"] == "suppressed":
                    suppressed += 1
                    continue
                figure["round"] = round_id
                receipt_id = _digest("receipt", FIGURE_SCHEMA, round_id, model,
                                     metric, FORMULA_VERSION)
                parameters = {
                    "receipt_id": receipt_id,
                    "round": round_id,
                    "model": model,
                    "metric": metric,
                    "value": figure["value"],
                    "formula_version": FORMULA_VERSION,
                    "cohort": figure["cohort"],
                    "commitment_root": _digest(sorted(roots)),
                    "proof_digest": _digest("proof", round_id, model, metric),
                }
                figure["receipt"] = dict(
                    parameters,
                    site_signature=hmac.new(
                        self._site_key, _canon(parameters).encode(),
                        hashlib.sha256).hexdigest(),
                )
                published += 1
            models[model] = figures
        sealed = {
            "round": round_id,
            "sealed_at": str(sealed_at or _utc_now_iso()),
            "schema": "public-round-v1",
            "floor": self.floor,
            "metric_version": METRIC_VERSION,
            "published_figures": published,
            "suppressed_figures": suppressed,
            # No totals/breakdowns companion: a published sum would let a
            # reader recover a suppressed cell by subtraction.
            "companions": {"state": "suppressed",
                           "text": NO_DATA_TEXT,
                           "reason": "a companion total would expose a "
                                     "suppressed cell"},
            "models": models,
        }
        self._sealed[round_id] = sealed
        self._open.pop(round_id, None)
        return sealed

    def published(self) -> Dict[str, Any]:
        return dict(self._sealed)


def roster_payload(rounds: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """The site's data file: published figures only, no-data stated plainly."""
    rounds = {round_id: sealed for round_id, sealed in sorted((rounds or {}).items())
              if isinstance(sealed, dict)}
    roster = []
    for round_id, sealed in rounds.items():
        for model, figures in sorted((sealed.get("models") or {}).items()):
            for metric, figure in sorted(figures.items()):
                row = {"round": round_id, "model": model, "metric": metric}
                if figure.get("state") == "suppressed":
                    row.update({"state": "no_data", "text": NO_DATA_TEXT,
                                "reason": figure.get("reason")})
                else:
                    row.update({"state": "published", "value": figure["value"],
                                "receipt": figure["receipt"]})
                roster.append(row)
    return {"schema": "public-roster-v1", "protocol": PROTOCOL,
            "metric_version": METRIC_VERSION, "floor": PUBLICATION_FLOOR,
            "no_data_text": NO_DATA_TEXT, "figures": roster}
