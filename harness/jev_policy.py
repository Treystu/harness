"""The single Jev policy owner for all Harness decision lanes (JEV-P1/P3).

The P0 evaluator owns TypeSafe parsing and code-owned mechanics. This module
owns lane policy: when a typed call may dispatch, its bounded spend, one ledger
event, and the structural envelope shared by apply, plan, waist, and agent
lanes. P3 utilization packs live in :mod:`harness.jev_packs` and are imported
here — still ONE policy owner, never a second Jev client.
"""
import atexit
import difflib
import os
import sys
import threading
import weakref
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import (Any, Callable, Dict, Iterable, List, Optional, Sequence,
                    Tuple)

from .errors import HarnessError, ProviderUsageUnknown, ToolCancelled
from .events import submit_with_context
from .provider_errors import ProviderSpendLimitError
from .config import HARD_MAX_COST
from .jev import (ACTIVE_GUARD, ACTIVE_RESERVER, ACTIVE_SITE, BREAKER_COOLDOWN_SECONDS,
                  BREAKER_FAILURE_THRESHOLD, CircuitBreakers,
                  LOCAL_HEURISTIC_MODEL, JevEvaluationResult, JevEvaluator,
                  _digest, jev_cost, triage_question_pack)
from .output import eprint
from .route_pack import (ROUTE_QUERY_SITE)
from .jev_packs import (
    ANSWER_PACK_VERSION,
    CONTEXT_RECALL_PACK_VERSION,
    SIMPLE_STRATEGY_PACK_VERSION,
    AUDIT_DIMENSIONS_SITE,
    HUL_SCOPE_SITE,
    LOG_FACTOR_SITE,
    PHASE_COMPLETION_SITE,
    PROVISION_SITE,
    REQUEST_WORKFLOW_SITE,
    SITE_REACHABILITY_SITE,
    ECONOMICS_ROUTE_SITE,
    REPO_SUMMARY_SITE,
    HOURGLASS_STAGE_DIMENSIONS,
    HOURGLASS_STAGE_PACK_ID,
    HOURGLASS_STAGE_PACK_VERSION,
    HOURGLASS_STAGE_SITE,
    hourglass_stage_question_pack,
    normalize_restart_target,
    stage_judgment_requirement,
    VISION_ASSESSMENT_SITE,
    VISION_ASSESSMENT_MAX_REQUEST_TOKENS,
    VISION_ASSESSMENT_MAX_STATE_QUESTION_TOKENS,
    VISION_ASSESSMENT_PACK_ID,
    VISION_ASSESSMENT_PACK_VERSION,
    VisionAssessmentEnvelope,
    VisionCategoryAssessment,
    answer_question_pack,
    simple_strategy_question_pack,
    escalation_decision_pack,
    completion_question_pack,
    file_relevance_question_pack,
    heuristic_file_relevance,
    heuristic_result_relevance,
    MAX_RESULT_REVIEW,
    RESEARCH_PLAN_SITE,
    research_plan_question_pack,
    result_relevance_question_pack,
    heuristic_requires_iteration,
    heuristic_route,
    request_workflow_question_pack,
    site_reachability_question_pack,
    economics_route_question_pack,
    named_artifact_status,
    normalize_route,
    route_question_pack,
    DEFAULT_VISION_ASSESSMENT_PACK,
    DECISION_CONFIDENCE_THRESHOLD,
    DECISION_DISPOSITION_MARGIN,
    DECISION_PACK_VERSION,
    DECISION_SITE,
    compose_decision_verdict,
    decision_question_pack,
    validate_vision_assessment_answers,
    validate_vision_assessment_pack,
    vision_assessment_preflight,
    vision_assessment_question_pack,
    sanitize_vision_state,
    validate_candidates,
)

# #309: the HUL scope evaluator family has its own owner module. The policy
# class keeps ``evaluate_scope`` and the family's helpers as its
# compatibility surface, and passes itself to the owner so dispatch,
# spend, settlement and ledger semantics stay in this one owner.
from .jev_scope import (evaluate_scope as _evaluate_scope, scope_choice, scope_determination, scope_noul, scope_score, scope_state_facts, scope_text)
from .jev_issue_sort import (evaluate_issue_sort as _evaluate_issue_sort,
                            issue_sort_combo, issue_sort_empty_combo,
                            issue_sort_text)
from .jev_log import (evaluate_log_item as _evaluate_log_item,
                     log_item_text, log_judgment)
from .jev_repo import (evaluate_repo_summary as _evaluate_repo_summary,
                      repo_element_text, repo_judgment)
from .jev_route import (evaluate_model_route as _evaluate_model_route,
                      route_query_text)
from .jev_phase_completion import (
    completion_judgment,
    completion_state_text,
    evaluate_phase_completion as _evaluate_phase_completion,
)
from .jev_audit_dimensions import (
    audit_dimension_text,
    evaluate_audit_dimensions as _evaluate_audit_dimensions,
    resolve_audit_dimension,
)
from .jev_claims import (
    evaluate_claim_support as _evaluate_claim_support,
)

# One input budget per judgment. It was 1024 tokens, and the answer field was
# clipped to 1,800 characters independently of it -- so a complete 4,000-char
# audit or plan was judged as a document that stops mid-sentence (measured
# 2026-10-23: a substantive site audit scored answer_sufficient 0.30 and was
# marked needs_iteration). The judge must see the answer it is judging.
JEV_MAX_INPUT_TOKENS = 4096

# Per-field share of that budget (chars ~ tokens * 3.5 for English and code).
# The answer gets the largest slice because it is the thing being judged.
JEV_REQUEST_MAX_CHARS = 1400
JEV_CONTEXT_MAX_CHARS = 2400
JEV_ANSWER_MAX_CHARS = 7000

# Safety net: a fallback row never lands without a reason. Sites name their
# own; this value only ever appears if a new path forgets to.
UNATTRIBUTED_FALLBACK = "unattributed_fallback"
# Fallback ledger-row bounds: one row each time an identical (site, reason,
# state) fallback count reaches a power of two, and past this many distinct
# states per (site, reason) only power-of-two totals are written.
FALLBACK_DISTINCT_ROW_CAP = 64
FALLBACK_TRACKED_KEYS = 4096
FANOUT_MAX_WORKERS = 4


# Every policy, so unwritten deduped-fallback tails can be flushed at the end
# of a run, a command, a server, or the process (policies are per request).
_LIVE_POLICIES: "weakref.WeakSet" = weakref.WeakSet()


ATEXIT_FLUSH_TIMEOUT_SECONDS = 3.0


def _live_policies() -> tuple:
    """A snapshot of the live policies that concurrent creation cannot break.

    Iterating a WeakSet while another thread adds to it can raise; retry, and
    give up with an empty snapshot rather than ever raising.
    """
    for _ in range(8):
        try:
            return tuple(_LIVE_POLICIES)
        except Exception:
            continue
    return ()


def flush_all_fallbacks() -> int:
    """Best-effort flush of every live policy's unwritten fallback tail.

    Never raises: it runs in ``finally`` blocks and at exit, where an error
    here must not mask the command's own result.
    """
    written = 0
    for policy in _live_policies():
        try:
            written += policy.flush_fallbacks()
        except Exception:
            pass  # a flush must never break shutdown
    return written


def _flush_at_exit() -> None:
    """Flush at interpreter exit, bounded: a stuck ledger cannot hang exit."""
    try:
        worker = threading.Thread(target=flush_all_fallbacks, daemon=True,
                                  name="jev-exit-flush")
        worker.start()
        worker.join(ATEXIT_FLUSH_TIMEOUT_SECONDS)
    except Exception:
        try:
            flush_all_fallbacks()  # no thread available this late
        except Exception:
            pass


atexit.register(_flush_at_exit)


class _Reservation:
    """A reservation acquired lazily, just before a request is dispatched."""

    def __init__(self, policy, site: str, max_input_tokens: int):
        self.policy = policy
        self.site = site
        self.max_input_tokens = max_input_tokens
        self.token = None
        self.acquired = False
        self.reserved = False
        self.used = False
        self._lock = threading.Lock()

    def consume(self) -> bool:
        """True exactly once, and only after a successful reservation."""
        with self._lock:
            if self.reserved and not self.used:
                self.used = True
                return True
            return False

    def acquire(self, estimate: int = 0) -> None:
        """Reserve for the call's bound, or its payload if that is larger.

        Atomic: concurrent callers reserve exactly once, and nobody sees
        ``reserved`` before the token exists.
        """
        with self._lock:
            if not self.acquired:
                self.acquired = True
                self.token = self.policy._reserve(
                    self.site, max(self.max_input_tokens, int(estimate or 0)))
                self.reserved = True


class _Escaped:
    """A HarnessError carried out of a fan-out worker thread."""

    def __init__(self, exc: BaseException):
        self.exc = exc


def _refusal_reason(exc: Exception) -> str:
    """The ``fallback_reason`` for a HarnessError raised around a call."""
    return getattr(exc, "fallback_reason", None) or "preflight_refused"


def _is_power_of_two(value: int) -> bool:
    return value > 0 and value & (value - 1) == 0


def jev_cost_ceiling(max_input_tokens: int = JEV_MAX_INPUT_TOKENS) -> float:
    """Return the worst-case input-token charge for one Jev decision."""
    return jev_cost(max_input_tokens)


def aggregate_structural(
    results: Iterable[Dict[str, Any]], site: str
) -> Optional[Dict[str, Any]]:
    """Aggregate evaluated child envelopes without inventing an empty verdict."""
    values = []
    for result in results:
        structural = result.get("structural") if isinstance(result, dict) else None
        if isinstance(structural, dict):
            values.append(structural)
    if not values:
        return None
    verdicts = {value.get("verdict") for value in values}
    if "fail" in verdicts:
        verdict = "fail"
    elif "defer" in verdicts:
        verdict = "defer"
    elif verdicts == {"pass"}:
        verdict = "pass"
    else:
        verdict = "fail"
    models = {value.get("model") for value in values}
    return {
        "verdict": verdict,
        "confidence": min(float(value.get("confidence") or 0.0)
                           for value in values),
        "supported": min(float(value.get("supported") or 0.0)
                          for value in values),
        "cost": round(sum(float(value.get("cost") or 0.0)
                          for value in values), 6),
        "input_tokens": sum(int(value.get("input_tokens") or 0)
                            for value in values),
        "is_fallback": all(bool(value.get("is_fallback"))
                           for value in values),
        "fallback_reason": ";".join(sorted({str(value.get("fallback_reason"))
                                               for value in values
                                               if value.get("fallback_reason")})) or None,
        "model": next(iter(models)) if len(models) == 1 else "mixed",
        "site": site,
    }


# #309: the audit-dimension resolver lives with its family; kept as a
# module-level name here because callers import it from this module.
_resolve_audit_dimension = resolve_audit_dimension

# --- #660 line 1: typed bands of the shared web-result reviewer ------------
#: An answer at or above this probability is relevant; at or below the next
#: one it is rejected; anything between is uncertain. The middle band is not
#: admission: the caller excludes it, so a reviewer that is unsure can never
#: admit unrelated content by failing to be sure.
RESULT_RELEVANT_AT = 0.70
RESULT_REJECTED_AT = 0.30
RESULT_RELEVANT = "relevant"
RESULT_REJECTED = "rejected"
RESULT_UNCERTAIN = "uncertain"
RESULT_UNREVIEWED = "unreviewed"


def result_verdict(probability: Optional[float]) -> str:
    """Band one noul probability into the reviewer's single typed verdict."""
    if not isinstance(probability, (int, float)) or isinstance(probability, bool):
        return RESULT_UNCERTAIN
    value = float(probability)
    if value >= RESULT_RELEVANT_AT:
        return RESULT_RELEVANT
    if value <= RESULT_REJECTED_AT:
        return RESULT_REJECTED
    return RESULT_UNCERTAIN


