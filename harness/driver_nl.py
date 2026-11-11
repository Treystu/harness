"""One-prompt driver intake for the GUI (#273): plan, confirm, execute.

``POST /api/driver/nl`` speaks in two steps. Without ``confirm`` it returns
a validated action plan and a ``plan_id``; with ``confirm: true`` and that
``plan_id`` it executes the stored plan, emitting the existing
``driver_task_start`` / ``driver_step_start`` / ``driver_step_complete``
events the GUI already renders, so live step status needs no new channel.

Gates, in order: the ``HARNESS_NL_CONTROL`` flag (404 when off), then the
caller (host token or the driver ``DRIVER_TOKEN`` bearer, else 401).
Confirmation binds to the stored plan: a ``plan_id`` without
``confirm: true`` never executes (400), an unknown or expired ``plan_id``
never executes (404), and execution stops at the first failed step. A stored
plan may be cancelled between steps; plans expire after
``PLAN_TTL_SECONDS`` and never survive a server restart (a restart turns the
id into an honest 404).
"""

import os
import secrets
import threading
import time

from driver_core.actions import DEFAULT_VOCABULARY
from harness.errors import HarnessError

#: How long a previewed plan stays confirmable. Short on purpose: the plan
#: names machine mutations, and a confirmation should bind to a fresh look.
PLAN_TTL_SECONDS = 600.0

#: Upper bound on stored plans. Confirmation ids are unguessable, but an
#: unbounded store is still a slow leak; the oldest id goes when full.
MAX_STORED_PLANS = 64

#: Token budget for one planning call. A plan is a short JSON array, not an
#: essay; anything longer fails the parse and is retried never.
NL_PLAN_MAX_TOKENS = 1024


class PlanStore:
    """Thread-safe previewed plans with expiry and a capacity bound."""

    def __init__(self, *, ttl=PLAN_TTL_SECONDS, max_plans=MAX_STORED_PLANS,
                 clock=time.monotonic):
        self._ttl = float(ttl)
        self._max = int(max_plans)
        self._clock = clock
        self._lock = threading.Lock()
        self._plans = {}

    def _prune_locked(self):
        now = self._clock()
        dead = [pid for pid, entry in self._plans.items()
                if now - entry["at"] > self._ttl]
        for pid in dead:
            del self._plans[pid]
        while len(self._plans) > self._max:
            oldest = min(self._plans, key=lambda pid: self._plans[pid]["at"])
            del self._plans[oldest]

    def save(self, user_input, plan):
        """Store a previewed plan; return its unguessable id."""
        plan_id = "nlp_" + secrets.token_urlsafe(16)
        with self._lock:
            self._prune_locked()
            self._plans[plan_id] = {
                "input": user_input, "plan": [dict(s) for s in plan],
                "at": self._clock(), "cancelled": False,
            }
        return plan_id

    def get(self, plan_id):
        """Return ``(input, plan)`` or ``None`` when unknown or expired."""
        with self._lock:
            self._prune_locked()
            entry = self._plans.get(plan_id)
            if entry is None:
                return None
            return entry["input"], [dict(s) for s in entry["plan"]]

    def cancel(self, plan_id):
        """Flag a stored plan cancelled; False when unknown or expired."""
        with self._lock:
            self._prune_locked()
            entry = self._plans.get(plan_id)
            if entry is None:
                return False
            entry["cancelled"] = True
            return True

    def is_cancelled(self, plan_id):
        with self._lock:
            entry = self._plans.get(plan_id)
            return entry is not None and entry["cancelled"]


#: Process-wide previewed plans. Restarting the server drops the ids, which
#: the 404 on an unknown id already covers honestly.
STORE = PlanStore()


def flag_on(environ=None):
    """Whether the host's ``HARNESS_NL_CONTROL`` flag is on. Default off."""
    env = os.environ if environ is None else environ
    return env.get("HARNESS_NL_CONTROL", "").strip().lower() not in (
        "", "0", "false", "no", "off")


def request_authorized(auth_header, *, host_authorized, driver_token):
    """Whether a request may use NL intake: host token or driver bearer."""
    if host_authorized:
        return True
    if not driver_token or not auth_header:
        return False
    supplied = auth_header[len("Bearer "):].strip() \
        if auth_header.startswith("Bearer ") else auth_header.strip()
    import hmac
    return hmac.compare_digest(supplied.encode("utf-8"),
                               driver_token.encode("utf-8"))


def build_planner(*, settings=None):
    """A planner: governed scout-head chat under the plan seam.

    The ladder head is the cheapest rung of the same sliding scale that
    classifies nodes; ``nl_planner.plan`` enforces the ONLY-validated-actions
    contract and the 10s bound. No key and no ladder is a 502 at request
    time, never a silent heuristic plan the operator did not ask for.
    """
    from harness._http import HttpTransport
    from harness.chat import governed_text
    from harness.config import load_settings
    from harness.nl_planner import plan as plan_text
    from harness.session import governor_for
    from harness.waist import resolve_scout_ladder

    resolved = settings if settings is not None else load_settings()
    api_key, gov = governor_for(resolved)
    transport = HttpTransport()
    ladder = resolve_scout_ladder(
        use_free=resolved.use_free,
        custom_frontier=resolved.frontier_model,
        allow_escalation=bool(getattr(resolved, "allow_escalation", False)))

    def chat_fn(prompt):
        last = None
        for model in ladder:
            try:
                content, _cost = governed_text(
                    transport, api_key, gov, model, prompt,
                    NL_PLAN_MAX_TOKENS, label="driver-nl")
                return content
            except HarnessError as exc:
                last = exc
        raise last or HarnessError("driver NL ladder empty")

    def planner(user_input):
        return plan_text(user_input, chat_fn)

    return planner


