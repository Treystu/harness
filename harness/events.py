"""Typed progress event stream: the ONE owner of live run telemetry.

Every lane used to speak only through human-readable stderr
(``output.eprint``). That is fine for a human at a terminal, but a UI (the
web server, an MCP host, a wrapper script) cannot parse prose it does not
own. This module gives every lane a second, structured voice: typed JSON
events fanned out to registered sinks.

    {"ts": 1789316400.1, "seq": 7, "type": "panel_call",
     "task_id": "a1b2c3d4", "model": "google/gemma-4-31b-it:free"}

Design rules:

- **Advisory only.** Events are telemetry, never control flow: no lane may
  branch on the bus, and the bus must never change a run's outcome. A broken
  sink is dropped (with one audible stderr warning), never raised into the
  caller's lane.
- **Zero-cost when nobody listens.** With no sinks registered (the default
  CLI behavior), ``emit`` returns before touching the clock -- progress
  events cost nothing for plain CLI runs.
- **Sinks are callables taking one dict.** ``add_jsonl_sink`` wires the
  common case: append-only JSONL on disk (the ``--events FILE`` flag), the
  shape a file-tailing UI or the future web server's SSE bridge consumes.
- **Thread-safe.** Panel seats run concurrently; seq assignment and sink
  iteration happen under one lock. Sinks themselves are invoked under that
  lock -- keep sinks fast; the JSONL sink buffers and flushes per line.

Event vocabulary (one place, so producers stay consistent):

  preflight        worst-case cost reserved before any call
  attempt_start    one model attempt begins (apply lane)
  panel_call       one panel seat begins
  panel_vote       one panel seat produced a usable vote
  judge_call       judge synthesis begins
  judge_result     judge synthesis finished (status mirrors the envelope)
  rotation         a model is being replaced: reason is machine-readable
  readiness        forced self-check verdict (confident|defer)
  consent_request  a consent probe begins
  consent_result   the parsed sovereign decision (accept/decline/defer/redirect)
  gate_start       verification gate begins
  gate_end         verification gate finished (passed bool, rc)
  escalation_rung  an escalation ladder rung begins
  spend_check      key verified / budget state (never the key label)
  bench_task       one bench task starts/finishes
  terminal         the run reached a terminal status

``task_id`` is optional (some lanes, e.g. the reasoning retry inside chat(),
have no task context); consumers must tolerate its absence.
"""
import json
import sys
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar, copy_context

# Guard against pathological sink counts; a UI registers one or two sinks.
MAX_SINKS = 8

_lock = threading.Lock()
_sinks = []
_seq = 0

# Module-global for a one-time broken-sink warning; assigned only at module
# level or inside emit() via the global statement (ruff F823 guard).
_warned_sink = None

_task_id = ContextVar("harness_event_task_id", default=None)
_cancel_check = ContextVar("harness_event_cancel_check", default=None)
_provider_request = ContextVar("harness_provider_request", default=None)
_terminal_spend_limit = ContextVar("harness_terminal_spend_limit", default=None)


@contextmanager
def task_context(task_id, cancel_check=None):
    """Attach run identity and cancellation to one run's execution context."""
    token = _task_id.set(task_id)
    cancel_token = _cancel_check.set(cancel_check)
    terminal_token = _terminal_spend_limit.set({})
    try:
        yield
    finally:
        _terminal_spend_limit.reset(terminal_token)
        _cancel_check.reset(cancel_token)
        _task_id.reset(token)


def current_cancel_check():
    """Return the active run's cancellation check, if this thread has one."""
    return _cancel_check.get()


def current_task_id():
    """Return the active run identity for durable terminal receipts."""
    return _task_id.get()


def mark_provider_spend_limit(error):
    """Latch provider exhaustion for this operation and its workers.

    The latch names the backend that refused (#538): one dry account must
    not stop a request that has another configured backend to fail over to.
    """
    state = _terminal_spend_limit.get()
    if state is not None and "error" not in state:
        state["error"] = {
            "http_status": getattr(error, "http_status", None),
            "model": getattr(error, "model", None),
            "cause": getattr(error, "cause", None),
        }


def _latch_blocks(latched: dict, model) -> bool:
    """True when a latched refusal also applies to the requested ``model``.

    Different providers never block each other. Within one provider, a
    funding refusal blocks only its paid routes (a $0 route still serves)
    and a route/model restriction blocks only that model.
    """
    from .availability import ACCOUNT_FUNDING, is_free_model, provider_of

    latched_model = latched.get("model")
    if not latched_model or not model:
        # No backend identity was recorded: keep the whole-run stop, which is
        # the pre-#538 conservative behaviour.
        return True
    if str(latched_model) == str(model):
        return True
    if provider_of(latched_model) != provider_of(model):
        return False
    if latched.get("cause") == ACCOUNT_FUNDING and not is_free_model(model):
        return True
    return False


