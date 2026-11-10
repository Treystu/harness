"""#480 BR2 — the interactive-session hand and its bus-backed consumer.

BR1 gave the observation side a registration surface
(:func:`driver_core.osal.register_capture_backend`): a non-desktop driver
can resolve the owner display through a backend that lives outside
``driver_core``. This module is the first backend that earns that
registration: the hand that runs *inside* the interactive Windows
session, and the consumer the non-desktop driver on the other end holds.

Layout (a private ledger: one directory, no server)::

    <root>/requests/<request-id>.json   what the driver asked for
    <root>/results/<request-id>.json    what the hand answered

The driver posts a request; the hand polls, answers exactly once, and the
driver reads its result. Files appear atomically (temporary file plus
``os.replace``), so a poller never reads a half-written record. One hand
owns one root: a second hand on the same root would double-answer, and
this module does not arbitrate that -- run one hand per root.

Session states, reported by the hand and carried on every result:

* ``interactive`` -- a user session is present; capture and describe run.
* ``locked`` -- the workstation is locked; the request is refused **and no
  frame is taken**. This is the LOCK RULE and it is absolute: the locked
  branch never calls the capture callable, so a locked screen cannot leak
  through a plugin, a default, or a refactor.
* ``no-foreground`` -- unlocked, but no foreground window. Capture still
  runs (a fullscreen shot is still a screenshot); describe reports
  whatever the platform reader reports, which on Windows is its own named
  refusal.

What this slice is not (named, not implied): the frame envelope and
``captured_at`` freshness gate are BR3; capture grants, the seat
allowlist, the on-screen indicator and the kill switch are BR5. Results
here carry no grant check and no freshness verdict -- the consumer trusts
the root directory the same way the queue bus trusts its own root.
"""
import json
import os
import re
import time
import uuid

from . import osal
from .errors import OsalError

#: Session states the hand reports. Plain strings, so they survive the
#: JSON round-trip through the ledger without a schema.
INTERACTIVE = "interactive"
LOCKED = "locked"
NO_FOREGROUND = "no-foreground"

#: The two things a driver may ask the hand for. They mirror
#: :data:`driver_core.osal.CAPTURE_KINDS` on purpose: a consumer backend
#: built here must be interchangeable with any other registered backend.
KINDS = ("capture", "describe")

#: How long the consumer waits for the hand before refusing by name.
DEFAULT_TIMEOUT = 30.0

#: Idle poll cadence while the consumer waits. Short enough that a live
#: hand answers inside a step budget, long enough not to spin.
POLL_INTERVAL = 0.05

#: Refusal text the locked branch writes. It names the condition, not the
#: caller: the same string serves the capture half and the describe half.
LOCKED_DETAIL = ("the hand reports the session is locked; "
                 "no frame is taken while locked")

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class HandError(ValueError):
    """A hand request that cannot be honoured, with the reason attached."""


def _checked_id(value):
    text = str(value or "").strip()
    if not _ID.match(text) or text in (".", ".."):
        raise HandError(
            "request_id must be a plain identifier (letters, digits, '.', "
            f"'_', '-'), got {value!r}")
    return text


def _requests_dir(root):
    path = os.path.join(os.path.abspath(root), "requests")
    os.makedirs(path, exist_ok=True)
    return path


def _results_dir(root):
    path = os.path.join(os.path.abspath(root), "results")
    os.makedirs(path, exist_ok=True)
    return path


def _write_json(path, record):
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(record, handle, sort_keys=True)
    os.replace(tmp, path)


def _read_json(path):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def default_session_probe():
    """Report the session state of this machine.

    Windows only in practice: the hand runs in the interactive session,
    and ``OpenInputDesktop`` fails there exactly when the workstation is
    locked, which is the condition the LOCK RULE needs. Any probe error
    fails closed to :data:`LOCKED` -- a broken probe must refuse frames,
    never permit them. Off Windows there is no lock to observe from here,
    so the answer is :data:`INTERACTIVE` and the platform readers speak
    for themselves.
    """
    if osal.platform_name() != "windows":
        return INTERACTIVE
    try:
        import ctypes

        user32 = ctypes.windll.user32
        # DESKTOP_READOBJECTS: enough to test the handle, nothing to draw.
        handle = user32.OpenInputDesktop(0, False, 0x0001)
        if not handle:
            return LOCKED
        try:
            if user32.GetForegroundWindow():
                return INTERACTIVE
            return NO_FOREGROUND
        finally:
            user32.CloseDesktop(handle)
    except Exception:  # noqa: BLE001 - a broken probe refuses, never permits
        return LOCKED


def session_state(probe=None):
    """Return the current session state: interactive, locked, or no-foreground."""
    probe = probe or default_session_probe
    state = probe()
    if state not in (INTERACTIVE, LOCKED, NO_FOREGROUND):
        raise HandError(f"session probe returned {state!r}; expected "
                        f"{INTERACTIVE!r}, {LOCKED!r} or {NO_FOREGROUND!r}")
    return state


def post_capture_request(root, request_id, kind="capture"):
    """Post one request for the hand. Returns the stored record."""
    rid = _checked_id(request_id)
    if kind not in KINDS:
        raise HandError(f"kind must be one of {KINDS}, got {kind!r}")
    record = {"request_id": rid, "kind": kind, "posted_at": time.time()}
    _write_json(os.path.join(_requests_dir(root), f"{rid}.json"), record)
    return record


def pending_requests(root):
    """IDs the driver asked for that the hand has not answered yet, oldest first."""
    try:
        names = os.listdir(_requests_dir(root))
    except FileNotFoundError:
        return []
    try:
        answered = set(os.listdir(_results_dir(root)))
    except FileNotFoundError:
        answered = set()
    pending = sorted(n[:-5] for n in names
                     if n.endswith(".json") and n[:-5] + ".json" not in answered
                     and _ID.match(n[:-5]))
    return pending


