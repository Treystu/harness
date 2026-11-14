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

BR3 is here too, and it is the reason a frame is not just a path. A path
says a picture exists; it does not say *when* it was taken, and a driver
that judges a stale screen is judging a state the machine has already left.
So every answered capture carries a declared **frame envelope**
(:data:`FRAME_SCHEMA`) whose ``captured_at`` is stamped the moment the
reader returned the pixels, and the consumer applies the **freshness gate**
(:func:`check_freshness`) before it hands the path on: a frame older than
``max_age``, stamped in the future (the two clocks disagree), or carrying no
usable stamp at all is refused by name. A refusal is the honest answer --
the driver can retry, and nothing downstream ever sees pixels it cannot date.

What this slice is not (named, not implied): capture grants, the seat
allowlist, the on-screen indicator and the kill switch are BR5. Results
here carry no grant check -- the consumer trusts the root directory the way
the queue bus trusts its own root -- and freshness is the only verdict a
frame carries.
"""
import json
import math
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

#: The frame envelope's schema name and version. Additive and declared: a
#: consumer that does not know this name refuses the frame rather than
#: guessing at the shape of an envelope it has never seen, and a future
#: version bump is how a field is added without one release's consumer
#: misreading another release's hand.
FRAME_SCHEMA = "frame@1"

#: Where the envelope lives on a result record. One key, one owner: the
#: flat ``path`` beside it is BR2's contract and stays for the callers that
#: read it, but the envelope is what a freshness decision reads.
FRAME_FIELD = "frame"

#: The envelope's timestamp. Seconds since the epoch, from the hand's own
#: clock -- the hand is the only process that knows when the pixels existed.
CAPTURED_AT_FIELD = "captured_at"

#: How old a frame may be when the driver reads it. Five seconds because
#: that is the vision verifier's own verdict budget (#272): a frame older
#: than the judgement it feeds has already been overtaken by the screen it
#: was meant to prove. A caller with a different loop declares its own.
DEFAULT_MAX_AGE = 5.0

#: How far a stamp may run ahead of the reader's clock before the gate
#: refuses. Not zero: two clocks on one machine, read microseconds apart,
#: legitimately disagree by a little, and a gate that fails on that noise
#: would refuse every frame. Beyond this the two clocks are not agreeing
#: about *time*, so the age cannot be evaluated at all -- which is a
#: refusal, not a pass.
MAX_CLOCK_LEAD = 1.0

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class HandError(ValueError):
    """A hand request that cannot be honoured, with the reason attached."""


def _is_number(value):
    """A finite real number, and never a ``bool``.

    ``True`` is an ``int`` in Python, and a stamp of ``True`` would age to
    a plausible-looking number instead of being the caller bug it is.
    """
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


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


def frame_envelope(*, path, captured_at, state):
    """The declared envelope for one answered frame.

    Refuses to build an envelope it could not date or place: a stamp that is
    not a finite number is a hand whose clock cannot be trusted, and storing
    it would put an unevaluable frame on the wire looking like a dated one.
    The refusal is raised here, in the hand, rather than left for the driver,
    because the hand is the only side that can still take a fresh frame.
    """
    if not isinstance(path, str) or not path.strip():
        raise HandError(f"a frame needs a path, got {path!r}")
    if not _is_number(captured_at):
        raise HandError(
            "a frame needs a finite numeric captured_at; the hand's clock "
            f"returned {captured_at!r}")
    if state not in (INTERACTIVE, LOCKED, NO_FOREGROUND):
        raise HandError(f"a frame needs a session state, got {state!r}")
    return {"schema": FRAME_SCHEMA, "path": path,
            CAPTURED_AT_FIELD: float(captured_at), "state": state}


def frame_age(frame, *, now=None):
    """How old a frame is, in seconds, or ``None`` when it cannot be dated.

    ``None`` is not zero: a frame with no envelope, an unknown schema or an
    unusable stamp has an *unknown* age, and a caller that treated that as
    fresh would be trusting a frame nothing can vouch for. Only
    :func:`check_freshness` decides; this reports.
    """
    if not isinstance(frame, dict) or frame.get("schema") != FRAME_SCHEMA:
        return None
    captured_at = frame.get(CAPTURED_AT_FIELD)
    if not _is_number(captured_at):
        return None
    return (time.time() if now is None else float(now)) - float(captured_at)


def _checked_max_age(max_age):
    """A caller-declared freshness window, refused if it is not one."""
    if not _is_number(max_age) or max_age < 0:
        raise HandError(
            "max_age must be a finite number of seconds, zero or more; got "
            f"{max_age!r}")
    return float(max_age)


def check_freshness(result, *, max_age=DEFAULT_MAX_AGE, now=None):
    """The freshness gate: ``(ok, detail)`` for one consumer-side result.

    Every refusal names which of the four things went wrong, because they
    call for different operator acts: a stale frame means the loop is too
    slow (retry, or widen ``max_age`` deliberately), a missing envelope
    means the hand predates BR3 (upgrade it), a future stamp means the two
    clocks disagree (fix the clocks -- no window makes it safe), and a bad
    window is the caller's own bug.

    A frame within :data:`MAX_CLOCK_LEAD` of the reader's clock passes: on
    one machine, read microseconds apart, the two clocks are the same clock
    with a little jitter, and a gate that refused that jitter would refuse
    every frame.

    The gate is evaluated only for a result that carries a path. A result
    with no frame -- locked, reader failure, unanswered -- is already a
    named refusal from BR2, and replacing that detail with a freshness
    verdict would hide the condition that actually stopped the capture.
    """
    window = _checked_max_age(max_age)
    if not isinstance(result, dict):
        return False, ("no frame envelope: the hand answered with "
                       f"{type(result).__name__}, which cannot be dated")
    frame = result.get(FRAME_FIELD)
    if not isinstance(frame, dict) or frame.get("schema") != FRAME_SCHEMA:
        return False, (
            "no frame envelope: the result carries no "
            f"{FRAME_SCHEMA} record, so the frame's age cannot be "
            "evaluated; a hand from before the freshness gate must be "
            "upgraded before its frames are used")
    captured_at = frame.get(CAPTURED_AT_FIELD)
    if not _is_number(captured_at):
        return False, (
            "the frame envelope carries no finite numeric "
            f"{CAPTURED_AT_FIELD}, so its age cannot be evaluated")
    reader = time.time() if now is None else float(now)
    age = reader - float(captured_at)
    if age < -MAX_CLOCK_LEAD:
        return False, (
            f"frame is stamped {-age:.3f}s in the future; the hand and the "
            "driver disagree about the clock, so freshness cannot be "
            "evaluated")
    if age > window:
        return False, (f"frame is stale: captured {age:.3f}s ago and the "
                       f"freshness gate allows {window:g}s")
    return True, ""


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
                 describe=None, clock=None):
        self._root = os.path.abspath(root)
        self._probe = session_probe or default_session_probe
        self._capture = capture or (lambda: osal.capture_screen(max_side=None))
        self._describe = describe or osal.describe_screen
        #: The hand's own clock, injectable so a test can pin a stamp rather
        #: than race a real one. It is the only source of ``captured_at``.
        self._clock = clock or time.time

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
        # Stamped the moment the reader handed the pixels back, not when the
        # answer is written: what the freshness gate ages is the screen, and
        # the write is already part of how old that screen has become.
        stamp = self._clock() if path else None
        if path and not _is_number(stamp):
            # An undatable frame is not offered at all. Handing the driver a
            # picture it cannot place in time would look exactly like a
            # verified one, and the hand is the side that can still retake
            # it -- so this is a refusal it can act on.
            return self._answer(
                rid, kind, state, None, None,
                f"the hand's clock returned {stamp!r}; the frame could not "
                "be stamped, so no frame is offered")
        return self._answer(rid, kind, state, path, None, detail,
                            captured_at=stamp)

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

    def _answer(self, rid, kind, state, path, fields, detail, *,
                captured_at=None):
        record = {"request_id": rid, "kind": kind, "state": state,
                  "detail": detail, "answered_at": time.time()}
        if kind == "describe":
            record["fields"] = fields
        else:
            record["path"] = path
            # An answer with no frame -- locked, reader failure, an
            # undatable clock -- carries an explicit null envelope rather
            # than a partial one, so a consumer reads the absence instead of
            # inferring it from a missing key.
            record[FRAME_FIELD] = (frame_envelope(
                path=path, captured_at=captured_at, state=state)
                if path else None)
        _write_json(os.path.join(_results_dir(self._root), f"{rid}.json"),
                    record)
        return record


def bus_capture_backend(root, *, name="bridge-bus", platform=None,
                        timeout=DEFAULT_TIMEOUT, request_id_factory=None,
                        max_age=DEFAULT_MAX_AGE, clock=None):
    """Build the consumer backend the non-desktop driver registers.

    The returned record is built by :func:`osal.capture_backend`, so it
    registers through :func:`osal.register_capture_backend` like any
    other backend and :class:`adapters.ScreenSource` resolves through it
    unchanged. Each half posts one request to the hand's ledger and waits
    up to ``timeout`` seconds; an unanswered hand arrives as the same
    named refusal shape the native path returns, never as an exception.

    A capture that arrives is judged by the freshness gate before it is
    returned, so the only paths this backend hands on are ones it can date
    inside ``max_age``. ``clock`` is the reader's clock, injectable for the
    same reason the hand's is: a test pins the comparison instead of
    racing it. The window is validated at build time -- a caller that
    declared an impossible one has a bug, and it should not surface as an
    unexplained refusal on the first frame.
    """
    window = _checked_max_age(max_age)
    factory = request_id_factory or (lambda: uuid.uuid4().hex)
    platform = platform or osal.platform_name()
    timeout = max(0.0, timeout)
    now = clock or time.time

    def _capture():
        rid = _checked_id(factory())
        post_capture_request(root, rid, "capture")
        result = read_result(root, rid, timeout=timeout)
        if result is None:
            return None, (f"capture hand did not answer within {timeout:g}s; "
                          "the interactive session may be down")
        path = result.get("path") if isinstance(result, dict) else None
        if not path:
            # BR2's own refusal -- locked, reader failure -- reaches the
            # driver unchanged. The gate would only overwrite it with a
            # freshness verdict about a frame that was never taken.
            return None, str(result.get("detail", "")) if isinstance(
                result, dict) else ""
        fresh, why = check_freshness(result, max_age=window, now=now())
        if not fresh:
            return None, why
        return path, str(result.get("detail", ""))

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
