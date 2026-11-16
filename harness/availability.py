"""Availability ledger: remember which backends cannot serve, and why.

Owner of one question: *is this model servable right now?* (#538, #539)

Before this module every lane knew only the failure in front of it. A pair
that had just returned 402 stayed selectable for the next call, the next run
and the next session, so a dry account was rediscovered by spending a call on
it again. Failover across a ladder existed but had nothing to consult, and
the plan lane treated provider exhaustion as terminal by design.

The ledger stores classified provider outcomes per ``(provider, model)``:

* ``route_or_model_restriction`` -- that model on that provider is excluded.
* ``account_funding`` -- that provider's *paid* models are excluded; its free
  models remain selectable, because a dry balance does not disable a $0 route.
* ``rate_limited`` / ``auth_failed`` / ``model_unavailable`` -- excluded for a
  shorter cooldown; a 429 is not a permanent verdict.

An entry expires on a TTL, and a bounded, cost-recorded probe may revalidate
it early (see ``note_probe``/``probe_budget_left``). Nothing here calls a
provider: the caller spends the call and reports the outcome.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Optional

#: How long a provider verdict is trusted before the pair is selectable again.
DEFAULT_TTL_SECONDS = 900.0

#: A rate limit is a much weaker signal than a dry balance.
RATE_LIMIT_TTL_SECONDS = 120.0

#: Bounded revalidation: one probe per pair per TTL window, recorded with cost.
DEFAULT_PROBE_BUDGET = 1

ACCOUNT_FUNDING = "account_funding"
ROUTE_OR_MODEL_RESTRICTION = "route_or_model_restriction"
UNKNOWN_CAUSE = "unknown"

#: Causes that exclude only the named model on its provider.
MODEL_SCOPED_CAUSES = frozenset({ROUTE_OR_MODEL_RESTRICTION})

#: Causes that exclude the provider's paid models but not its free ones.
PROVIDER_SCOPED_CAUSES = frozenset({ACCOUNT_FUNDING})

FIREWORKS_PREFIX = "accounts/fireworks/models/"
META_PREFIX = "muse-"


def provider_of(model: str) -> str:
    """The provider a model id routes through (no brand hardcoding in lanes)."""
    label = str(model or "")
    if label.startswith(FIREWORKS_PREFIX):
        return "fireworks"
    if label.startswith(META_PREFIX):
        return "meta"
    lowered = label.lower()
    if lowered.startswith("groq/"):
        return "groq"
    if lowered.startswith("cerebras/"):
        return "cerebras"
    return "openrouter"


def is_free_model(model: str) -> bool:
    """True when a model is a $0 route that a dry balance does not disable."""
    label = str(model or "")
    return label.endswith(":free") or label == "openrouter/free"


@dataclass
class AvailabilityEntry:
    """One recorded provider verdict for a model."""

    model: str
    provider: str
    kind: str
    cause: str
    reason: str = ""
    http_status: Optional[int] = None
    recorded_at: float = 0.0
    expires_at: float = 0.0
    probes: int = 0
    probe_cost: float = 0.0

    def expired(self, now: float) -> bool:
        return now >= float(self.expires_at or 0.0)

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


class AvailabilityLedger:
    """Persisted map of model -> latest classified availability outcome.

    ``path=None`` keeps the ledger in memory (hermetic tests, and any lane
    that has no config dir). A failed read or write degrades to memory: a
    bookkeeping outage must never stop a request.
    """

    def __init__(self, path: Optional[str] = None, *,
                 ttl: float = DEFAULT_TTL_SECONDS,
                 rate_limit_ttl: float = RATE_LIMIT_TTL_SECONDS,
                 clock=None,
                 probe_budget: int = DEFAULT_PROBE_BUDGET):
        self.path = path
        self.ttl = max(0.0, float(ttl))
        self.rate_limit_ttl = max(0.0, float(rate_limit_ttl))
        self._clock = clock or time.time
        self.probe_budget = max(0, int(probe_budget))
        self._entries: Dict[str, AvailabilityEntry] = {}
        self.load()

    # -- persistence -----------------------------------------------------
    def load(self) -> None:
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            return
        raw = payload.get("entries") if isinstance(payload, dict) else None
        if not isinstance(raw, dict):
            return
        now = self._clock()
        for model, item in raw.items():
            if not isinstance(item, dict):
                continue
            try:
                entry = AvailabilityEntry(
                    model=str(item.get("model") or model),
                    provider=str(item.get("provider") or provider_of(model)),
                    kind=str(item.get("kind") or "unknown"),
                    cause=str(item.get("cause") or UNKNOWN_CAUSE),
                    reason=str(item.get("reason") or "")[:400],
                    http_status=item.get("http_status"),
                    recorded_at=float(item.get("recorded_at") or 0.0),
                    expires_at=float(item.get("expires_at") or 0.0),
                    probes=int(item.get("probes") or 0),
                    probe_cost=float(item.get("probe_cost") or 0.0),
                )
            except (TypeError, ValueError):
                continue
            if not entry.expired(now):
                self._entries[entry.model] = entry

    def save(self) -> None:
        if not self.path:
            return
        payload = {
            "version": 1,
            "entries": {m: e.as_dict() for m, e in self._entries.items()},
        }
        try:
            directory = os.path.dirname(os.path.abspath(self.path))
            os.makedirs(directory, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=directory, prefix=".availability-",
                                       suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        except OSError:
            # Best effort: memory still holds this run's verdicts.
            return

    # -- recording -------------------------------------------------------
    def _ttl_for(self, kind: str) -> float:
        # ``ttl`` is the ledger's window for every verdict; a rate limit may
        # be shorter, never longer (a test or an operator turning the window
        # off must turn ALL of it off, including the rate-limit cooldown).
        if str(kind) == "rate_limited":
            return min(self.rate_limit_ttl, self.ttl)
        return self.ttl

    def record_failure(self, model: str, *, kind: str = "unknown",
                       cause: str = UNKNOWN_CAUSE, reason: str = "",
                       http_status: Optional[int] = None,
                       ttl: Optional[float] = None) -> AvailabilityEntry:
        """Record that ``model`` could not serve, with its classified cause."""
        now = self._clock()
        window = self._ttl_for(kind) if ttl is None else max(0.0, float(ttl))
        prior = self._entries.get(str(model))
        entry = AvailabilityEntry(
            model=str(model),
            provider=provider_of(model),
            kind=str(kind or "unknown"),
            cause=cause if cause in (ACCOUNT_FUNDING, ROUTE_OR_MODEL_RESTRICTION,
                                     UNKNOWN_CAUSE) else UNKNOWN_CAUSE,
            reason=str(reason or "")[:400],
            http_status=http_status,
            recorded_at=now,
            expires_at=now + window,
            probes=int(prior.probes) if prior is not None else 0,
            probe_cost=float(prior.probe_cost) if prior is not None else 0.0,
        )
        self._entries[entry.model] = entry
        self.save()
        return entry

    def record_success(self, model: str) -> None:
        """A servable answer clears the pair's verdict."""
        if self._entries.pop(str(model), None) is not None:
            self.save()

    def note_probe(self, model: str, cost: float = 0.0) -> None:
        """Record one bounded revalidation attempt and its spend."""
        entry = self._entries.get(str(model))
        if entry is None:
            return
        entry.probes += 1
        try:
            entry.probe_cost += max(0.0, float(cost or 0.0))
        except (TypeError, ValueError):
            pass
        self.save()

    # -- queries ---------------------------------------------------------
    def entry(self, model: str) -> Optional[AvailabilityEntry]:
        entry = self._entries.get(str(model))
        if entry is None:
            return None
        if entry.expired(self._clock()):
            self._entries.pop(entry.model, None)
            return None
        return entry

    def probe_budget_left(self, model: str) -> int:
        entry = self.entry(model)
        if entry is None:
            return 0
        return max(0, self.probe_budget - int(entry.probes))

    def is_unservable(self, model: str) -> bool:
        """True when this model's own or provider-wide verdict excludes it."""
        entry = self.entry(model)
        if entry is None:
            return False
        if entry.cause in MODEL_SCOPED_CAUSES:
            return entry.model == str(model)
        if entry.cause in PROVIDER_SCOPED_CAUSES:
            # A dry provider balance disables its paid routes only; its $0
            # routes cost nothing and stay selectable (#539).
            return not is_free_model(model)
        return True

    def is_excluded(self, model: str) -> bool:
        """True when any live verdict in this ledger excludes ``model``."""
        if self.is_unservable(model):
            return True
        provider = provider_of(model)
        paid = not is_free_model(model)
        for entry in list(self._entries.values()):
            if entry.expired(self._clock()):
                continue
            if entry.provider != provider:
                continue
            if entry.cause in PROVIDER_SCOPED_CAUSES and paid:
                return True
        return False

    def order(self, models: Iterable[str], *, prefer_free: bool = True) -> List[str]:
        """Servable models in the caller's order, free routes first (#540).

        Excluded pairs are dropped rather than merely demoted: dispatching to
        a backend already known to be unservable spends a call to relearn it.
        When every model is excluded the caller's order is returned unchanged
        -- a ladder must never become empty because of bookkeeping.
        """
        ordered: List[str] = []
        seen = set()
        for model in models or []:
            key = str(model)
            if key in seen:
                continue
            seen.add(key)
            if not self.is_excluded(key):
                ordered.append(key)
        if not ordered:
            return [str(m) for m in (models or [])]
        if prefer_free:
            ordered.sort(key=lambda m: 0 if is_free_model(m) else 1)
        return ordered

    def live_backends(self, models: Iterable[str]) -> List[Dict[str, object]]:
        """Which configured backends are currently selectable, and why not."""
        report = []
        for model in models or []:
            entry = self.entry(model)
            report.append({
                "model": str(model),
                "provider": provider_of(model),
                "free": is_free_model(model),
                "live": not self.is_excluded(model),
                "reason": (entry.reason if entry is not None else ""),
                "cause": (entry.cause if entry is not None else ""),
            })
        return report

    def snapshot(self) -> Dict[str, object]:
        now = self._clock()
        return {
            m: e.as_dict() for m, e in self._entries.items()
            if not e.expired(now)
        }