def read_result(root, request_id, *, timeout=DEFAULT_TIMEOUT):
    """Read one answered request, waiting up to ``timeout`` seconds.

    Returns the result record, or ``None`` when the hand did not answer
    in time -- a missing hand is a named absence, not an exception.
    """
    rid = _checked_id(request_id)
    path = os.path.join(_results_dir(root), f"{rid}.json")
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        try:
            return _read_json(path)
        except (FileNotFoundError, ValueError):
            if time.monotonic() >= deadline:
                return None
            time.sleep(POLL_INTERVAL)


class CaptureHand:
    """Answer capture requests from inside the interactive session.

    The hand owns one ledger root. Each :meth:`poll_once` answers the
    oldest unanswered request: locked sessions get the named refusal
    without any capture running; everything else runs the injected
    readers (defaulting to :func:`osal.capture_screen` and
    :func:`osal.describe_screen`) and stores what they returned.
    """

    def __init__(self, root, *, session_probe=None, capture=None,
                 describe=None):
        self._root = os.path.abspath(root)
        self._probe = session_probe or default_session_probe
        self._capture = capture or (lambda: osal.capture_screen(max_side=None))
        self._describe = describe or osal.describe_screen

    @property
    def root(self):
        return self._root

    def status(self):
        """The hand's own state report: session state plus queue depth."""
        return {"state": session_state(self._probe),
                "pending": len(pending_requests(self._root))}

    def poll_once(self):
        """Answer the oldest unanswered request, or ``None`` when idle.

        An idle hand is quiet: no event, no heartbeat, no empty result.
        """
        pending = pending_requests(self._root)
        if not pending:
            return None
        rid = pending[0]
        try:
            request = _read_json(
                os.path.join(_requests_dir(self._root), f"{rid}.json"))
        except (FileNotFoundError, ValueError):
            return None
        kind = request.get("kind", "capture")
        state = session_state(self._probe)
        if state == LOCKED:
            # The LOCK RULE: this branch returns before any reader runs.
            # Nothing below this line touches pixels while locked.
            return self._answer(rid, kind, state, None, None, LOCKED_DETAIL)
        if kind == "describe":
            fields, detail = self._safe_describe()
            return self._answer(rid, kind, state, None, fields, detail)
        path, detail = self._safe_capture()
        return self._answer(rid, kind, state, path, None, detail)

    def _safe_capture(self):
        try:
            path, detail = self._capture()
        except OsalError as exc:
            return None, str(exc)
        except Exception as exc:  # noqa: BLE001 - a reader bug is a refusal
            return None, f"hand capture failed: {exc}"
        if path is not None and not isinstance(path, str):
            return None, (f"hand capture returned {type(path).__name__} "
                          f"instead of a path")
        return path, detail if isinstance(detail, str) else str(detail)

    def _safe_describe(self):
        try:
            fields, detail = self._describe()
        except OsalError as exc:
            return None, str(exc)
        except Exception as exc:  # noqa: BLE001 - a reader bug is a refusal
            return None, f"hand describe failed: {exc}"
        if fields is None:
            return None, detail if isinstance(detail, str) else str(detail)
        if not isinstance(fields, dict):
            return None, (f"hand describe returned {type(fields).__name__} "
                          f"instead of a field dict")
        return fields, detail if isinstance(detail, str) else str(detail)

    def _answer(self, rid, kind, state, path, fields, detail):
        record = {"request_id": rid, "kind": kind, "state": state,
                  "detail": detail, "answered_at": time.time()}
        if kind == "describe":
            record["fields"] = fields
        else:
            record["path"] = path
        _write_json(os.path.join(_results_dir(self._root), f"{rid}.json"),
                    record)
        return record


def bus_capture_backend(root, *, name="bridge-bus", platform=None,
                        timeout=DEFAULT_TIMEOUT, request_id_factory=None):
    """Build the consumer backend the non-desktop driver registers.

    The returned record is built by :func:`osal.capture_backend`, so it
    registers through :func:`osal.register_capture_backend` like any
    other backend and :class:`adapters.ScreenSource` resolves through it
    unchanged. Each half posts one request to the hand's ledger and waits
    up to ``timeout`` seconds; an unanswered hand arrives as the same
    named refusal shape the native path returns, never as an exception.
    """
    factory = request_id_factory or (lambda: uuid.uuid4().hex)
    platform = platform or osal.platform_name()
    timeout = max(0.0, timeout)

    def _capture():
        rid = _checked_id(factory())
        post_capture_request(root, rid, "capture")
        result = read_result(root, rid, timeout=timeout)
        if result is None:
            return None, (f"capture hand did not answer within {timeout:g}s; "
                          "the interactive session may be down")
        return result.get("path"), str(result.get("detail", ""))

    def _describe():
        rid = _checked_id(factory())
        post_capture_request(root, rid, "describe")
        result = read_result(root, rid, timeout=timeout)
        if result is None:
            return None, (f"capture hand did not answer within {timeout:g}s; "
                          "the interactive session may be down")
        return result.get("fields"), str(result.get("detail", ""))

    return osal.capture_backend(capture=_capture, describe=_describe,
                                name=name, platform=platform)


def register_bus_capture_backend(root, platform=None, **kwargs):
    """Register the bus consumer for ``platform`` and report it.

    The mirror of :func:`osal.register_native_capture_backend`: where
    that one names the in-repo reader, this one names the hand, so
    :func:`osal.capture_backends` answers honestly about which one the
    next observation will resolve through.
    """
    platform = platform or osal.platform_name()
    backend = bus_capture_backend(root, platform=platform, **kwargs)
    osal.register_capture_backend(platform, backend)
    return backend