def build_driver(*, settings=None):
    """An in-process driver with the host's launch mapping applied."""
    from driver_core.config import load_settings as load_driver_settings
    from driver_core.driver import driver_from_settings

    resolved = settings if settings is not None else load_driver_settings()
    resolved = resolved.with_overrides(
        launch_app_enabled=(resolved.launch_app_enabled or flag_on()))
    return driver_from_settings(resolved)


def emit(event_type, **fields):
    """The existing event bus the GUI already polls."""
    from . import events as _events
    _events.emit(event_type, **fields)


def _step_view(step):
    """A plan step plus its declared consequence class for the card."""
    declared = DEFAULT_VOCABULARY.resolve(step["action"])
    return {"action": step["action"], "params": dict(step.get("params") or {}),
            "class": declared.action_class}


def handle(body, *, authorized, planner=None, driver=None, store=None):
    """Serve one ``/api/driver/nl`` request; return ``(status, payload)``.

    ``authorized`` is decided by the server (host token or driver bearer).
    ``planner``/``driver`` default to the live builders; tests inject fakes.
    """
    if not flag_on():
        return 404, {"ok": False,
                     "error": "driver NL intake is off (HARNESS_NL_CONTROL)"}
    if not authorized:
        return 401, {"ok": False, "error": "unauthorized"}
    if not isinstance(body, dict):
        return 400, {"ok": False, "error": "body must be an object"}
    store = store if store is not None else STORE

    cancel_id = body.get("cancel_plan")
    if cancel_id is not None:
        if not isinstance(cancel_id, str) or not cancel_id:
            return 400, {"ok": False,
                         "error": "cancel_plan must be a plan id string"}
        if not store.cancel(cancel_id):
            return 404, {"ok": False,
                         "error": f"unknown or expired plan {cancel_id!r}"}
        return 200, {"ok": True, "status": "cancelled", "plan_id": cancel_id}

    if body.get("confirm") is True:
        plan_id = body.get("plan_id")
        if not isinstance(plan_id, str) or not plan_id:
            return 400, {"ok": False,
                         "error": "confirm:true needs the preview plan_id"}
        found = store.get(plan_id)
        if found is None:
            return 404, {"ok": False,
                         "error": f"unknown or expired plan {plan_id!r}"}
        user_input, plan = found
        return 200, _execute(plan_id, user_input, plan,
                             driver=driver, store=store)

    if "plan_id" in body:
        return 400, {"ok": False,
                     "error": "a stored plan never executes without "
                              "confirm:true (no auto-execution)"}
    user_input = str(body.get("input") or "").strip()
    if not user_input:
        return 400, {"ok": False,
                     "error": "field 'input' is required and must be "
                              "a non-empty string"}
    live_planner = planner if planner is not None else build_planner()
    try:
        plan = live_planner(user_input)
    except HarnessError as exc:
        return 502, {"ok": False,
                     "error": f"driver NL planning failed: {exc}"}
    plan_id = store.save(user_input, plan)
    return 200, {"ok": True, "status": "plan", "plan_id": plan_id,
                 "plan": [_step_view(s) for s in plan],
                 "requires_confirm": True}


def _execute(plan_id, user_input, plan, *, driver, store):
    """Run stored steps; stop at the first failure or cancellation."""
    from driver_core.errors import DriverError
    from driver_core.executor import Consent

    live = driver if driver is not None else build_driver()
    emit("driver_task_start", task_id=plan_id, goal=user_input,
         max_steps=len(plan))
    steps = []
    end = "done"
    for position, step in enumerate(plan, start=1):
        if store.is_cancelled(plan_id):
            end = "cancelled"
            break
        emit("driver_step_start", task_id=plan_id, step=position,
             step_id=f"{plan_id}:{position}", target=step["action"],
             schema="nl-plan")
        view = _step_view(step)
        try:
            _action, checked = live.executor.resolve(
                step["action"], step.get("params") or {})
            consent = Consent(True, step["action"], checked,
                              by="operator:nl-confirm")
            result = live.executor.execute(
                step["action"], checked, consent=consent)
            ok = bool(getattr(result, "ok", False))
            detail = getattr(result, "detail", "") or ""
        except DriverError as exc:
            ok, detail = False, str(exc)
        view["ok"] = ok
        view["detail"] = detail
        steps.append(view)
        emit("driver_step_complete", task_id=plan_id, step=position,
             step_id=f"{plan_id}:{position}", ok=ok)
        if not ok:
            end = "stopped"
            break
    return {"ok": True, "status": end, "plan_id": plan_id, "steps": steps}