# ---------------------------------------------------------------------------
# Process-wide ledger used by the lanes that have no explicit instance.
# ---------------------------------------------------------------------------

_DEFAULT: Optional[AvailabilityLedger] = None


def _default_path() -> Optional[str]:
    """Where verdicts persist between runs (env override wins)."""
    if os.environ.get("HARNESS_AVAILABILITY_OFF", "").strip().lower() in (
            "1", "true", "yes", "on"):
        return None
    explicit = os.environ.get("HARNESS_AVAILABILITY_PATH")
    if explicit:
        return explicit
    try:
        from .paths import get_config_dir

        return os.path.join(get_config_dir(), "availability.json")
    except Exception:
        return None


def default_ledger() -> AvailabilityLedger:
    """One ledger per process so every lane shares this run's verdicts."""
    global _DEFAULT
    if _DEFAULT is None:
        try:
            ttl = float(os.environ.get("HARNESS_AVAILABILITY_TTL",
                                       DEFAULT_TTL_SECONDS))
        except (TypeError, ValueError):
            ttl = DEFAULT_TTL_SECONDS
        _DEFAULT = AvailabilityLedger(_default_path(), ttl=ttl)
    return _DEFAULT


def reset_default_ledger(ledger: Optional[AvailabilityLedger] = None) -> None:
    """Replace/clear the process ledger (tests, and a fresh process run)."""
    global _DEFAULT
    _DEFAULT = ledger