class JevPolicy:
    """Coordinate typed Jev calls, spend, ledger evidence, and envelopes."""

    def __init__(self, settings, *, transport=None, governor=None, ledger=None,
                 evaluator=None, breaker_threshold: Optional[int] = None,
                 breaker_cooldown: Optional[float] = None,
                 clock: Optional[Callable[[], float]] = None,
                 request_timeout: float = 120.0,
                 single_attempt: bool = False):
        if settings is None:
            raise HarnessError("Jev policy requires settings")
        self.settings = settings
        self.transport = transport
        self.governor = governor
        self.ledger = ledger
        # #588: a billed call with nowhere to write its receipt must be
        # visible, not silent. One warning per policy, naming the site.
        self._ledger_missing_warned = False
        # (site, reason, state) -> [calls, unwritten]; (site, reason) ->
        # [calls, distinct states, unwritten once capped].
        self._fallback_counts: "OrderedDict[Tuple[str, str, str], List[int]]" = OrderedDict()
        self._fallback_site_counts: Dict[Tuple[str, str], List[int]] = {}
        self._evicted_pending: Dict[Tuple[str, str], int] = {}
        self._state_lock = threading.Lock()
        self._tl = threading.local()
        _LIVE_POLICIES.add(self)
        # The breaker board is shared process-wide on the real transport
        # (policies are built per request); explicit knobs get a private one.
        breakers = None
        if (breaker_threshold is not None or breaker_cooldown is not None
                or clock is not None):
            breakers = CircuitBreakers(
                BREAKER_FAILURE_THRESHOLD if breaker_threshold is None
                else breaker_threshold,
                BREAKER_COOLDOWN_SECONDS if breaker_cooldown is None
                else breaker_cooldown,
                clock or time.monotonic)
        explicitly_disabled = bool(getattr(settings, "jev_disabled", False))
        # No `endpoint=` here: JevEvaluator already reads settings.jev_endpoint
        # itself and falls back to its own default, so passing the attribute
        # through again only restated it -- and typed it as possibly missing.
        self.evaluator = (JevEvaluator(
            api_key=None,
            transport=transport,
            settings=settings,
            breakers=breakers,
            request_timeout=request_timeout,
            single_attempt=single_attempt,
        ) if explicitly_disabled else evaluator or JevEvaluator(
            api_key=getattr(settings, "jev_api_key", None),
            transport=transport,
            settings=settings,
            breakers=breakers,
            request_timeout=request_timeout,
            single_attempt=single_attempt,
        ))

    @property
    def keyed(self) -> bool:
        return bool(self.evaluator.api_key)

    def available(self, site: str,
                  max_input_tokens: int = JEV_MAX_INPUT_TOKENS) -> bool:
        """True when a keyed call at ``site`` could be dispatched right now.

        Checks key presence, that the shared governor could still afford the
        worst-case call (advisory -- the reservation in ``_preflight`` stays
        the enforcing gate), and that the site's breaker is not open. It never
        reserves or dispatches. A half-open breaker reports available without
        consuming its probe slot.
        """
        if not self.keyed:
            return False
        remaining: Any = getattr(self.governor, "remaining", None)
        if callable(remaining):
            try:
                # A governor's remaining() may be duck-typed; float() is the
                # contract check, and the except below is the refusal.
                reserve_left: Any = remaining()
                if float(reserve_left) < jev_cost(max_input_tokens):
                    return False
            except (TypeError, ValueError, HarnessError):
                pass
        breakers = getattr(self.evaluator, "breakers", None)
        return breakers is None or breakers.would_allow(site)

    def _dedupe(self, site: str, reason: str, state_hash: str) -> Tuple[bool, int]:
        """Return ``(write_row, repeat_count)`` for one free fallback/refusal.

        A loop that keeps asking the same unanswerable question must not
        append a ledger row per call. The first occurrence of each
        (site, reason, state) is written, then only counts 2, 4, 8, ...; past
        ``FALLBACK_DISTINCT_ROW_CAP`` distinct states for one (site, reason)
        the same power-of-two rule applies to the site total. A written row's
        ``repeat_count`` is the number of calls it stands for since the last
        row, so summing rows is the true total up to the last write (see
        :meth:`flush_fallbacks` for the unwritten tail).
        """
        key = (site, reason, state_hash)
        with self._state_lock:
            entry = self._fallback_counts.pop(key, None) or [0, 0]
            self._fallback_counts[key] = entry
            while len(self._fallback_counts) > FALLBACK_TRACKED_KEYS:
                old_key, old = self._fallback_counts.popitem(last=False)
                if old[1] > 0:
                    # Never lose calls to eviction: the unwritten tally of the
                    # forgotten state folds into its (site, reason) bucket.
                    self._evicted_pending[old_key[:2]] = (
                        self._evicted_pending.get(old_key[:2], 0) + old[1])
            totals = self._fallback_site_counts.setdefault(key[:2], [0, 0, 0])
            entry[0] += 1
            if entry[0] == 1:
                totals[1] += 1  # a new distinct state for this site/reason
            totals[0] += 1
            if totals[1] <= FALLBACK_DISTINCT_ROW_CAP:
                entry[1] += 1
                write = _is_power_of_two(entry[0])
                repeat = entry[1] if write else 0
                if write:
                    entry[1] = 0
            else:
                totals[2] += 1
                write = _is_power_of_two(totals[0])
                repeat = totals[2] if write else 0
                if write:
                    totals[2] = 0
        return write, max(1, repeat)

    def _dedupe_fallback(self, result: JevEvaluationResult,
                         site: str) -> Tuple[bool, int]:
        """Billed or discarded fallbacks are never deduped: real spend always
        gets its own row."""
        if (not result.is_fallback or result.discarded
                or float(result.cost or 0.0) > 0.0 or result.input_tokens):
            return True, 1
        state_hash = result.state_hash or _digest(
            result.verdict, result.answers, result.reasons)
        return self._dedupe(
            site, result.fallback_reason or UNATTRIBUTED_FALLBACK, state_hash)

    def flush_fallbacks(self) -> int:
        """Write one row per still-unwritten deduped repeat run; return how many.

        Dedupe lags between powers of two. A caller that wants an exact total
        (end of a CLI run, a report) flushes first. Nothing is written (and
        nothing is forgotten) if the ledger's directory is gone, so a flush
        never resurrects a deleted ledger; and if an append fails the
        unwritten tallies are restored before the error propagates.
        """
        path = getattr(self.ledger, "path", None)
        if path and not os.path.isdir(os.path.dirname(path) or "."):
            return 0
        with self._state_lock:
            pending = []
            for (site, reason, _state), entry in self._fallback_counts.items():
                if entry[1] > 0:
                    pending.append((site, reason, entry[1]))
                    entry[1] = 0
            for (site, reason), totals in self._fallback_site_counts.items():
                if totals[2] > 0:
                    pending.append((site, reason, totals[2]))
                    totals[2] = 0
            for (site, reason), count in self._evicted_pending.items():
                pending.append((site, reason, count))
            self._evicted_pending.clear()
        if self.ledger is None:
            return len(pending)
        for index, (site, reason, repeat) in enumerate(pending):
            try:
                self.ledger.append(
                    "jev_eval", site=site, model=self.evaluator.model,
                    verdict="fail", supported=0.0, confidence=0.0,
                    input_tokens=0, output_tokens=0, cost=0.0,
                    is_fallback=True, fallback_reason=reason,
                    repeat_count=repeat, discarded=False, flush=True,
                    note="flush of deduped fallback repeats")
            except BaseException:
                with self._state_lock:
                    for lost_site, lost_reason, lost in pending[index:]:
                        key = (lost_site, lost_reason)
                        self._evicted_pending[key] = (
                            self._evicted_pending.get(key, 0) + lost)
                raise
        return len(pending)

    def fan_out(self, jobs: Sequence[Tuple], *,
                max_workers: int = FANOUT_MAX_WORKERS) -> List[Any]:
        """Run independent typed calls over one state concurrently.

        ``jobs`` is a sequence of ``(site, call)`` or ``(site, call,
        on_failure)``; ``call`` takes no arguments and returns whatever the
        site's ``evaluate_*`` returns. Results come back in ``jobs`` order no
        matter which finishes first. On the threaded (keyed) path each
        question fails closed on its own: a call that raises a plain
        ``Exception`` yields a local fallback (``fallback_reason=
        "fanout_exception"``, one ledger row) and does not disturb its
        siblings. A ``HarnessError`` is a run-level signal and propagates:
        every sibling finishes first, then the first one in job order is
        re-raised; ``on_failure(result, structural)``
        reshapes that pair when a site returns something other than
        ``(result, structural)``. An unkeyed policy, one job, or
        ``max_workers <= 1`` runs inline exactly like sequential calls: a bug
        propagates instead of being swallowed. Either way a reservation the
        failing call still holds is released, never leaked. Concurrency stays
        bounded by ``max_workers`` and every call still reserves/settles
        through the shared governor.
        """
        jobs = list(jobs)
        workers = min(int(max_workers), len(jobs), 8)

        def settle_failure(job, exc: BaseException):
            site = job[0]
            result = JevEvaluationResult(
                "fail", 0.0, 0.0, {},
                ["fan-out call raised {}: {}".format(type(exc).__name__, exc)],
                is_fallback=True, model=self.evaluator.model,
                fallback_reason="fanout_exception")
            try:
                structural = self._account(result, site=site)
            except Exception as ledger_exc:
                eprint("[jev] fan-out failure at {!r} was not ledgered: {}: {}"
                       .format(site, type(ledger_exc).__name__, ledger_exc))
                structural = self._structural(result, site)
            if len(job) > 2 and callable(job[2]):
                return job[2](result, structural)
            return result, structural

        def run(job, *, fail_closed: bool):
            self._tl.token = None
            try:
                return job[1]()
            except BaseException as exc:
                self._release_reservation(exc)
                if isinstance(exc, ToolCancelled) or getattr(exc, "usage_unknown", False):
                    raise
                if not fail_closed or not isinstance(exc, Exception):
                    raise
                if isinstance(exc, HarnessError):
                    # Ruling: a HarnessError (a hard budget "Aborting", a
                    # ledger lock) is a run-level signal, never swallowed. It
                    # is carried out of the worker and re-raised after every
                    # sibling finished and released its reservation.
                    return _Escaped(exc)
                return settle_failure(job, exc)

        if workers <= 1 or not self.keyed:
            return [run(job, fail_closed=False) for job in jobs]
        with ThreadPoolExecutor(max_workers=workers,
                                thread_name_prefix="jev-fanout") as pool:
            futures = [submit_with_context(
                pool, run, job, fail_closed=True) for job in jobs]
            results = [future.result() for future in futures]
        for item in results:
            if isinstance(item, _Escaped):
                raise item.exc  # first HarnessError in job order
        return results

    def _release_reservation(self, error=None) -> None:
        """Release this thread's reservation if a call died holding it."""
        handle = getattr(self._tl, "token", None)
        if handle is not None:
            if isinstance(error, ToolCancelled) or getattr(error, "usage_unknown", False):
                self._settle_cancelled(handle, error)
            elif isinstance(error, ProviderSpendLimitError):
                self._release_after_provider_limit(handle, error)
            else:
                self._release(handle)
        else:
            self._clear_dispatch_state()

    def _release_after_provider_limit(self, reservation, error, *,
                                      task_id=None) -> None:
        """Release liability and preserve a terminal provider failure receipt."""
        site = ACTIVE_SITE.get() or "jev"
        cost = max(0.0, float(getattr(error, "known_cost", 0.0) or 0.0))
        model = getattr(self.evaluator, "model", None) or "jev"
        self._release(reservation)
        from .provider_errors import account_provider_spend_limit
        account_provider_spend_limit(error, self.governor, model)
        if self.ledger is not None and not getattr(error, "ledger_recorded", False):
            should_write = cost > 0.0
            repeat = 1
            if not should_write:
                should_write, repeat = self._dedupe(
                    site, "provider_spend_limit",
                    _digest(task_id, getattr(error, "http_status", None)))
            if should_write:
                metadata = {"result_state": "provider_spend_limit",
                            "error_kind": error.kind,
                            "http_status": getattr(error, "http_status", None),
                            "reason": str(error)}
                if repeat > 1:
                    metadata["repeat_count"] = repeat
                self.ledger.append(
                    "jev_eval", task_id=task_id, site=site, model=model,
                    verdict="fail", supported=0.0, confidence=0.0,
                    answers={}, input_tokens=0, output_tokens=0,
                    cost=cost, is_fallback=False, discarded=cost > 0.0,
                    known_cost_usd=cost, **metadata)
                error.ledger_recorded = True

    def _preflight(self, *, site: str, max_input_tokens: int,
                   eager: bool = False):
        """Reserve one bounded Jev call before its network dispatch.

        An evaluator that supports it (``lazy_reserve``) reserves at the last
        moment instead: after the cache or a single-flight wait could have
        answered for free, and immediately before a request would leave the
        machine. The returned handle is what every site passes to
        ``_account``/``_release``; it holds no token until a request is
        really about to be sent, so a free answer is never refused for budget
        and a billed request is never sent unreserved. ``eager`` reserves
        now (strict one-attempt calls that bypass the cache). Also names ``site``
        for the dispatcher's per-site circuit breaker.
        """
        if not self.keyed:
            return None
        if self.governor is None:
            raise HarnessError(
                "keyed Jev evaluation requires the shared spend governor")
        ACTIVE_SITE.set(site)
        if not eager and getattr(self.evaluator, "lazy_reserve", False):
            handle = _Reservation(self, site, max_input_tokens)
            ACTIVE_RESERVER.set(handle.acquire)
            ACTIVE_GUARD.set(handle.consume)
            self._tl.token = handle
            return handle
        token = self._reserve(site, max_input_tokens)
        self._tl.token = token
        return token

    @staticmethod
    def _sent(reservation) -> bool:
        """Was the call past its reservation (so a failure is post-dispatch)?"""
        return reservation.reserved if isinstance(reservation, _Reservation) else True

    @staticmethod
    def _token_of(reservation):
        return reservation.token if isinstance(reservation, _Reservation) else reservation

    def _release(self, reservation) -> None:
        """Settle a reservation at zero (the call was refused or failed)."""
        # ``_account`` clears the active handle immediately after settlement.
        # An exception raised later (for example while appending the ledger
        # row) must not reconcile that already-settled token a second time.
        if getattr(self._tl, "token", None) is not reservation:
            self._clear_dispatch_state()
            return
        token = self._token_of(reservation)
        if token is not None and self.governor is not None:
            try:
                self.governor.reconcile(token, 0.0)
            except HarnessError:
                pass  # already settled on the call's own path
        self._clear_dispatch_state(reservation)

    def _settle_cancelled(self, reservation, error) -> None:
        """Book known spend and keep unknown post-dispatch liability reserved."""
        if getattr(self._tl, "token", None) is not reservation:
            # The normal accounting path already settled and cleared this
            # handle; a later cancellation (for example, ledger I/O) must not
            # reconcile the same token again.
            self._clear_dispatch_state()
            return
        if getattr(error, "usage_unknown", False):
            # The provider may have received this request, but the usage
            # response was lost when the local worker was stopped. Book any
            # known earlier attempts; leave this dispatch's worst-case
            # reservation outstanding instead of falsely settling it at $0.
            cost = max(0.0, float(getattr(error, "known_cost", 0.0) or 0.0))
            token = self._token_of(reservation)
            model = getattr(self.evaluator, "model", None) or "jev"
            if cost > 0.0 and not getattr(error, "cost_accounted", False):
                try:
                    if self.governor is not None:
                        self.governor.record_actual(cost, model)
                    error.cost_accounted = True
                except HarnessError:
                    book = getattr(self.governor, "record_overrun", None)
                    if callable(book):
                        book(cost, model)
                    error.cost_accounted = True
            from .events import emit
            reserved: Any = (token[1] if isinstance(token, tuple) and len(token) > 1
                             else None)
            if token is not None and self.governor is not None:
                reclassify = getattr(self.governor, "reclassify_unknown", None)
                if callable(reclassify):
                    try:
                        reserved = reclassify(token)
                    except HarnessError:
                        # Preserve the already-held reservation if a custom
                        # governor cannot reclassify it; never release or
                        # duplicate the liability after dispatch.
                        pass
            error.reserved_cost = float(reserved or 0.0)
            error.cost_accounted = True
            phase = (getattr(reservation, "site", None)
                     or (token[0] if isinstance(token, tuple) and token else None))
            emit("provider_usage_unknown", model=model, known_cost=cost,
                 reserved_cost=reserved, phase=phase)
            self._clear_dispatch_state(reservation)
            return
        if getattr(error, "cost_accounted", False):
            self._release(reservation)
            return
        cost = max(0.0, float(getattr(error, "known_cost", 0.0) or 0.0))
        token = self._token_of(reservation)
        model = getattr(self.evaluator, "model", None) or "jev"
        try:
            if token is not None and self.governor is not None:
                self.governor.reconcile(token, cost)
            elif self.governor is not None and cost > 0.0:
                self.governor.record_actual(cost, model)
        except HarnessError:
            book = getattr(self.governor, "record_overrun", None)
            if cost > 0.0 and callable(book):
                book(cost, model)
        finally:
            self._clear_dispatch_state(reservation)
        error.cost_accounted = True

    def _clear_dispatch_state(self, reservation=None) -> None:
        ACTIVE_SITE.set("")
        ACTIVE_RESERVER.set(None)
        ACTIVE_GUARD.set(None)
        if getattr(self._tl, "token", None) is reservation:
            self._tl.token = None

    def _reserve(self, site: str, max_input_tokens: int):
        if self.governor is None:
            raise HarnessError(
                "keyed Jev evaluation requires the shared spend governor")
        label = "jev:" + site
        worst = jev_cost(max_input_tokens)
        reserve = getattr(self.governor, "reserve", None)
        if callable(reserve):
            return reserve(worst, label)
        preflight = getattr(self.governor, "preflight_jev", None)
        if callable(preflight):
            preflight(max_input_tokens, label=label)
            return None
        ceiling = getattr(self.governor, "max_cost", None)
        spent = getattr(self.governor, "spent", 0.0)
        outstanding = getattr(self.governor, "outstanding", 0.0)
        if (ceiling is not None
                and float(spent) + float(outstanding) + worst > float(ceiling)):
            raise HarnessError(
                f"Jev worst-case cost ${worst:.6f} exceeds the remaining budget")
        return None

    def _no_key_reason(self) -> str:
        return ("explicit_disable"
                if getattr(self.evaluator, "explicitly_disabled", False)
                else "missing_key")

    @staticmethod
    def _fallback_reason_of(result: JevEvaluationResult, default: str) -> str:
        """Why a result is being replaced by a local answer; never ``None``."""
        if result.fallback_reason:
            return result.fallback_reason
        return "response_discarded" if result.discarded else default

    @staticmethod
    def _local_from(result: JevEvaluationResult, answers: Dict[str, Any],
                    reasons: Sequence[str], reason: str, *, billed: bool = True,
                    verdict: str = "pass") -> JevEvaluationResult:
        """A local fallback that keeps the live call's real cost and identity.

        A billed call whose answer was discarded stays settled at its real
        cost and is flagged ``discarded`` so the loss is reported, never
        hidden behind a free-looking fallback.
        """
        spent = billed and float(result.cost or 0.0) > 0.0
        return JevEvaluationResult(
            verdict, 0.0, 1.0 if verdict == "pass" else 0.0, answers,
            list(reasons), cost=result.cost if billed else 0.0,
            input_tokens=result.input_tokens if billed else 0,
            output_tokens=result.output_tokens if billed else 0,
            is_fallback=True, model=result.model,
            discarded=bool(result.discarded or spent),
            fallback_reason=reason, state_hash=result.state_hash)

    def _with_reason(self, result: JevEvaluationResult,
                     reason: Optional[str], state: Any = None
                     ) -> JevEvaluationResult:
        """Stamp a closure-built fallback with its reason and billed state.

        ``state`` is the text the site judged; it keys the fallback dedupe so
        two different inputs never collapse into one ledger row.
        """
        cost = float(result.cost or 0.0)
        return replace(
            result, fallback_reason=reason or result.fallback_reason,
            discarded=bool(result.discarded or cost > 0.0),
            state_hash=result.state_hash or (
                None if state is None else _digest(state)))

    def _book_overrun(self, cost: float, result: JevEvaluationResult) -> None:
        """Record spend the governor refused to settle (it is real money)."""
        book = getattr(self.governor, "record_overrun", None)
        if cost > 0.0 and callable(book):  # zero spend is never an overrun
            try:
                book(cost, result.model or "jev")
            except Exception as exc:
                eprint("[jev] overrun of ${:.6f} could not be booked: {}"
                       .format(cost, exc))

    def _structural(self, result: JevEvaluationResult, site: str) -> Dict[str, Any]:
        return {
            "verdict": result.verdict,
            "confidence": result.confidence,
            "supported": result.supported,
            "cost": float(result.cost or 0.0),
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "is_fallback": result.is_fallback,
            "fallback_reason": result.fallback_reason,
            "model": result.model,
            "site": site,
            # DF-JEV-3: a billed call whose answer could not be used. Carried
            # in the structural envelope so a run can total its own losses.
            "discarded": bool(result.discarded),
        }

    def _record_refusal(self, reason: str, *, site: str,
                        task_id: Optional[str] = None,
                        node_id: Optional[str] = None,
                        event_metadata: Optional[Dict[str, Any]] = None,
                        code: str = "preflight_refused"):
        result = JevEvaluationResult(
            "fail", 0.0, 0.0, {}, [reason], cost=0.0,
            input_tokens=0, output_tokens=0, is_fallback=False,
            model=self.evaluator.model,
        )
        structural = self._structural(result, site)
        write_row, repeat = self._dedupe(site, "refusal:" + code, _digest(reason))
        if self.ledger is not None and write_row:
            metadata = dict(event_metadata or {})
            if repeat > 1:
                metadata["repeat_count"] = repeat
            self.ledger.append(
                "jev_refusal", task_id=task_id, node_id=node_id, site=site,
                model=metadata.get("observed_model", result.model),
                reason=reason, reason_code=code, cost=0.0,
                input_tokens=0, is_fallback=False,
                **metadata,
            )
        return result, structural

    def _account(self, result: JevEvaluationResult, *, site: str,
                 task_id: Optional[str] = None,
                 node_id: Optional[str] = None,
                 reservation=None,
                 settlement_cost: Optional[float] = None,
                 event_metadata: Optional[Dict[str, Any]] = None,
                 preserve_event_on_settlement_error: bool = False) -> Dict[str, Any]:
        """Settle live spend and append exactly one hash-chained jev_eval."""
        if result.is_fallback and not result.fallback_reason:
            result = replace(result, fallback_reason=UNATTRIBUTED_FALLBACK)
        cost = (float(result.cost or 0.0) if settlement_cost is None
                else float(settlement_cost))
        settlement_error = None
        token = self._token_of(reservation)
        try:
            # Settle the REAL cost even when the answer was discarded or
            # replaced by a local fallback: a billed call is spend either way.
            if token is not None and self.governor is not None:
                self.governor.reconcile(token, cost)
            elif (self.governor is not None
                  and (not result.is_fallback or cost > 0.0)):
                # A governor without reservations (or a call that was
                # answered without one) still gets one actual settlement.
                self.governor.record_actual(cost, result.model or "jev")
        except Exception as exc:
            if not isinstance(exc, HarnessError):
                raise
            # The provider already billed this call: the money is spent
            # whether or not it fits the ceiling, so it is booked (and flagged
            # as an overrun) and never allowed to vanish. Settlement failure
            # is NOT a reason to throw away an answer that was paid for, so
            # nothing is raised: the result stands and is flagged below.
            self._book_overrun(cost, result)
            settlement_error = "{}: {}".format(type(exc).__name__, exc)
        self._clear_dispatch_state(reservation)
        structural = self._structural(result, site)
        # Mutated in place on purpose: callers read ``result_state`` back out
        # of the dict they passed to learn that settlement failed.
        metadata = event_metadata if event_metadata is not None else {}
        if settlement_error is not None and preserve_event_on_settlement_error:
            metadata["result_state"] = "unassessed"
            metadata["settlement_error"] = settlement_error
        elif settlement_error is not None:
            # Ruling: a parsed answer is honored after an overrun (a paid
            # "fail" still fails, a paid "pass" passes) and the overrun is
            # flagged on the single billed row, in the reasons and in the
            # envelope. Only the budget REFUSAL (nothing sent) hard-stops.
            metadata["settlement_overrun"] = True
            metadata["settlement_error"] = settlement_error
            structural["settlement_overrun"] = True
            if isinstance(result.reasons, list):
                result.reasons.append(
                    "settlement overrun: billed cost exceeded the budget "
                    "ceiling and was booked (" + settlement_error + ")")
        if result.cache_hit:
            metadata["cache_hit"] = True
            metadata["note"] = ("cache hit: identical state/questions served "
                                "locally; no request sent, cost 0")
            structural["cache_hit"] = True
        write_row, repeat = self._dedupe_fallback(result, site)
        if repeat > 1:
            metadata["repeat_count"] = repeat
        unassessed = (settlement_error is not None
                      and preserve_event_on_settlement_error)
        if self.ledger is None and cost > 0.0:
            self._warn_ledger_missing(site, cost)
        if self.ledger is not None and write_row:
            self.ledger.append(
                "jev_eval", task_id=task_id, node_id=node_id, site=site,
                model=metadata.get("observed_model", result.model),
                verdict="fail" if unassessed else result.verdict,
                supported=0.0 if unassessed else result.supported,
                confidence=0.0 if unassessed else result.confidence,
                input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                cost=cost, is_fallback=result.is_fallback,
                fallback_reason=result.fallback_reason,
                discarded=bool(result.discarded),
                **metadata,
            )
        return structural

    def _warn_ledger_missing(self, site: str, cost: float):
        """Say out loud that a paid judgment left no receipt (#588).

        The ledger contract on this path is exactly one ``jev_eval`` per call;
        a composition without a ledger spends the owner's money and writes no
        row. Nothing here invents a ledger path -- the operator is told which
        site lost its receipt and where the composition should have supplied
        one, once per policy so a hot lane cannot flood its log.
        """
        if self._ledger_missing_warned:
            return
        self._ledger_missing_warned = True
        print("[jev] WARNING: billed ${:.8f} at site {} with no ledger; no "
              "jev_eval row was written. Compose with "
              "session.jev_for(settings, ledger=...) or pass --ledger."
              .format(cost, site), file=sys.stderr)

    def evaluate_diff(self, diff: str, instruction: str, file_path: str,
                      *, candidate: Optional[str] = None,
                      site: str = "apply", task_id: Optional[str] = None,
                      node_id: Optional[str] = None,
                      max_input_tokens: int = JEV_MAX_INPUT_TOKENS):
        """Run local mechanics first, then the answerable semantic pack."""
        reservation = None
        try:
            def reserve_for_evaluator(state=None):
                nonlocal reservation
                reservation = self._preflight(
                    site=site, max_input_tokens=max_input_tokens)

            result = self.evaluator.verify_diff_mechanics(
                diff, instruction, file_path, candidate=candidate,
                preflight=reserve_for_evaluator,
            )
            structural = self._account(
                result, site=site, task_id=task_id, node_id=node_id,
                reservation=reservation,
            )
            reservation = None
            return result, structural
        except ProviderUsageUnknown as exc:
            self._settle_cancelled(reservation, exc)
            raise
        except ToolCancelled as exc:
            self._settle_cancelled(reservation, exc)
            raise
        except ProviderSpendLimitError as exc:
            self._release_after_provider_limit(reservation, exc, task_id=task_id)
            raise
        except HarnessError as exc:
            self._release(reservation)
            return self._record_refusal(
                str(exc), code=_refusal_reason(exc), site=site, task_id=task_id, node_id=node_id)

    def evaluate_hourglass_stage(
            self, dimension: str, state: Any, *,
            site: str = HOURGLASS_STAGE_SITE,
            task_id: Optional[str] = None,
            node_id: Optional[str] = None,
            max_input_tokens: int = JEV_MAX_INPUT_TOKENS,
            subject_supplied: bool = True,
            superseded: bool = False):
        """Judge ONE declared Hourglass stage dimension (HV-1).

        Selectable typed integrations, one owner, one contract:

        - ``dimension`` MUST be one of the operator-declared dimensions in
          ``HOURGLASS_STAGE_DIMENSIONS``; an unknown dimension raises rather
          than inventing a question set;
        - every signal is read through the official answer shapes. An
          unkeyed, transport-failed, malformed, or out-of-vocabulary answer
          leaves that signal ``None`` and the whole judgment ``native=False``
          -- a fallback is never promoted to a native signal;
        - ``restart_target`` may only ever yield a DECLARED stage; an
          out-of-vocabulary choice is reported ``None``. Deciding whether
          that recommendation is an allowed transition belongs to code
          (``validate_restart_request``), not to Jev;
        - one preflight reservation, one dispatch, one settlement, one
          metadata-only ledger ``jev_eval`` on every path.

        ``subject_supplied``/``superseded`` are the code-owned facts behind
        HV-1's "avoid redundant calls when no decision is needed". When they
        say no call is required, this returns BEFORE any preflight: no
        reservation, no dispatch, no settlement, and no ``jev_eval`` event,
        because nothing was evaluated -- a ``jev_eval`` for a call that never
        happened would be a false record. The skip is reported in the returned
        envelope instead (``result_state="not_required"``, every signal
        ``None``, ``native=False``), so it can never be mistaken for a
        judgment that passed or failed. Which facts are supplied is Lane 2's
        wiring decision (#119); this owner only reads the pack's verdict.

        ``dispatched`` in the returned envelope is the honest answer to "did
        a Jev call actually leave this machine": only the live path sets it
        true. The unkeyed and pre-dispatch-refusal paths DID require a
        judgment and could not make one -- ``judgment_required`` is true and
        ``result_state`` is ``unavailable`` -- which is a different fact from
        one that was asked and answered.

        Returns ``(result, structural)`` where ``structural`` carries the
        declared signals, the capability/pack identity, and the honest
        native/fallback state.
        """
        questions = hourglass_stage_question_pack(dimension)
        spec = HOURGLASS_STAGE_DIMENSIONS[dimension]
        signals = list(spec["signals"])

        def noul_value(answers, key):
            value = (answers or {}).get(key)
            if isinstance(value, dict) and "noul" in value:
                value = value.get("noul")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None
            value = float(value)
            return value if 0.0 <= value <= 1.0 else None

        def choice_value(answers, key):
            value = (answers or {}).get(key)
            if not isinstance(value, dict):
                return None
            declared = set(questions[key].get("criteria") or {})
            choice = normalize_restart_target(value.get("choice"))
            if choice is None or choice not in declared:
                return None
            confidence = value.get("confidence")
            if (isinstance(confidence, bool)
                    or not isinstance(confidence, (int, float))):
                return None
            return {"target": choice, "confidence": float(confidence),
                    "unmatched_options": list(value.get("unmatched_options") or [])}

        def read(answers):
            out: Dict[str, Any] = {}
            for key in signals:
                if key == "restart_target":
                    out[key] = choice_value(answers, key)
                else:
                    out[key] = noul_value(answers, key)
            return out

        def envelope_payload(result, values, live):
            return {**values, "pack_version": HOURGLASS_STAGE_PACK_VERSION,
                    "native": bool(live)}

        # HV-1 redundancy guard, read from the pack (never decided here).
        # Placed before the preflight so a suppressed call costs nothing.
        requirement = stage_judgment_requirement(
            dimension, subject_supplied=subject_supplied,
            superseded=superseded)
        if not requirement["required"]:
            values = {key: None for key in signals}
            skipped = JevEvaluationResult(
                "skip", 0.0, 0.0, envelope_payload(None, values, False),
                [requirement["reason"]],
                is_fallback=False, model=self.evaluator.model)
            return skipped, {
                "capability": HOURGLASS_STAGE_SITE,
                "pack_id": HOURGLASS_STAGE_PACK_ID,
                "pack_version": HOURGLASS_STAGE_PACK_VERSION,
                "dimension": dimension,
                "declared_signals": signals,
                "native": False,
                "result_state": "not_required",
                "judgment_required": False,
                "skip_reason": requirement["reason"],
                "code_owned_fact": requirement["code_owned_fact"],
                # No reservation, no dispatch, no settlement, no ledger event.
                "dispatched": False,
                "cost": 0.0,
                **{key: None for key in signals},
            }

        def finish(result, values, live, reservation=None):
            structural = self._account(
                result, site=site, task_id=task_id, node_id=node_id,
                reservation=reservation,
                event_metadata={
                    "capability": HOURGLASS_STAGE_SITE,
                    "pack_id": HOURGLASS_STAGE_PACK_ID,
                    "pack_version": HOURGLASS_STAGE_PACK_VERSION,
                    "dimension": dimension,
                    "result_state": "judged" if live else "unavailable",
                    "fallback_state": (
                        "not_used" if live else
                        "fallback" if result.is_fallback else "invalid"),
                    "native": bool(live),
                })
            structural.update({
                "capability": HOURGLASS_STAGE_SITE,
                "pack_id": HOURGLASS_STAGE_PACK_ID,
                "pack_version": HOURGLASS_STAGE_PACK_VERSION,
                "dimension": dimension,
                "declared_signals": signals,
                "native": bool(live),
                # finish() is reached only by paths that did NOT dispatch
                # (unkeyed, and a pre-dispatch HarnessError refusal). A
                # judgment WAS required and could not be made; saying
                # otherwise would make "tried and unavailable" look like
                # "asked and answered". ``result_state`` mirrors the
                # event_metadata above, so the envelope alone distinguishes
                # skip / unavailable / judged without reading the ledger.
                "judgment_required": True,
                "dispatched": False,
                "result_state": "unavailable",
                **{key: values.get(key) for key in signals},
            })
            return result, structural

        if not self.keyed:
            values = {key: None for key in signals}
            fallback = JevEvaluationResult(
                "fail", 0.0, 0.0, envelope_payload(None, values, False),
                ["unkeyed Jev cannot judge " + dimension],
                is_fallback=True, model=self.evaluator.model,
                fallback_reason=self._no_key_reason())
            return finish(fallback, values, False)

        reservation = None
        try:
            reservation = self._preflight(site=site, max_input_tokens=max_input_tokens)
            raw = self.evaluator.evaluate(state, questions)
            answers = raw.answers if isinstance(raw.answers, dict) else {}
            values = read(answers)
            live = (not raw.is_fallback
                    and all(values.get(key) is not None for key in signals))
            if not live:
                values = {key: None for key in signals}
            result = JevEvaluationResult(
                raw.verdict if raw.verdict in ("pass", "fail") else "fail",
                float(raw.confidence or 0.0),
                raw.supported, envelope_payload(raw, values, live),
                list(raw.reasons or []),
                cost=raw.cost, input_tokens=raw.input_tokens,
                output_tokens=raw.output_tokens,
                is_fallback=bool(raw.is_fallback), model=raw.model,
                discarded=bool(raw.discarded), cache_hit=raw.cache_hit)
            settled = self._account(
                result, site=site, task_id=task_id, node_id=node_id,
                reservation=reservation,
                event_metadata={
                    "capability": HOURGLASS_STAGE_SITE,
                    "pack_id": HOURGLASS_STAGE_PACK_ID,
                    "pack_version": HOURGLASS_STAGE_PACK_VERSION,
                    "dimension": dimension,
                    "result_state": "judged" if live else "unavailable",
                    "fallback_state": (
                        "not_used" if live else
                        "fallback" if raw.is_fallback else "invalid"),
                    "native": bool(live),
                })
            reservation = None
            structural = settled
            structural.update({
                "capability": HOURGLASS_STAGE_SITE,
                "pack_id": HOURGLASS_STAGE_PACK_ID,
                "pack_version": HOURGLASS_STAGE_PACK_VERSION,
                "dimension": dimension,
                "declared_signals": signals,
                "native": bool(live),
                "judgment_required": True,
                "dispatched": True,
                "result_state": "judged" if live else "unavailable",
                **{key: values.get(key) for key in signals},
            })
            return result, structural
        except ProviderUsageUnknown as exc:
            self._settle_cancelled(reservation, exc)
            raise
        except ToolCancelled as exc:
            self._settle_cancelled(reservation, exc)
            raise
        except ProviderSpendLimitError as exc:
            self._release_after_provider_limit(reservation, exc, task_id=task_id)
            raise
        except HarnessError as exc:
            self._release(reservation)
            values = {key: None for key in signals}
            fallback = JevEvaluationResult(
                "fail", 0.0, 0.0, envelope_payload(None, values, False),
                ["hourglass stage judgment unavailable: " + str(exc)],
                is_fallback=False, model=self.evaluator.model)
            return finish(fallback, values, False)

    def evaluate_simple_strategy(
            self, prompt: str, context: str = "", *,
            site: str = "simple-strategy", task_id: Optional[str] = None,
            max_input_tokens: int = JEV_MAX_INPUT_TOKENS):
        """Choose a pre-answer strategy without granting tool authority.

        Choice concentration and probabilities are retained as observations;
        only the explicit selected option controls this narrow transition.
        Unavailable Jev yields an honest ``direct_answer`` fallback because
        deterministic request-kind checks already excluded tool/current work.
        """
        options = {
            "direct_answer", "web_research", "workspace_inspection",
            "simple_action", "needs_tool", "plan", "ambiguous",
        }

        def fallback(reason: str, *, result=None):
            raw_result = result
            fb = JevEvaluationResult(
                "fail", 0.0, 0.0,
                {"strategy": "direct_answer",
                 "probabilities": None, "concentration": None,
                 "pack_version": SIMPLE_STRATEGY_PACK_VERSION},
                [reason],
                cost=float(getattr(raw_result, "cost", 0.0) or 0.0),
                input_tokens=int(getattr(raw_result, "input_tokens", 0) or 0),
                output_tokens=int(getattr(raw_result, "output_tokens", 0) or 0),
                is_fallback=True,
                model=getattr(raw_result, "model", self.evaluator.model),
                discarded=bool(getattr(raw_result, "discarded", False)),
                fallback_reason=(getattr(raw_result, "fallback_reason", None)
                                 or "strategy_unavailable"),
            )
            return fb

        reservation = None
        try:
            reservation = self._preflight(
                site=site, max_input_tokens=max_input_tokens)
            result = self.evaluator.evaluate(
                {"request": str(prompt or "")[:1400],
                 "relevant_history": str(context or "")[:1200]},
                simple_strategy_question_pack())
            raw = result.answers if isinstance(result.answers, dict) else {}
            answer = raw.get("strategy")
            choice = answer.get("choice") if isinstance(answer, dict) else None
            probabilities = (answer.get("probabilities")
                             if isinstance(answer, dict) else None)
            concentration = (answer.get("confidence")
                             if isinstance(answer, dict) else None)
            valid = (not result.is_fallback and choice in options
                     and isinstance(probabilities, dict)
                     and all(name in probabilities for name in options))
            if valid and isinstance(probabilities, dict):
                normalized = {
                    "strategy": choice,
                    "probabilities": dict(probabilities),
                    "concentration": concentration,
                    "pack_version": SIMPLE_STRATEGY_PACK_VERSION,
                }
                result = replace(result, answers=normalized, is_fallback=False)
            else:
                reason = ((result.reasons or ["simple strategy unavailable"])[0])
                result = fallback(str(reason), result=result)
            structural = self._account(
                result, site=site, task_id=task_id, reservation=reservation)
            structural.update(result.answers)
            structural["native"] = not result.is_fallback
            return result, structural
        except ProviderUsageUnknown as exc:
            self._settle_cancelled(reservation, exc)
            raise
        except ToolCancelled as exc:
            self._settle_cancelled(reservation, exc)
            raise
        except ProviderSpendLimitError as exc:
            self._release_after_provider_limit(reservation, exc, task_id=task_id)
            raise
        except HarnessError as exc:
            self._release(reservation)
            result = fallback(str(exc))
            structural = self._account(
                result, site=site, task_id=task_id)
            structural.update(result.answers)
            structural["native"] = False
            return result, structural

    def evaluate_context_need(
            self, prompt: str, *, facts: str = "", recent: str = "",
            site: str = "chat-context", task_id: Optional[str] = None,
            max_input_tokens: Optional[int] = None):
        """Should this chat turn expand beyond the nearest relevant history?

        The judgment is advisory to the chat lane's context assembly, not a
        permission gate: code still builds the messages and still owns every
        budget.  The reservation is sized to the state actually sent rather
        than a fixed constant, so a long facts index is judged whole instead
        of being silently sliced before the model sees it.
        """
        from .jev_packs import context_recall_question_pack

        state = {
            "request": str(prompt or ""),
            "remembered_facts": str(facts or ""),
            "recent_turns": str(recent or ""),
        }
        state_chars = sum(len(value) for value in state.values())
        reservation_tokens = max_input_tokens or max(512, state_chars // 4 + 256)
        structural: Dict[str, Any] = {
            "capability": "context-recall",
            "pack_version": CONTEXT_RECALL_PACK_VERSION,
            "needs_earlier_context": None,
            "target_is_remembered": None,
            "native": False,
        }
        if not self.keyed:
            structural["reason"] = "Jev unavailable (no key)"
            return JevEvaluationResult(
                "fail", 0.0, 0.0, dict(structural), ["Jev unavailable (no key)"],
                is_fallback=True,
                fallback_reason="context_recall_unavailable",
                model=self.evaluator.model,
            ), structural
        reservation = None
        try:
            reservation = self._preflight(
                site=site, max_input_tokens=reservation_tokens)
            result = self.evaluator.evaluate(
                state, context_recall_question_pack())
            raw = result.answers if isinstance(result.answers, dict) else {}
            values = {}
            for key in ("needs_earlier_context", "target_is_remembered"):
                value = raw.get(key)
                if isinstance(value, dict):
                    # Noul answers arrive as {"type": "noul", "noul": p}.
                    probability = value.get("noul", value.get("probability"))
                else:
                    probability = value
                if not isinstance(probability, (int, float)) or isinstance(probability, bool):
                    values = {}
                    break
                values[key] = float(probability)
            if not values or result.is_fallback:
                raise HarnessError(
                    str((result.reasons or ["context recall returned no usable answers"])[0]))
            normalized = {
                "needs_earlier_context": values["needs_earlier_context"],
                "target_is_remembered": values["target_is_remembered"],
                "pack_version": CONTEXT_RECALL_PACK_VERSION,
            }
            result = replace(result, verdict="pass",
                             confidence=max(values.values()), answers=normalized)
            structural.update({
                "needs_earlier_context": values["needs_earlier_context"] >= 0.5,
                "target_is_remembered": values["target_is_remembered"] >= 0.5,
                "probabilities": values,
                "native": True,
            })
            accounted = self._account(
                result, site=site, task_id=task_id, reservation=reservation)
            reservation = None
            accounted.update(structural)
            return result, accounted
        except ToolCancelled:
            raise
        except ProviderSpendLimitError:
            raise
        except HarnessError as exc:
            if reservation is not None:
                self._release(reservation)
            structural["reason"] = str(exc)
            return JevEvaluationResult(
                "fail", 0.0, 0.0, dict(structural), [str(exc)],
                is_fallback=True,
                fallback_reason="context_recall_unavailable",
                model=self.evaluator.model,
            ), structural

    def evaluate_answer(
            self, prompt: str, answer: str, context: str = "", *,
            site: str = "answer", task_id: Optional[str] = None,
            max_input_tokens: int = JEV_MAX_INPUT_TOKENS):
        """Assess a candidate answer and expose explicit loop signals.

        This is deliberately a narrow Jev capability rather than a second
        completion engine.  The caller owns model selection, retries, the
        confidence threshold, and any plan transition; Jev only judges the
        bounded candidate state.  A fallback or malformed response is never
        allowed to look like a sufficient/native answer.
        """
        state = {
            "request": str(prompt or "")[:JEV_REQUEST_MAX_CHARS],
            "candidate_answer": str(answer or "")[:JEV_ANSWER_MAX_CHARS],
            "retained_context": str(context or "")[:JEV_CONTEXT_MAX_CHARS],
        }
        questions = answer_question_pack()

        def probability(answers, key):
            value = (answers or {}).get(key)
            if isinstance(value, dict) and "noul" in value:
                value = value.get("noul")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None
            value = float(value)
            if value < 0.0 or value > 1.0:
                return None
            return value

        def normalize(result):
            raw = result.answers if isinstance(result.answers, dict) else {}
            values = {key: probability(raw, key) for key in questions}
            valid = not result.is_fallback and all(v is not None for v in values.values())
            if not valid:
                reasons = list(result.reasons or [])
                if not reasons:
                    reasons = ["answer judgment unavailable or malformed"]
                fallback = JevEvaluationResult(
                    "fail", 0.0, 0.0,
                    {**{key: None for key in questions}, "pack_version": ANSWER_PACK_VERSION},
                    reasons, cost=result.cost, input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    # A malformed live response is not a heuristic fallback,
                    # but it is still not a usable native judgment. Preserve
                    # this distinction so reported provider usage is settled.
                    is_fallback=bool(result.is_fallback),
                    model=result.model,
                    discarded=bool(result.discarded),
                    fallback_reason=result.fallback_reason,
                )
                return fallback, values, False
            # `valid` proved every probability is a float; narrow them once
            # here rather than asking each arithmetic site to re-prove it. The
            # filtered mapping equals `values` whenever `valid` holds.
            measured = {key: float(value) for key, value in values.items()
                        if value is not None}
            normalized = {
                "answer_sufficient": measured["answer_sufficient"],
                "iteration_required": measured["iteration_required"] >= 0.5,
                "plan_required": measured["plan_required"] >= 0.5,
                "raw": raw,
                "pack_version": ANSWER_PACK_VERSION,
            }
            verdict = result.verdict if result.verdict in ("pass", "fail") else "fail"
            return JevEvaluationResult(
                verdict, float(result.confidence or 0.0),
                min(measured.values()), normalized, list(result.reasons or []),
                cost=result.cost, input_tokens=result.input_tokens,
                output_tokens=result.output_tokens, is_fallback=False,
                model=result.model, cache_hit=result.cache_hit,
            ), values, True

        if not self.keyed:
            fallback = JevEvaluationResult(
                "fail", 0.0, 0.0,
                {key: None for key in questions} | {"pack_version": ANSWER_PACK_VERSION},
                ["unkeyed Jev cannot establish answer sufficiency"],
                is_fallback=True, model=self.evaluator.model,
                fallback_reason=("explicit_disable"
                                 if getattr(self.evaluator,
                                            "explicitly_disabled", False)
                                 else "missing_key"),
            )
            structural = self._account(fallback, site=site, task_id=task_id)
            structural.update({
                "capability": "answer",
                "pack_version": ANSWER_PACK_VERSION,
                "native": False,
                "answer_sufficient": None,
                "iteration_required": True,
                "plan_required": None,
            })
            return fallback, structural

        reservation = None
        dispatched = False
        try:
            reservation = self._preflight(site=site, max_input_tokens=max_input_tokens)
            dispatched = True
            raw_result = self.evaluator.evaluate(state, questions)
            result, values, live = normalize(raw_result)
            structural = self._account(
                result, site=site, task_id=task_id, reservation=reservation)
            reservation = None
            iteration_required = values.get("iteration_required")
            plan_required = values.get("plan_required")
            structural.update({
                "capability": "answer",
                "pack_version": ANSWER_PACK_VERSION,
                "native": bool(live),
                "answer_sufficient": values.get("answer_sufficient"),
                "iteration_required": (
                    True if iteration_required is None
                    else iteration_required >= 0.5),
                "plan_required": (
                    None if plan_required is None
                    else plan_required >= 0.5),
            })
            return result, structural
        except ProviderUsageUnknown as exc:
            self._settle_cancelled(reservation, exc)
            raise
        except ToolCancelled as exc:
            self._settle_cancelled(reservation, exc)
            raise
        except ProviderSpendLimitError as exc:
            self._release_after_provider_limit(reservation, exc, task_id=task_id)
            raise
        except HarnessError as exc:
            self._release(reservation)
            # Only a settlement failure happens AFTER a request was billed; a
            # refused reservation (budget) is a pre-dispatch refusal even
            # though it is raised from inside the dispatcher.
            post_dispatch = dispatched and self._sent(reservation)
            refusal, structural = self._record_refusal(
                str(exc), code=_refusal_reason(exc), site=site, task_id=task_id)
            refusal = JevEvaluationResult(
                "fail", 0.0, 0.0,
                {key: None for key in questions} | {"pack_version": ANSWER_PACK_VERSION},
                list(refusal.reasons), is_fallback=post_dispatch,
                model=refusal.model,
                fallback_reason="transport_failure" if post_dispatch else None,
            )
            structural.update({
                "capability": "answer",
                "pack_version": ANSWER_PACK_VERSION,
                "native": False,
                "answer_sufficient": None,
                "iteration_required": True,
                "plan_required": None,
                "is_fallback": refusal.is_fallback,
                "fallback_reason": refusal.fallback_reason,
            })
            return refusal, structural

    def evaluate_candidate(self, original: str, candidate: str, instruction: str,
                           file_path: str, *, site: str = "apply",
                           task_id: Optional[str] = None,
                           node_id: Optional[str] = None,
                           max_input_tokens: int = JEV_MAX_INPUT_TOKENS):
        """Evaluate a candidate diff before the verification gate can write it."""
        diff = "".join(difflib.unified_diff(
            original.splitlines(keepends=True),
            candidate.splitlines(keepends=True),
            fromfile="a/" + os.path.basename(file_path),
            tofile="b/" + os.path.basename(file_path),
        ))
        return self.evaluate_diff(
            diff, instruction, file_path, candidate=candidate, site=site,
            task_id=task_id, node_id=node_id, max_input_tokens=max_input_tokens,
        )

    def evaluate_triage(self, prompt: str, target_files=None, *,
                        site: str = "triage", task_id: Optional[str] = None):
        """Return a bounded route choice plus iteration signal for Pillar 1."""
        reservation = None
        try:
            reservation = self._preflight(site=site, max_input_tokens=JEV_MAX_INPUT_TOKENS)
            result = self.evaluator.evaluate(
                {"prompt": prompt or "", "target_files": list(target_files or [])},
                triage_question_pack())
            if result.is_fallback and "route" not in result.answers:
                lower = (prompt or "").lower()
                iterative = any(word in lower for word in
                                ("iterat", "loop", "branch", "recur", "algorithm", "architect"))
                route = "frontier" if iterative else (
                    "diff" if len(target_files or []) > 1 else "free-distill")
                result = self._local_from(
                    result, {"route": route, "requires_iteration": iterative},
                    result.reasons,
                    self._fallback_reason_of(result, "triage_unanswered"))
            structural = self._account(result, site=site, task_id=task_id,
                                       reservation=reservation)
            return result, structural
        except ProviderUsageUnknown as exc:
            self._settle_cancelled(reservation, exc)
            raise
        except ToolCancelled as exc:
            self._settle_cancelled(reservation, exc)
            raise
        except ProviderSpendLimitError as exc:
            self._release_after_provider_limit(reservation, exc, task_id=task_id)
            raise
        except HarnessError as exc:
            self._release(reservation)
            # Honest local triage is heuristic only; it never pretends to be live.
            lower = (prompt or "").lower()
            iterative = any(word in lower for word in
                            ("iterat", "loop", "branch", "recur", "algorithm", "architect"))
            route = "frontier" if iterative else ("diff" if len(target_files or []) > 1 else "free-distill")
            fallback = JevEvaluationResult(
                "pass", 0.0, 1.0,
                {"route": route, "requires_iteration": iterative}, [str(exc)],
                is_fallback=True, model=self.evaluator.model,
                fallback_reason=_refusal_reason(exc))
            return fallback, self._account(fallback, site=site, task_id=task_id)

    def evaluate_escalation_decision(
            self, failure_context: str, *, site: str = "escalation-decision",
            task_id: Optional[str] = None,
            max_input_tokens: int = JEV_MAX_INPUT_TOKENS):
        """Jev-directed escalation signals for the P2 decision pipeline
        (JEV-P2-dead-code: wire, not delete).

        Two nouls over the code-owned failure context (verify-output tail +
        attempt history -- never model output treated as state):

        - ``escalation_decision``: the ``decide_probe_verify_escalate``
          noul. Its calibrated confidence IS the confidence the dead
          function's ``confidence`` parameter was always meant to receive.
        - ``capability_budget``: the ``should_abstain`` noul (remaining
          attempt budget worth another same-tier retry?).

        Unkeyed runs dispatch no network and resolve to the evaluator's
        honest local fallback (``is_fallback=True``), so callers treat a
        fallback result as "no Jev signal available" and keep the
        status-quo walk. Live transport/contract failures refund the
        reservation and refuse honestly. Returns ``(result, structural)``.
        """
        reservation = None
        try:
            reservation = self._preflight(
                site=site, max_input_tokens=max_input_tokens)
            result = self.evaluator.evaluate(
                {"context": failure_context or ""},
                escalation_decision_pack())
            structural = self._account(
                result, site=site, task_id=task_id, reservation=reservation)
            reservation = None
            return result, structural
        except ProviderUsageUnknown as exc:
            self._settle_cancelled(reservation, exc)
            raise
        except ToolCancelled as exc:
            self._settle_cancelled(reservation, exc)
            raise
        except ProviderSpendLimitError as exc:
            self._release_after_provider_limit(reservation, exc, task_id=task_id)
            raise
        except HarnessError as exc:
            self._release(reservation)
            return self._record_refusal(
                str(exc), code=_refusal_reason(exc), site=site, task_id=task_id)

    def evaluate_decision(self, action: str, end_state: str, context: str = "",
                          *, site: str = DECISION_SITE,
                          task_id: Optional[str] = None,
                          node_id: Optional[str] = None,
                          threshold: float = DECISION_CONFIDENCE_THRESHOLD,
                          margin: float = DECISION_DISPOSITION_MARGIN,
                          max_input_tokens: int = JEV_MAX_INPUT_TOKENS):
        """Typed pre-escalation decision gate (issue #106).

        Jev advises on three split dimensions over code-owned state
        (``action``, ``end_state``, ``context`` -- never model output);
        CODE composes the verdict via ``compose_decision_verdict``:

        - ``is_destructive >= 0.5`` -> escalate, at any confidence;
        - no Jev signal (unkeyed / transport failure) or unusable answers
          -> escalate (fail closed, never proceed);
        - disposition ``escalate`` -> escalate;
        - the disposition does not lead the runner-up by ``margin`` ->
          escalate. A Choice's ``confidence`` is distribution concentration
          and does NOT gate: holding it to an absolute ``threshold`` demanded
          near-unanimity from a three-way question and escalated on almost
          every well-evidenced action. The disposition's concentration is
          still reported as ``disposition_confidence`` for telemetry;
        - ``advances_goal`` < threshold -> investigate (Jev Gate Policy v1
          rule 6). A Noul is a real yes-probability, but it carries
          evidence-thoroughness bias: a low value says "gather evidence", not
          "harm is likely". The caller proceeds with a documented note if the
          investigation finds no risk, and escalates if it does;
        - disposition ``needs_improvement`` -> revise: the caller fixes the
          action and re-gates (bounded by ``DECISION_MAX_REVISIONS``);
        - otherwise -> proceed.

        Authorization gates are not bypassed: the gate can only add a
        reason to escalate, never remove one. Returns ``(verdict,
        structural)`` where ``verdict`` is the composed dict
        (``verdict`` / ``reasons`` / the three signals / ``disposition_lead``
        / ``threshold`` / ``margin`` / ``pack_version``) and ``structural``
        is the shared Jev envelope; the ``jev_eval`` ledger event carries
        the composed verdict so the gate is measurable like every other Jev
        surface.
        """
        reservation = None
        try:
            reservation = self._preflight(
                site=site, max_input_tokens=max_input_tokens)
            result = self.evaluator.evaluate(
                {"action": action or "", "end_state": end_state or "",
                 "context": context or ""},
                decision_question_pack())
            verdict = compose_decision_verdict(
                result, threshold=threshold, margin=margin)
            structural = self._account(
                result, site=site, task_id=task_id, node_id=node_id,
                reservation=reservation,
                event_metadata={
                    "decision_verdict": verdict["verdict"],
                    "decision_disposition": verdict["disposition"],
                    "decision_confidence": verdict["disposition_confidence"],
                    "decision_lead": verdict["disposition_lead"],
                    "decision_advances_goal": verdict["advances_goal"],
                    "decision_destructive": verdict["is_destructive"],
                    "decision_threshold": threshold,
                    "decision_margin": margin,
                    "decision_pack": DECISION_PACK_VERSION,
                })
            reservation = None
            return verdict, structural
        except ProviderUsageUnknown as exc:
            self._settle_cancelled(reservation, exc)
            raise
        except ToolCancelled as exc:
            self._settle_cancelled(reservation, exc)
            raise
        except ProviderSpendLimitError as exc:
            self._release_after_provider_limit(reservation, exc, task_id=task_id)
            raise
        except HarnessError as exc:
            self._release(reservation)
            result, structural = self._record_refusal(
                str(exc), code=_refusal_reason(exc), site=site, task_id=task_id, node_id=node_id)
            verdict = compose_decision_verdict(
                result, threshold=threshold, margin=margin)
            verdict["reasons"] = (["evaluation refused: " + str(exc)]
                                  + verdict["reasons"])
            return verdict, structural

    def evaluate_plan(self, prompt: str, target_files=None, *, site: str = "waist",
                      task_id: Optional[str] = None, node_id: Optional[str] = None,
                      max_input_tokens: int = JEV_MAX_INPUT_TOKENS):
        """Evaluate the bounded plan pack and account it like every other site."""
        reservation = None
        try:
            reservation = self._preflight(
                site=site, max_input_tokens=max_input_tokens)
            result = self.evaluator.evaluate_plan_requirements(
                prompt, target_files)
            structural = self._account(
                result, site=site, task_id=task_id, node_id=node_id,
                reservation=reservation,
            )
            reservation = None
            return result, structural
        except ProviderUsageUnknown as exc:
            self._settle_cancelled(reservation, exc)
            raise
        except ToolCancelled as exc:
            self._settle_cancelled(reservation, exc)
            raise
        except ProviderSpendLimitError as exc:
            self._release_after_provider_limit(reservation, exc, task_id=task_id)
            raise
        except HarnessError as exc:
            self._release(reservation)
            return self._record_refusal(
                str(exc), code=_refusal_reason(exc), site=site, task_id=task_id, node_id=node_id)

    def evaluate_route(self, prompt: str, target_files=None, *,
                       site: str = "route", task_id: Optional[str] = None,
                       node_id: Optional[str] = None,
                       max_input_tokens: int = JEV_MAX_INPUT_TOKENS):
        """JEV-P3-route: typed route choice over the shared vocabulary.

        Keyed answers use the route pack; unkeyed/transport failure returns
        the existing heuristic with ``is_fallback=True`` (never brand ids).
        """
        reservation = None
        try:
            reservation = self._preflight(
                site=site, max_input_tokens=max_input_tokens)
            result = self.evaluator.evaluate(
                {"prompt": prompt or "", "target_files": list(target_files or [])},
                route_question_pack())
            answers = dict(result.answers or {})
            if result.is_fallback or "route" not in answers:
                route = heuristic_route(prompt, target_files)
                iterative = heuristic_requires_iteration(prompt)
                answers = {
                    "route": route,
                    "requires_iteration": iterative,
                    **{k: v for k, v in answers.items() if k not in ("route", "requires_iteration")},
                }
                result = self._local_from(
                    result, answers, result.reasons,
                    self._fallback_reason_of(result, "route_unanswered"))
            else:
                # Normalize live choice into the vocabulary (or fall back).
                normalized = normalize_route(
                    answers.get("route", {}).get("choice")
                    if isinstance(answers.get("route"), dict)
                    else answers.get("route"))
                if normalized is None:
                    route = heuristic_route(prompt, target_files)
                    answers = dict(answers)
                    answers["route"] = route
                    result = replace(
                        result, answers=answers,
                        reasons=list(result.reasons) + [
                            "live route outside vocabulary; heuristic applied"],
                        is_fallback=True, discarded=result.input_tokens > 0,
                        fallback_reason="route_out_of_vocabulary")
                else:
                    answers = dict(answers)
                    answers["route"] = normalized
                    raw_iter = answers.get("requires_iteration")
                    if isinstance(raw_iter, dict) and "noul" in raw_iter:
                        answers["requires_iteration"] = float(raw_iter["noul"]) >= 0.5
                    elif not isinstance(raw_iter, bool):
                        answers["requires_iteration"] = heuristic_requires_iteration(prompt)
                    result = replace(result, answers=answers, is_fallback=False)
            structural = self._account(
                result, site=site, task_id=task_id, node_id=node_id,
                reservation=reservation)
            return result, structural
        except ProviderUsageUnknown as exc:
            self._settle_cancelled(reservation, exc)
            raise
        except ToolCancelled as exc:
            self._settle_cancelled(reservation, exc)
            raise
        except ProviderSpendLimitError as exc:
            self._release_after_provider_limit(reservation, exc, task_id=task_id)
            raise
        except HarnessError as exc:
            self._release(reservation)
            route = heuristic_route(prompt, target_files)
            answers = {
                "route": route,
                "requires_iteration": heuristic_requires_iteration(prompt),
            }
            fallback = JevEvaluationResult(
                "pass", 0.0, 1.0, answers, [str(exc)],
                is_fallback=True, model=self.evaluator.model,
                fallback_reason=_refusal_reason(exc))
            return fallback, self._account(fallback, site=site, task_id=task_id)

    def evaluate_file_triage(self, goal: str, candidates: Sequence[str],
                             known_files: Optional[Sequence[str]] = None, *,
                             site: str = "triage-files",
                             task_id: Optional[str] = None,
                             max_files: int = 15,
                             max_input_tokens: int = JEV_MAX_INPUT_TOKENS):
        """JEV-P3-triage-files: noul relevance over orchestrator candidates.

        Every kept path is validated against ``known_files`` when supplied.
        Unkeyed path uses the keyword heuristic with honest ``is_fallback``.
        """
        listing = list(known_files) if known_files is not None else None
        scoped = validate_candidates(candidates, listing)[:max_files]
        if not scoped:
            empty = JevEvaluationResult(
                "pass", 0.0, 1.0,
                {"files": [], "is_fallback": True},
                ["no candidates to triage"], is_fallback=True,
                model=self.evaluator.model, fallback_reason="no_candidates")
            structural = self._structural(empty, site)
            structural["files"] = []
            return empty, structural
        reservation = None
        try:
            reservation = self._preflight(
                site=site, max_input_tokens=max_input_tokens)
            result = self.evaluator.evaluate(
                {"goal": goal or "", "files": list(scoped)},
                file_relevance_question_pack(scoped))
            picked: List[str] = []
            if result.is_fallback:
                picked = heuristic_file_relevance(goal, scoped, max_files=max_files)
                answers = {"files": picked, "heuristic": True}
                result = self._local_from(
                    result, answers, result.reasons,
                    self._fallback_reason_of(result, "triage_unanswered"))
            else:
                for index, path in enumerate(scoped):
                    key = f"file_{index}_relevant"
                    answer = (result.answers or {}).get(key)
                    prob = None
                    if isinstance(answer, dict):
                        prob = answer.get("noul")
                    elif isinstance(answer, (int, float)):
                        prob = answer
                    if isinstance(prob, (int, float)) and float(prob) >= 0.5:
                        picked.append(path)
                if not picked:
                    # Live pack said nothing relevant — keep honest empty list.
                    picked = []
                answers = {"files": picked}
                result = replace(result, answers=answers, is_fallback=False)
            # Defense in depth: never emit a path outside the real listing.
            result.answers["files"] = validate_candidates(picked, listing)
            structural = self._account(
                result, site=site, task_id=task_id, reservation=reservation)
            structural["files"] = list(result.answers["files"])
            return result, structural
        except ProviderUsageUnknown as exc:
            self._settle_cancelled(reservation, exc)
            raise
        except ToolCancelled as exc:
            self._settle_cancelled(reservation, exc)
            raise
        except ProviderSpendLimitError as exc:
            self._release_after_provider_limit(reservation, exc, task_id=task_id)
            raise
        except HarnessError as exc:
            self._release(reservation)
            picked = heuristic_file_relevance(goal, scoped, max_files=max_files)
            picked = validate_candidates(picked, listing)
            fallback = JevEvaluationResult(
                "pass", 0.0, 1.0,
                {"files": picked, "heuristic": True}, [str(exc)],
                is_fallback=True, model=self.evaluator.model,
                fallback_reason=_refusal_reason(exc))
            structural = self._account(fallback, site=site, task_id=task_id)
            structural["files"] = picked
            return fallback, structural

    def evaluate_result_relevance(self, prompt: str,
                                  results: Sequence[Dict[str, Any]], *,
                                  site: str = "web-results",
                                  task_id: Optional[str] = None,
                                  max_input_tokens: int = JEV_MAX_INPUT_TOKENS):
        """#660 line 1: one typed relevance verdict per gathered web result.

        Bands are code-owned on the noul probability (:func:`result_verdict`):
        relevant at or above ``RESULT_RELEVANT_AT``, rejected at or below
        ``RESULT_REJECTED_AT``, otherwise uncertain. A missing or unparseable
        answer is uncertain, never admission, and the caller excludes both.

        Fail-closed (oversight decision 7078539288): when the reviewer cannot
        answer at all -- refusal, spend limit, transport error -- every result
        is reported ``unreviewed`` with the outage reason; the caller excludes
        those results and discloses the outage in the evidence block. Nothing
        unreviewed is ever admitted as reviewed. With no key there is no
        reviewer to be down, so the local fallback records an admitted
        verdict that names the method it actually used.
        """
        items = [dict(item) for item in list(results)[:MAX_RESULT_REVIEW]]
        if not items:
            empty = JevEvaluationResult(
                "pass", 0.0, 1.0, {"results": [], "reviewed": False},
                ["no gathered results to review"], is_fallback=True,
                model=self.evaluator.model, fallback_reason="no_results")
            structural = self._structural(empty, site)
            structural.update({"results": [], "reviewed": False,
                               "outage": False})
            return empty, structural
        if not self.keyed:
            verdicts = self._local_result_verdicts(prompt, items)
            local = JevEvaluationResult(
                "pass", 0.0, 1.0, {"results": verdicts},
                ["local term reviewer: no native reviewer configured"],
                is_fallback=True, model=LOCAL_HEURISTIC_MODEL,
                fallback_reason="reviewer_unkeyed")
            structural = self._structural(local, site)
            structural.update({"results": verdicts, "reviewed": True,
                               "outage": False})
            return local, structural
        reservation = None
        try:
            reservation = self._preflight(
                site=site, max_input_tokens=max_input_tokens)
            result = self.evaluator.evaluate(
                {"request": (prompt or "")[:JEV_REQUEST_MAX_CHARS],
                 "results": [{"url": str(item.get("url") or ""),
                              "title": str(item.get("title") or ""),
                              "text": str(item.get("text") or "")[:800]}
                             for item in items]},
                result_relevance_question_pack(items))
            if result.is_fallback:
                return self._result_review_outage(
                    result, items, site=site, task_id=task_id,
                    reservation=reservation,
                    reason=self._fallback_reason_of(result,
                                                    "reviewer_unanswered"))
            verdicts = self._band_result_answers(result.answers, items)
            reviewed = replace(result, answers={"results": verdicts})
            structural = self._account(
                reviewed, site=site, task_id=task_id,
                reservation=reservation)
            structural.update({"results": verdicts, "reviewed": True,
                               "outage": False})
            return reviewed, structural
        except (ToolCancelled, ProviderUsageUnknown) as exc:
            self._settle_cancelled(reservation, exc)
            raise
        except ProviderSpendLimitError as exc:
            self._release_after_provider_limit(
                reservation, exc, task_id=task_id)
            return self._result_review_unanswered(
                str(exc), items, site=site, task_id=task_id,
                code="reviewer_spend_limit")
        except HarnessError as exc:
            self._release(reservation)
            return self._result_review_unanswered(
                str(exc), items, site=site, task_id=task_id)

    @staticmethod
    def _local_result_verdicts(prompt: str,
                               items: Sequence[Dict[str, Any]]
                               ) -> List[Dict[str, Any]]:
        """Band the local fallback's probabilities into typed verdicts."""
        verdicts: List[Dict[str, Any]] = []
        for index, scored in enumerate(
                heuristic_result_relevance(prompt, items)):
            probability = scored.get("probability")
            verdicts.append({
                "url": str(items[index].get("url") or ""),
                "verdict": result_verdict(probability),
                "probability": probability,
                "reason": str(scored.get("reason") or ""),
            })
        return verdicts

    @staticmethod
    def _band_result_answers(answers: Optional[Dict[str, Any]],
                             items: Sequence[Dict[str, Any]]
                             ) -> List[Dict[str, Any]]:
        """Read one banded verdict per result, never a silent admission."""
        verdicts: List[Dict[str, Any]] = []
        for index, item in enumerate(items):
            answer = (answers or {}).get(f"result_{index}_relevant")
            probability = (answer.get("noul") if isinstance(answer, dict)
                           else answer)
            if isinstance(probability, (int, float)):
                probability = float(probability)
                reason = "noul {:.2f} -> {}".format(
                    probability, result_verdict(probability))
            else:
                probability = None
                reason = "reviewer returned no answer for this result"
            verdicts.append({
                "url": str(item.get("url") or ""),
                "verdict": result_verdict(probability),
                "probability": probability,
                "reason": reason,
            })
        return verdicts

    @staticmethod
    def _unreviewed(items: Sequence[Dict[str, Any]], reason: str
                    ) -> List[Dict[str, Any]]:
        return [{"url": str(item.get("url") or ""),
                 "verdict": RESULT_UNREVIEWED, "probability": None,
                 "reason": reason} for item in items]

    def _result_review_outage(self, result: JevEvaluationResult,
                              items: Sequence[Dict[str, Any]], *,
                              site: str, task_id: Optional[str],
                              reservation, reason: str):
        """Book the answering call, then report every result unreviewed."""
        verdicts = self._unreviewed(items, reason)
        settled = replace(result, answers={"results": verdicts})
        structural = self._account(
            settled, site=site, task_id=task_id, reservation=reservation)
        structural.update({"results": verdicts, "reviewed": False,
                           "outage": True, "outage_reason": reason})
        return settled, structural

    def _result_review_unanswered(self, reason: str,
                                  items: Sequence[Dict[str, Any]], *,
                                  site: str, task_id: Optional[str],
                                  code: str = "reviewer_outage"):
        """Refusal/spend/transport: a receipt, not an admission."""
        result, structural = self._record_refusal(
            reason, site=site, task_id=task_id, code=code)
        verdicts = self._unreviewed(items, reason)
        structural.update({"results": verdicts, "reviewed": False,
                           "outage": True, "outage_reason": reason})
        return replace(result, answers={"results": verdicts}), structural

    def evaluate_research_plan(self, plan_state: Dict[str, Any], *,
                               plan_hash: str, request_hash: str,
                               revision: int = 0,
                               site: str = RESEARCH_PLAN_SITE,
                               task_id: Optional[str] = None,
                               max_input_tokens: int = JEV_MAX_INPUT_TOKENS):
        """#342: the ONE native judgment that can approve external retrieval.

        The plan itself is built and validated by :mod:`harness.research_plan`;
        this method owns only the typed call. It answers ``accept`` /
        ``revise`` / ``decline`` plus one relevance noul per exact query, and
        code bands those answers: an accept whose acknowledgements are
        incomplete, that rejects a query, or that falls under the policy's
        confidence floor is reported as ``decline`` with its reason. Every way
        the reviewer can fail -- unkeyed, refusal, spend limit, transport
        error, unusable answer -- reports ``unavailable`` with ``native``
        false, so no local heuristic preview can ever become approval.
        """
        base = {"plan_hash": str(plan_hash),
                "request_hash": str(request_hash),
                "revision": int(revision)}
        if not self.keyed:
            result, structural = self._record_refusal(
                "unkeyed Jev cannot approve a research plan; retrieval stays "
                "closed", site=site, task_id=task_id,
                code="plan_review_unkeyed")
            structural.update(base, decision="unavailable", native=False,
                              reviewed=False, query_verdicts=[],
                              outage=True,
                              outage_reason="reviewer_unkeyed")
            return replace(result, answers={"decision": "unavailable",
                                            "query_verdicts": []}), structural
        reservation = None
        try:
            reservation = self._preflight(
                site=site, max_input_tokens=max_input_tokens)
            result = self.evaluator.evaluate(
                plan_state, research_plan_question_pack(plan_state))
            if result.is_fallback:
                return self._plan_review_closed(
                    base, result, site=site, task_id=task_id,
                    reservation=reservation,
                    reason=self._fallback_reason_of(
                        result, "plan_reviewer_unanswered"))
            decision, verdicts, reason = self._band_plan_answers(
                result.answers, plan_state,
                confidence=float(result.confidence or 0.0))
            reviewed = replace(result, answers={
                "decision": decision, "query_verdicts": verdicts})
            structural = self._account(
                reviewed, site=site, task_id=task_id,
                reservation=reservation)
            if decision == "accept":
                structural.update(base, decision=decision, native=True,
                                  reviewed=True, query_verdicts=verdicts,
                                  outage=False)
            else:
                structural.update(base, decision=decision, native=True,
                                  reviewed=True, query_verdicts=verdicts,
                                  outage=False,
                                  decision_reason=reason)
            return reviewed, structural
        except (ToolCancelled, ProviderUsageUnknown):
            self._release(reservation)
            raise
        except ProviderSpendLimitError as exc:
            self._release_after_provider_limit(
                reservation, exc, task_id=task_id)
            return self._plan_review_unavailable(
                base, str(exc), site=site, task_id=task_id,
                code="plan_reviewer_spend_limit")
        except HarnessError as exc:
            self._release(reservation)
            return self._plan_review_unavailable(
                base, str(exc), site=site, task_id=task_id)

    def _band_plan_answers(self, answers: Optional[Dict[str, Any]],
                           plan_state: Dict[str, Any], *,
                           confidence: float
                           ) -> Tuple[str, List[bool], str]:
        """Read the typed decision and every per-query answer, or refuse.

        A missing or unparseable per-query answer is not approval; the whole
        judgment becomes ``invalid`` rather than accepting the answered part.
        """
        raw = (answers or {}).get("plan_decision")
        choice = raw.get("choice") if isinstance(raw, dict) else raw
        choice = str(choice or "").strip().lower()
        queries = list(plan_state.get("queries") or [])
        verdicts: List[bool] = []
        complete = True
        for index in range(len(queries)):
            answer = (answers or {}).get(f"query_{index}_relevant")
            probability = (answer.get("noul") if isinstance(answer, dict)
                           else answer)
            if isinstance(probability, (int, float)):
                verdicts.append(float(probability) >= 0.5)
            else:
                verdicts.append(False)
                complete = False
        if queries and not complete:
            return "invalid", verdicts, "incomplete query review"
        if choice not in ("accept", "revise", "decline"):
            return "invalid", verdicts, "reviewer returned no usable decision"
        if choice == "accept" and not all(verdicts or [True]):
            return "decline", verdicts, "at least one query was not accepted"
        floor = float(getattr(self, "min_confidence", 0.70) or 0.70)
        # A noul-only pack reports no Choice confidence (0.0), which the rest
        # of the policy reads as "not reported" -- only a reported-low
        # confidence is a decline.
        if choice == "accept" and 0.0 < confidence < floor:
            return "decline", verdicts, "confidence below the approval floor"
        return choice, verdicts, ""

    def _plan_review_closed(self, base: Dict[str, Any],
                            result: JevEvaluationResult, *,
                            site: str, task_id: Optional[str],
                            reservation, reason: str):
        """Book the answering call, then report the plan unapproved."""
        settled = replace(result, answers={"decision": "unavailable",
                                           "query_verdicts": []})
        structural = self._account(
            settled, site=site, task_id=task_id, reservation=reservation)
        structural.update(base, decision="unavailable", native=False,
                          reviewed=False, query_verdicts=[],
                          outage=True, outage_reason=reason)
        return settled, structural

    def _plan_review_unavailable(self, base: Dict[str, Any], reason: str, *,
                                 site: str, task_id: Optional[str],
                                 code: str = "plan_reviewer_outage"):
        """Refusal/spend/transport: a receipt, never an approval."""
        result, structural = self._record_refusal(
            reason, site=site, task_id=task_id, code=code)
        structural.update(base, decision="unavailable", native=False,
                          reviewed=False, query_verdicts=[],
                          outage=True, outage_reason=reason)
        return replace(result, answers={"decision": "unavailable",
                                        "query_verdicts": []}), structural

    def evaluate_claim_support(self, claims, source_context: str, *,
                               enabled: bool = False,
                               site: str = "claims",
                               task_id: Optional[str] = None,
                               max_input_tokens: int = JEV_MAX_INPUT_TOKENS):
        """JEV-P3-claims: optional lean support checks before panel judge --
        delegated.

        Default off (``enabled=False``). Does not own claims lint -- that stays
        in :mod:`harness.claims`. This only adds advisory typed flags. The
        0-hallucination rules and the fail-closed envelope live in
        :func:`harness.jev_claims.evaluate_claim_support`; the policy instance
        is passed in, so dispatch, spend, settlement and ledger semantics stay
        in this one owner.
        """
        return _evaluate_claim_support(
            self, claims, source_context, enabled=enabled, site=site,
            task_id=task_id, max_input_tokens=max_input_tokens,
            refusal_reason=_refusal_reason)

    def evaluate_completion_nouls(self, goal: str, state_summary: str,
                                  named_artifacts=None, root_dir=None, *,
                                  site: str = "completion",
                                  task_id: Optional[str] = None,
                                  max_input_tokens: int = JEV_MAX_INPUT_TOKENS):
        """JEV-P3-completion: artifact/goal nouls before the generative judge.

        Missing named artifact is code-owned truth: the envelope cannot
        complete regardless of live answers.
        """
        from pathlib import Path as _Path
        if named_artifacts is None:
            artifact_facts = named_artifact_status(goal, root_dir=root_dir)
        else:
            base = _Path(root_dir) if root_dir is not None else _Path.cwd()
            artifact_facts = []
            for item in named_artifacts:
                if isinstance(item, dict):
                    path = str(item.get("path") or "").replace("\\", "/")
                    present = bool(item.get("present"))
                    if path and not item.get("present") and "present" not in item:
                        present = (base / path).is_file()
                    artifact_facts.append({
                        "path": path,
                        "present": present,
                        "lines": item.get("lines"),
                    })
                else:
                    path = str(item).replace("\\", "/").strip("`'\" .")
                    present = bool(path) and (base / path).is_file()
                    artifact_facts.append({
                        "path": path, "present": present, "lines": None,
                    })
        missing = [item["path"] for item in artifact_facts
                   if item.get("path") and not item.get("present")]
        artifacts_payload = artifact_facts
        if missing:
            # Code-owned refuse: no spend required to know completion is false.
            answers = {
                "named_artifacts_present": 0.0,
                "goal_achieved": 0.0,
                "missing_artifacts": missing,
                "artifacts": artifacts_payload,
            }
            result = JevEvaluationResult(
                "fail", 0.0, 0.0, answers,
                [f"named artifact missing: {p}" for p in missing],
                is_fallback=False, model=self.evaluator.model)
            structural = self._account(
                result, site=site, task_id=task_id, reservation=None)
            structural["cannot_complete"] = True
            structural["missing_artifacts"] = missing
            return result, structural
        reservation = None
        dispatched = False
        try:
            reservation = self._preflight(
                site=site, max_input_tokens=max_input_tokens)
            dispatched = True
            result = self.evaluator.evaluate(
                {
                    "goal": goal or "",
                    "execution_state": (state_summary or "")[:4000],
                    "named_artifacts": artifacts_payload,
                },
                completion_question_pack())
            answers = dict(result.answers or {})
            cannot = False
            if result.is_fallback:
                # Unkeyed: artifacts exist; generative judge remains the seat.
                answers.setdefault("named_artifacts_present", 1.0)
                answers.setdefault("goal_achieved", None)
                answers["artifacts"] = artifacts_payload
                result = JevEvaluationResult(
                    "pass", 0.0, 1.0, answers, result.reasons,
                    cost=result.cost, input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    is_fallback=True, model=result.model,
                    fallback_reason=result.fallback_reason)
            else:
                present = answers.get("named_artifacts_present")
                achieved = answers.get("goal_achieved")
                present_p = float(present.get("noul", 0.0)) if isinstance(present, dict) else float(present or 0.0)
                achieved_p = float(achieved.get("noul", 0.0)) if isinstance(achieved, dict) else float(achieved or 0.0)
                answers = dict(answers)
                answers["named_artifacts_present"] = present_p
                answers["goal_achieved"] = achieved_p
                answers["artifacts"] = artifacts_payload
                verdict = "pass" if present_p >= 0.5 and achieved_p >= 0.5 else "fail"
                result = JevEvaluationResult(
                    verdict, result.confidence,
                    min(present_p, achieved_p),
                    answers, result.reasons,
                    cost=result.cost, input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    is_fallback=False, model=result.model,
                    cache_hit=result.cache_hit)
                cannot = present_p < 0.5 or achieved_p < 0.5
            structural = self._account(
                result, site=site, task_id=task_id, reservation=reservation)
            structural["cannot_complete"] = bool(cannot)
            structural["missing_artifacts"] = missing
            return result, structural
        except ProviderUsageUnknown as exc:
            self._settle_cancelled(reservation, exc)
            raise
        except ToolCancelled as exc:
            self._settle_cancelled(reservation, exc)
            raise
        except ProviderSpendLimitError as exc:
            self._release_after_provider_limit(reservation, exc, task_id=task_id)
            raise
        except HarnessError as exc:
            self._release(reservation)
            post_dispatch = dispatched and self._sent(reservation)
            answers = {
                "named_artifacts_present": 1.0,
                "goal_achieved": 0.5,
                "artifacts": artifacts_payload,
            }
            fallback = JevEvaluationResult(
                "pass", 0.0, 0.5, answers, [str(exc)],
                is_fallback=post_dispatch, model=self.evaluator.model,
                fallback_reason="transport_failure" if post_dispatch else None)
            if post_dispatch:
                structural = self._account(
                    fallback, site=site, task_id=task_id)
            else:
                # Refused before dispatch: leave (deduped) ledger evidence.
                self._record_refusal(
                    str(exc), code=_refusal_reason(exc), site=site,
                    task_id=task_id)
                structural = self._structural(fallback, site)
            structural["cannot_complete"] = True
            structural["missing_artifacts"] = missing
            structural["reason"] = str(exc)
            return fallback, structural

    # #309: the HUL scope evaluator family is owned by harness/jev_scope.py.
    # The class keeps these names -- the owner's own functions, by identity --
    # for the callers and tests that reach the family through JevPolicy.
    _scope_noul = staticmethod(scope_noul)
    _scope_score = staticmethod(scope_score)
    _scope_choice = staticmethod(scope_choice)
    _scope_determination = staticmethod(scope_determination)
    _scope_text = staticmethod(scope_text)
    _scope_state_facts = staticmethod(scope_state_facts)

    def evaluate_scope(self, mission_state, *, site: str = HUL_SCOPE_SITE,
                       task_id: Optional[str] = None,
                       node_id: Optional[str] = None,
                       max_input_tokens: int = JEV_MAX_INPUT_TOKENS):
        """HUL-C: mission scope gate -- delegated to the family owner.

        This method is the construction path the callers already use; the
        typed inputs, the determination and the fail-closed envelope live in
        :func:`harness.jev_scope.evaluate_scope`. The policy instance is
        passed in, so dispatch, spend, settlement and ledger semantics stay
        in this one owner.
        """
        return _evaluate_scope(
            self, mission_state, site=site, task_id=task_id, node_id=node_id,
            max_input_tokens=max_input_tokens, refusal_reason=_refusal_reason)

    _issue_sort_text = staticmethod(issue_sort_text)
    _issue_sort_empty_combo = staticmethod(issue_sort_empty_combo)
    _issue_sort_combo = staticmethod(issue_sort_combo)

    def evaluate_issue_sort(self, state, pack, *, site: str = "issue_sort",
                            task_id: Optional[str] = None,
                            node_id: Optional[str] = None,
                            max_input_tokens: int = JEV_MAX_INPUT_TOKENS):
        """Sort an issue into an operator-declared bucket -- delegated.

        This method is the construction path the callers already use; the
        0-hallucination rules and the fail-closed envelope live in
        :func:`harness.jev_issue_sort.evaluate_issue_sort`. The policy
        instance is passed in, so dispatch, spend, settlement and ledger
        semantics stay in this one owner.
        """
        return _evaluate_issue_sort(
            self, state, pack, site=site, task_id=task_id, node_id=node_id,
            max_input_tokens=max_input_tokens, refusal_reason=_refusal_reason)

    _log_item_text = staticmethod(log_item_text)
    _log_judgment = staticmethod(log_judgment)

    def evaluate_log_item(self, state, pack, *, site=LOG_FACTOR_SITE,
                          task_id: Optional[str] = None,
                          node_id: Optional[str] = None,
                          max_input_tokens: int = JEV_MAX_INPUT_TOKENS):
        """Jev audit of one log item -- delegated to the family owner.

        This method is the construction path the callers already use; the
        0-hallucination rules and the fail-closed envelope live in
        :func:`harness.jev_log.evaluate_log_item`. The policy instance is
        passed in, so dispatch, spend, settlement and ledger semantics stay
        in this one owner.
        """
        return _evaluate_log_item(
            self, state, pack, site=site, task_id=task_id, node_id=node_id,
            max_input_tokens=max_input_tokens, refusal_reason=_refusal_reason)

    _repo_element_text = staticmethod(repo_element_text)
    _repo_judgment = staticmethod(repo_judgment)

    def evaluate_repo_summary(self, state, pack, *, site=REPO_SUMMARY_SITE,
                              task_id: Optional[str] = None,
                              node_id: Optional[str] = None,
                              max_input_tokens: int = JEV_MAX_INPUT_TOKENS):
        """Judge ONE repo element against the operator pack -- delegated.

        This method is the construction path the callers already use; the
        0-hallucination rules and the fail-closed envelope live in
        :func:`harness.jev_repo.evaluate_repo_summary`. The policy instance is
        passed in, so dispatch, spend, settlement and ledger semantics stay
        in this one owner.
        """
        return _evaluate_repo_summary(
            self, state, pack, site=site, task_id=task_id, node_id=node_id,
            max_input_tokens=max_input_tokens, refusal_reason=_refusal_reason)
    _route_query_text = staticmethod(route_query_text)

    def evaluate_model_route(self, state, pack, *, site: str = ROUTE_QUERY_SITE,
                             task_id: Optional[str] = None,
                             node_id: Optional[str] = None,
                             max_input_tokens: int = JEV_MAX_INPUT_TOKENS):
        """Route a query onto the declared model ladder -- delegated.

        This method is the construction path the callers already use; the
        0-hallucination rules, the confidence-aware acceptance and the
        fail-closed envelope live in
        :func:`harness.jev_route.evaluate_model_route`. The policy instance is
        passed in, so dispatch, spend, settlement and ledger semantics stay
        in this one owner.
        """
        return _evaluate_model_route(
            self, state, pack, site=site, task_id=task_id, node_id=node_id,
            max_input_tokens=max_input_tokens, refusal_reason=_refusal_reason)
    # #309: the JEV-BAR phase-completion evaluator family has its own owner
    # module. The class keeps the family's helpers as its compatibility
    # surface (the same objects, not copies) and the public method as the
    # construction path the callers already use; the policy instance is passed
    # to the owner, so dispatch, spend, settlement and ledger semantics stay in
    # this one owner.
    _completion_state_text = staticmethod(completion_state_text)
    _completion_judgment = staticmethod(completion_judgment)

    def evaluate_phase_completion(self, state, pack, *, site=PHASE_COMPLETION_SITE,
                                  task_id: Optional[str] = None,
                                  node_id: Optional[str] = None,
                                  max_input_tokens: int = JEV_MAX_INPUT_TOKENS):
        """Judge one mission phase's evidence against the operator
        phase-completion sentiment pack (JEV-BAR) -- delegated.

        This method is the construction path the callers already use; the
        0-hallucination rules and the fail-closed envelope live in
        :func:`harness.jev_phase_completion.evaluate_phase_completion`. The
        policy instance is passed in, so dispatch, spend, settlement and
        ledger semantics stay in this one owner.
        """
        return _evaluate_phase_completion(
            self, state, pack, site=site, task_id=task_id, node_id=node_id,
            max_input_tokens=max_input_tokens, refusal_reason=_refusal_reason)

    # #309: the 4-dimensional self-audit evaluator family has its own owner
    # module. The class keeps the family's helper as its compatibility surface
    # (the same object, not a copy) and the public method as the construction
    # path the callers already use; the policy instance is passed to the
    # owner, so dispatch, spend, settlement and ledger semantics stay in this
    # one owner.
    _audit_dimension_text = staticmethod(audit_dimension_text)

    def evaluate_audit_dimensions(
        self,
        dimension_evidence: Dict[str, Any],
        pack: Any = None,
        *,
        site: str = AUDIT_DIMENSIONS_SITE,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Evaluate the 4 self-audit dimensions with Jev as the authoritative
        gate -- delegated.

        This method is the construction path the callers already use; the
        0-hallucination rules and the fail-closed envelope live in
        :func:`harness.jev_audit_dimensions.evaluate_audit_dimensions`. The
        policy instance is passed in, so dispatch, spend, settlement and
        ledger semantics stay in this one owner.
        """
        return _evaluate_audit_dimensions(
            self, dimension_evidence, pack, site=site, task_id=task_id,
            max_input_tokens=JEV_MAX_INPUT_TOKENS,
            refusal_reason=_refusal_reason)

    def evaluate_vision_assessment(
            self, state: Any, *, task_id: Optional[str] = None, pack: Any = None):
        """Run the one-request HV-0 assessment through the shared policy owner.

        The result is advisory design evidence only. It has no phase,
        readiness, or completion authority. Any preflight or response failure
        leaves every category unassessed.
        """
        pack_doc = validate_vision_assessment_pack(
            DEFAULT_VISION_ASSESSMENT_PACK if pack is None else pack)
        questions = vision_assessment_question_pack(pack_doc)
        model_name = getattr(self.evaluator, "model", None)
        if not isinstance(model_name, str) or not model_name.strip():
            model_name = "jev-latest"
        # Bound before the try so the refusal path leaves no reading of an
        # unset name; the only path that dispatches is the one that set it.
        sanitized_state: Any = None
        try:
            sanitized_state = sanitize_vision_state(state)
            metrics = vision_assessment_preflight(
                sanitized_state, model_name, pack_doc)
        except (TypeError, ValueError) as exc:
            metrics = {
                "payload_outline": {}, "payload_utf8_bytes": 0,
                "estimated_input_tokens": 0,
                "estimated_state_longest_question_tokens": 0,
                "request_margin_tokens": VISION_ASSESSMENT_MAX_REQUEST_TOKENS,
                "state_longest_question_margin_tokens": VISION_ASSESSMENT_MAX_STATE_QUESTION_TOKENS,
                "fits_context": False,
            }
            refusal_reason = "assessment state is invalid: " + str(exc)
        else:
            refusal_reason = None

        category_ids = list(pack_doc["categories"])
        categories: Dict[str, Optional[VisionCategoryAssessment]] = {
            category_id: None for category_id in category_ids
        }
        threshold = float(pack_doc["confidence_threshold"])

        def usage_source(result=None):
            if result is None:
                return "unavailable"
            if result.input_tokens_observed and result.output_tokens_observed:
                return "actual"
            if result.input_tokens_observed or result.output_tokens_observed:
                return "actual_partial"
            return "unavailable"

        def event_metadata(result_state: str, fallback_state: str,
                           result=None) -> Dict[str, Any]:
            return {
                "capability": VISION_ASSESSMENT_SITE,
                "pack_id": VISION_ASSESSMENT_PACK_ID,
                "pack_version": VISION_ASSESSMENT_PACK_VERSION,
                "result_state": result_state,
                "fallback_state": fallback_state,
                "observed_model": (result.model if result
                                   and result.model_observed else None),
                "model_observed": bool(result and result.model_observed),
                "usage_source": usage_source(result),
                "cost_source": ("actual_input" if result
                                and result.input_tokens_observed else
                                "estimated_input" if result else "unavailable"),
                "input_tokens_observed": bool(
                    result and result.input_tokens_observed),
                "output_tokens_observed": bool(
                    result and result.output_tokens_observed),
                "estimated_input_tokens": int(metrics["estimated_input_tokens"]),
                "payload_utf8_bytes": int(metrics["payload_utf8_bytes"]),
                "question_count": len(questions),
                "request_margin_tokens": int(metrics["request_margin_tokens"]),
                "state_longest_question_margin_tokens": int(
                    metrics["state_longest_question_margin_tokens"]),
            }

        def make_envelope(status: str, *, result=None,
                          reasons: Optional[List[str]] = None,
                          perfect: bool = False) -> VisionAssessmentEnvelope:
            source = usage_source(result)
            return VisionAssessmentEnvelope(
                status=status,
                pack_id=VISION_ASSESSMENT_PACK_ID,
                pack_version=VISION_ASSESSMENT_PACK_VERSION,
                confidence_threshold=threshold,
                model=(result.model if result and result.model_observed else None),
                model_observed=bool(result and result.model_observed),
                fallback_state=("not_dispatched" if result is None else
                                "not_used" if not result.is_fallback else "fallback"),
                usage_source=source,
                input_tokens=(int(result.input_tokens)
                              if result and result.input_tokens_observed else None),
                output_tokens=(int(result.output_tokens)
                               if result and result.output_tokens_observed else None),
                estimated_input_tokens=int(metrics["estimated_input_tokens"]),
                estimated_state_longest_question_tokens=int(
                    metrics["estimated_state_longest_question_tokens"]),
                payload_utf8_bytes=int(metrics["payload_utf8_bytes"]),
                request_margin_tokens=int(metrics["request_margin_tokens"]),
                state_longest_question_margin_tokens=int(
                    metrics["state_longest_question_margin_tokens"]),
                cost_usd=(float(result.cost or 0.0) if result
                          and result.input_tokens_observed else
                          jev_cost(int(metrics["estimated_input_tokens"]))
                          if result else 0.0),
                cost_source=("actual_input" if result
                             and result.input_tokens_observed else
                             "estimated_input" if result else "unavailable"),
                perfect=perfect,
                categories=categories,
                payload_outline=dict(metrics["payload_outline"]),
                reasons=list(reasons or []),
            )

        def refuse(reason: str):
            self._record_refusal(
                reason, site=VISION_ASSESSMENT_SITE, task_id=task_id,
                event_metadata=event_metadata("unassessed", "not_dispatched"))
            return make_envelope("unassessed", reasons=[reason])

        if refusal_reason:
            return refuse(refusal_reason)
        if not metrics["fits_context"]:
            return refuse("full assessment request exceeds a published context limit")
        if self.ledger is None:
            return refuse("autonomy ledger unavailable; assessment not dispatched")
        if not self.keyed:
            return refuse("TypeSafe key unavailable; assessment not dispatched")
        if not callable(getattr(self.evaluator, "evaluate_once", None)):
            return refuse("one-attempt TypeSafe evaluator is unavailable")
        transport = getattr(self.evaluator, "transport", None)
        if not callable(getattr(transport, "post_once", None)):
            return refuse("one-attempt TypeSafe transport is unavailable")
        reserve_cost = jev_cost(int(metrics["estimated_input_tokens"]))
        if reserve_cost > HARD_MAX_COST:
            return refuse("estimated assessment reserve exceeds HARD_MAX_COST")

        reservation = None
        try:
            reservation = self._preflight(
                site=VISION_ASSESSMENT_SITE,
                max_input_tokens=int(metrics["estimated_input_tokens"]),
                eager=True)
        except HarnessError as exc:
            return refuse(str(exc))

        try:
            result = self.evaluator.evaluate_once(sanitized_state, questions)
        except ProviderUsageUnknown as exc:
            self._settle_cancelled(reservation, exc)
            raise
        except ToolCancelled as exc:
            self._settle_cancelled(reservation, exc)
            raise
        except ProviderSpendLimitError as exc:
            self._release_after_provider_limit(reservation, exc, task_id=task_id)
            raise
        except Exception as exc:
            # An injected evaluator should not turn an exception into an
            # implicit fallback score; record the dispatched attempt once.
            result = JevEvaluationResult(
                "fail", 0.0, 0.0, {},
                ["TypeSafe evaluation failed (" + type(exc).__name__ + ")"],
                cost=0.0, input_tokens=0, output_tokens=0,
                is_fallback=False, model=None)

        assessed = False
        perfect = False
        reasons = list(result.reasons or [])
        if result.is_fallback:
            reasons = ["fallback result cannot assess the vision"]
        elif not result.model_observed:
            reasons = ["response did not include an observed model identity"]
        elif not result.usage_observed:
            reasons = ["response did not include complete observed token usage"]
        else:
            try:
                validated = validate_vision_assessment_answers(
                    result.answers, pack_doc)
            except (TypeError, ValueError) as exc:
                reasons = ["assessment response is invalid: " + str(exc)]
            else:
                assessed = True
                for category_id, spec in pack_doc["categories"].items():
                    answer = validated[category_id]
                    probabilities = answer["probabilities"]
                    top_probability = max(probabilities.values())
                    # A tie deliberately chooses the lower level ordinal.
                    selected = min(
                        int(level) for level, probability in probabilities.items()
                        if probability == top_probability)
                    review_required = answer["confidence"] < threshold
                    buckets = spec["improvement_buckets"]
                    actions = spec["improvement_actions"]
                    bucket = buckets[selected] if selected < len(buckets) else None
                    action = actions[selected] if selected < len(actions) else None
                    categories[category_id] = VisionCategoryAssessment(
                        score=answer["score"], selected_level=selected,
                        selected_score_10=round(
                            10.0 * selected / (len(spec["levels"]) - 1), 2),
                        probabilities=probabilities,
                        confidence=answer["confidence"],
                        evidence_refs=list(spec["evidence_refs"]),
                        improvement_bucket=bucket,
                        suggested_next_action=action,
                        review_required=review_required)
                perfect = all(
                    category is not None
                    and category.selected_level == len(
                        pack_doc["categories"][category_id]["levels"]) - 1
                    and category.confidence >= threshold
                    and category.improvement_bucket is None
                    and not category.review_required
                    for category_id, category in categories.items())

        metadata = event_metadata(
            "assessed" if assessed else "unassessed",
            "not_used" if not result.is_fallback else "fallback", result)
        # Nothing was sent (breaker open, no key): it costs nothing. Only a
        # call that may have reached the wire with unobserved usage settles
        # at the conservative estimate.
        settlement_cost = (
            float(result.cost or 0.0)
            if result.input_tokens_observed or result.is_fallback
            else jev_cost(int(metrics["estimated_input_tokens"]))
        )
        self._account(
            result, site=VISION_ASSESSMENT_SITE, task_id=task_id,
            reservation=reservation, settlement_cost=settlement_cost,
            event_metadata=metadata,
            preserve_event_on_settlement_error=True)
        settlement_error = metadata.get("settlement_error")
        if settlement_error:
            assessed = False
            perfect = False
            reasons = ["spend settlement failed after dispatch: " + settlement_error]
            categories = {category_id: None for category_id in category_ids}
        return make_envelope(
            "assessed" if assessed else "unassessed", result=result,
            reasons=reasons, perfect=bool(assessed and perfect))

    def evaluate_typed_pack(self, state, questions, *, site: str,
                            task_id: Optional[str] = None,
                            node_id: Optional[str] = None,
                            max_input_tokens: int = JEV_MAX_INPUT_TOKENS,
                            fallback_reason: str = "unkeyed Jev judgment is unavailable"):
        """Dispatch one typed pack through the shared budget and ledger owner."""
        if not self.keyed:
            result = JevEvaluationResult(
                "fail", 0.0, 0.0, {},
                [fallback_reason],
                is_fallback=True, model=self.evaluator.model,
                fallback_reason=self._no_key_reason())
            structural = self._account(
                result, site=site, task_id=task_id, node_id=node_id)
            return result, structural
        reservation = None
        try:
            reservation = self._preflight(
                site=site, max_input_tokens=max_input_tokens)
            result = self.evaluator.evaluate(state, questions)
            structural = self._account(
                result, site=site, task_id=task_id, node_id=node_id,
                reservation=reservation)
            reservation = None
            return result, structural
        except ProviderUsageUnknown as exc:
            self._settle_cancelled(reservation, exc)
            raise
        except ToolCancelled as exc:
            self._settle_cancelled(reservation, exc)
            raise
        except ProviderSpendLimitError as exc:
            self._release_after_provider_limit(reservation, exc, task_id=task_id)
            raise
        except HarnessError as exc:
            self._release(reservation)
            return self._record_refusal(
                str(exc), site=site, task_id=task_id, node_id=node_id)

    def evaluate_site_reachability(self, state, *, task_id: Optional[str] = None,
                                   max_input_tokens: int = 512):
        """Ask one bounded Jev Noul whether a probe received an HTTPS response."""
        return self.evaluate_typed_pack(
            state, site_reachability_question_pack(),
            site=SITE_REACHABILITY_SITE, task_id=task_id,
            max_input_tokens=max_input_tokens,
            fallback_reason="unkeyed Jev cannot judge site reachability")

    def evaluate_request_workflow(self, state, *, task_id: Optional[str] = None,
                                  max_input_tokens: int = 512):
        """Choose answer/simple-action/plan for a freeform request candidate."""
        return self.evaluate_typed_pack(
            state, request_workflow_question_pack(),
            site=REQUEST_WORKFLOW_SITE, task_id=task_id,
            max_input_tokens=max_input_tokens,
            fallback_reason="unkeyed Jev cannot select a request workflow")

    def evaluate_provision(self, state, questions, *, site: str = PROVISION_SITE,
                           task_id: Optional[str] = None,
                           node_id: Optional[str] = None,
                           max_input_tokens: int = JEV_MAX_INPUT_TOKENS):
        """Run a provisioning question pack through shared spend and ledger."""
        return self.evaluate_typed_pack(
            state, questions, site=site, task_id=task_id, node_id=node_id,
            max_input_tokens=max_input_tokens,
            fallback_reason="unkeyed: provisioning falls back to the deterministic plan")

    def evaluate_economics_route(self, state, *, task_id: Optional[str] = None,
                                 max_input_tokens: int = 512) -> Dict[str, Any]:
        """Advisory EV-3 Jev tier-routing judgment (DF-EV-6).

        Dispatches ``packs/economics_route.pack.json`` through the shared
        budget and ledger owner when keyed, and always computes the
        deterministic :func:`~harness.routing_table.classify_task_tier`
        baseline. Because EV-3 is advisory until 30 real tasks prove >=10%
        better accuracy, ``effective_tier`` stays deterministic unless
        explicitly promoted, while ``advisory_tier`` and ``agreement``
        record Jev's typed judgment.
        """
        from .routing_table import TIER_ORDER, classify_task_tier, get_tier_route

        prompt = ""
        target_files: List[str] = []
        if isinstance(state, dict):
            prompt = str(state.get("prompt") or state.get("instruction") or "")
            raw_files = state.get("target_files") or state.get("files") or []
            if isinstance(raw_files, (list, tuple)):
                target_files = [str(f) for f in raw_files]
        else:
            prompt = str(state or "")

        deterministic_tier = classify_task_tier(prompt, target_files=target_files)
        result, structural = self.evaluate_typed_pack(
            {"prompt": prompt[:1200], "target_files": target_files[:15]},
            economics_route_question_pack(),
            site=ECONOMICS_ROUTE_SITE,
            task_id=task_id,
            max_input_tokens=max_input_tokens,
            fallback_reason="unkeyed: economics_route uses deterministic classify_task_tier",
        )
        answers = result.answers if isinstance(result.answers, dict) else {}
        raw_tier = answers.get("tier")
        if isinstance(raw_tier, dict):
            raw_tier = raw_tier.get("choice") or raw_tier.get("value")
        advisory_tier = (
            str(raw_tier) if str(raw_tier) in TIER_ORDER else deterministic_tier
        )
        confident = (
            not result.is_fallback
            and float(result.confidence or 0.0) >= float(getattr(self, "min_confidence", 0.70) or 0.70)
            and str(raw_tier) in TIER_ORDER
        )
        route = get_tier_route(deterministic_tier)
        return {
            "site": ECONOMICS_ROUTE_SITE,
            "mode": "advisory",
            "effective_tier": deterministic_tier,
            "deterministic_tier": deterministic_tier,
            "advisory_tier": advisory_tier,
            "agreement": advisory_tier == deterministic_tier,
            "confident": confident,
            "confidence": float(result.confidence or 0.0),
            "is_fallback": bool(result.is_fallback),
            "answers": dict(answers),
            "route": route,
            "structural": structural,
        }

    @staticmethod
    def attach(envelope: Dict[str, Any], structural: Optional[Dict[str, Any]]):
        """Attach the stable structural block without changing status."""
        if structural is not None:
            envelope["structural"] = dict(structural)
        return envelope


def policy_for(settings, *, transport=None, governor=None, ledger=None,
               evaluator=None, **options) -> JevPolicy:
    """Construct the shared policy at a session composition boundary.

    ``options`` are the policy's resilience knobs (``breaker_threshold``,
    ``breaker_cooldown``, ``clock``); omit them for the defaults.
    """
    return JevPolicy(
        settings, transport=transport, governor=governor,
        ledger=ledger, evaluator=evaluator, **options,
    )