def raise_if_provider_spend_limited(*, known_cost=0.0, model=None):
    """Prevent queued or retrying calls to a backend that already refused."""
    state = _terminal_spend_limit.get()
    if state is not None and "error" in state:
        if model is not None and not _latch_blocks(state["error"], model):
            # A different backend is still worth trying: this is failover,
            # not a re-dispatch into the refused account (#538).
            return
        from .provider_errors import ProviderSpendLimitError
        raise ProviderSpendLimitError(
            "a sibling request already exhausted the provider spend limit",
            http_status=state["error"].get("http_status"),
            known_cost=known_cost,
            model=state["error"].get("model"),
            # Forward the latched cause: reconstructing a restriction as the
            # default account-funding cause would widen it to every paid model
            # on the provider in the availability ledger.
            cause=state["error"].get("cause") or "unknown",
        )


def reset_provider_spend_limit_latch():
    """Reset the terminal spend-limit latch for this execution context."""
    state = _terminal_spend_limit.get()
    if state is not None:
        state.clear()


def reset_executor_spend_limit(executor):
    """Reset the executor's terminal spend-limit latch so reuse succeeds."""
    if hasattr(executor, "_harness_terminal_spend_limit"):
        executor._harness_terminal_spend_limit = {}


def submit_with_context(executor, fn, *args, **kwargs):
    """Submit one worker with this run's event and cancellation context."""
    context = copy_context()
    state = _terminal_spend_limit.get()
    if state is None:
        # CLI and library fan-outs may not have a server task context. Give
        # every worker submitted to this pool one shared terminal-stop latch.
        state = getattr(executor, "_harness_terminal_spend_limit", None)
        if state is None:
            state = {}
            if hasattr(executor, "__dict__"):
                executor._harness_terminal_spend_limit = state

    def invoke():
        token = _terminal_spend_limit.set(state)
        try:
            return fn(*args, **kwargs)
        finally:
            _terminal_spend_limit.reset(token)

    return executor.submit(context.run, invoke)


@contextmanager
def provider_request_context(request_id, model=None, attempt=None):
    """Correlate transport-level retries with their logical model request."""
    token = _provider_request.set({
        "request_id": request_id,
        "model": model,
        "attempt": attempt,
    })
    try:
        yield
    finally:
        _provider_request.reset(token)


def current_provider_request():
    """Return a copy of the current logical provider request metadata."""
    return dict(_provider_request.get() or {})


@contextmanager
def cancellation_context(cancel_check):
    """Bind a cancellation signal without changing the current task id."""
    token = _cancel_check.set(cancel_check)
    try:
        yield
    finally:
        _cancel_check.reset(token)



def emit(event_type, **fields):
    """Emit one event to every registered sink. Never raises.

    With no sinks (the default CLI run) this is a single ``if`` -- the
    free-tier guarantee that telemetry changes nothing about cost or outcome
    includes not even touching the clock.
    """
    if not _sinks:
        return
    global _seq, _warned_sink
    with _lock:
        _seq += 1
        event = {"ts": time.time(), "seq": _seq, "type": event_type}
        if fields.get("task_id") is None and _task_id.get() is not None:
            fields["task_id"] = _task_id.get()
        event.update(fields)
        dead = []
        for sink in _sinks:
            try:
                sink(event)
            except Exception as exc:  # a broken sink must not break a run
                if _warned_sink is not sink:
                    print(f"[events] sink dropped ({exc})", file=sys.stderr)
                    _warned_sink = sink
                dead.append(sink)
        for sink in dead:
            _sinks.remove(sink)


def add_sink(sink):
    """Register a sink (callable taking one event dict). Returns the sink on
    success, or None when the registration was refused (full, duplicate)."""
    with _lock:
        if sink in _sinks or len(_sinks) >= MAX_SINKS:
            return None
        _sinks.append(sink)
    return sink


def remove_sink(sink):
    with _lock:
        if sink in _sinks:
            _sinks.remove(sink)
            return True
    return False


def sink_count():
    with _lock:
        return len(_sinks)


class JsonlSink:
    """Append one JSON object per line to a file. Opened lazily on the first
    event so ``--events`` never creates a file for a run that emits nothing;
    flushed per line so a tailing UI sees progress live."""

    def __init__(self, path):
        self.path = path
        self._fh = None

    def __call__(self, event):
        if self._fh is None:
            self._fh = open(self.path, "a", encoding="utf-8")
        self._fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._fh.flush()

    def close(self):
        if self._fh is not None:
            self._fh.close()
            self._fh = None


def add_jsonl_sink(path):
    """Wire a JSONL file sink (the ``--events FILE`` flag). Returns the sink,
    or None when a sink for that exact path is already registered."""
    with _lock:
        if any(isinstance(s, JsonlSink) and s.path == path for s in _sinks):
            return None
    return add_sink(JsonlSink(path))