def record_error(model: str, error: Exception, *, kind: str = "unknown") -> None:
    """Record a provider error against ``model`` with its classified cause."""
    cause = getattr(error, "cause", None) or UNKNOWN_CAUSE
    default_ledger().record_failure(
        model, kind=kind, cause=cause, reason=str(error),
        http_status=getattr(error, "http_status", None))


def order_models(models: Iterable[str], *, prefer_free: bool = True) -> List[str]:
    """Availability-ordered ladder (see ``AvailabilityLedger.order``)."""
    return default_ledger().order(models, prefer_free=prefer_free)


def failover_models(
    primary: Iterable[str],
    fallback: Optional[Iterable[str]] = None,
    *,
    prefer_free: bool = False,
) -> List[str]:
    """Servable models from ``fallback`` when ``primary`` is provider-exhausted.

    Used when a single-provider primary pool hits ``account_funding`` while
    another funded direct backend (or $0 route) is configured in ``local_pool``
    (#538, #539). Returns only models not already in ``primary`` and not
    excluded in the default ledger.
    """
    ledger = default_ledger()
    primary_list = [str(m) for m in (primary or []) if m]
    if not any("/" in m for m in primary_list):
        return []
    if primary_list and not all(ledger.is_excluded(m) for m in primary_list):
        return []
    now = ledger._clock()
    if not any(
        not e.expired(now) and e.cause in PROVIDER_SCOPED_CAUSES
        for e in ledger._entries.values()
    ):
        return []
    seen = set(primary_list)
    extras = [
        str(m) for m in (fallback or [])
        if m and str(m) not in seen and not ledger.is_excluded(str(m))
    ]
    if not extras:
        return []
    return ledger.order(extras, prefer_free=prefer_free)

