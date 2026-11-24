"""Run the operator-approved FreeBuff Lane 1 dispatch with Harness vision."""

import argparse
import base64
import ctypes
import hashlib
import io
import json
import os
import re
import time
from difflib import SequenceMatcher
from ctypes import wintypes
from pathlib import Path

from driver_core import osal, transport
from driver_core.actions import MUTATING, Action, Vocabulary
from driver_core.audit import AuditLog
from driver_core.config import Settings
from driver_core.driver import Driver
from driver_core.executor import Consent
from driver_core.jev_client import SYSTEM_ONE_URL
from driver_core.observation import GUI, Target

from .windows_freebuff_capture import TITLE, FreeBuffWindow
from .windows_focus import activate_exact
from .windows_notepad_window import WindowsWindowScreen

GOAL = "Restart the existing Harness Lane 1 local FreeBuff session (315608d2) once in place."
LANE = "Lane 1 navigation row directly below the Harness project heading"
FOCUS = Action("focus_freebuff", MUTATING, "focus_freebuff", ("title",),
               "Bring the existing FreeBuff window forward.", "gui")
CLICK = Action("click_freebuff", MUTATING, "click_freebuff", ("control", "point", "size"),
               "Click the vision-verified FreeBuff control.", "gui")
TYPE = Action("type_freebuff", MUTATING, "type_freebuff", ("text",),
              "Type the exact approved continuation into the empty verified composer.", "gui")
SEND = Action("send_freebuff", MUTATING, "send_freebuff",
              ("thread", "text", "control", "point", "size"),
              "Send the exact authorized draft in the verified session once.", "gui")
QUERY = Action("query_freebuff", MUTATING, "query_freebuff", ("thread", "text", "control"),
               "Search FreeBuff for the exact existing session title.", "gui")
SCROLL = Action("scroll_freebuff", MUTATING, "scroll_freebuff", ("point", "size", "delta"),
                "Scroll visible SCM content without focusing its composer.", "gui")
VOCABULARY = Vocabulary("windows-freebuff-dispatch", "1.2.0", [FOCUS, CLICK, TYPE, SEND, QUERY, SCROLL])
THREAD = "315608d2"
CONTINUATION = "continue in full"
DISK_THREAD = "f90f01e9"
SCM_THREAD = "2ae32937"
VISION_THREAD = "6d39cf4f"
# Full session UUIDs derived by read-only FreeBuff storage lookup (7118494622).
PINNED_UUIDS = {
    THREAD: "315608d2-1531-456b-918a-f7e97db56496",
    DISK_THREAD: "f90f01e9-128f-497b-b64f-2662ee4051e0",
    SCM_THREAD: "2ae32937-c991-4c33-87d4-68b8c956ba98",
    VISION_THREAD: "6d39cf4f-2469-4f47-8cf0-3948309f5f2b",
    "0319b9f6": "0319b9f6-d5da-4327-9632-296f7ab42adf",
}


def lookup_local_session_uuid(short_id, *, appdata=None):
    """Read-only lookup of a full session UUID from local FreeBuff Partitions stores."""
    short = str(short_id or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{8}", short):
        return None
    root = Path(appdata) if appdata is not None else Path(os.environ.get("APPDATA", "")) / "Freebuff" / "Partitions"
    if not root.is_dir():
        return None
    pattern = re.compile(rf"\b({short}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}})\b", re.I)
    for store in ("*/Local Storage/leveldb", "*/IndexedDB/https_freebuff.com_0.indexeddb.leveldb"):
        for directory in sorted(root.glob(store)):
            for path in sorted(directory.iterdir()):
                if not path.is_file() or path.suffix not in (".log", ".ldb"):
                    continue
                try:
                    data = path.read_bytes()
                except OSError:
                    continue
                match = pattern.search(data.decode("utf-8", errors="ignore"))
                if match:
                    return match.group(1).lower()
    return None
BURN_SESSIONS = {
    "0d7e2f37": "BigEnergyCo",
    "7d4a9b14": "Kalshi Paper Burndown",
    "9ecc3453": "Lane 2",
    "918dad1a": "Harness Audit Lane",
    "0319b9f6": "SCMessenger Audit Lane",
}
# What a lane's own transcript must contain for the app to identify it when its
# row name cannot (BigEnergyCo has five sessions that all open with its name).
LANE_MARKERS = {
    "0d7e2f37": ("466", "467"),
}
DISK_POINTER = ("Run D-007 from Treystu/slow-lane-ledger. Read "
                "DISK-AUDIT-MISSION-V3-2026-11-22.md in oversight/disk-audit-2026-11-19.")
SESSIONS = {
    THREAD: ("Lane 1", CONTINUATION),
    DISK_THREAD: ("Disk Audit", CONTINUATION),
    SCM_THREAD: ("SCMessenger", CONTINUATION),
    VISION_THREAD: ("Vision Driver Standup and Audit", CONTINUATION),
    **{thread: (label, CONTINUATION) for thread, label in BURN_SESSIONS.items()},
}
# A title is not an identity: the app keeps a CLOUD and a LOCAL "Lane 1", and a
# local session and a same-named chat can both sit in one sidebar. Every row is
# therefore bound to the project heading printed above it; a row whose heading
# is not in the same frame is refused rather than guessed.
PROJECT_OF = {
    THREAD: "Harness",
    VISION_THREAD: "GitHub",
    DISK_THREAD: "GitHub",
    SCM_THREAD: "SCMessenger",
    "0319b9f6": "SCMessenger",
    "9ecc3453": "Harness",
    "918dad1a": "Harness",
    "0d7e2f37": "BigEnergyCo",
    "7d4a9b14": "Kalshi-Trader",
}
PROJECT_HEADINGS = ("GitHub", "harness CLOUD", "Harness", "SCMessenger",
                    "Kalshi-Trader", "BigEnergyCo", "agensi-skills")
COMPOSER = (630, 918, 1550, 1110)
# The editor's own text band only: the toolbar below it carries labels
# (Build/Plan/Mission/Skills) that are not a draft.
COMPOSER_TEXT = (650, 930, 1520, 1050)
LANE_NAV = (80, 590, 390, 750)
SEND_CONTROL = (1480, 1043, 1535, 1100)
QUEUE_PLACEHOLDER = "Type a message — added to the queue"
QUEUE_REGION = (644, 947, 1250, 1020)
SIDEBAR = (88, 225, 390, 1060)
# The dialog panel only covers its own rows; a taller region picks up the
# transcript behind it (measured: prose lines censused as search results).
SEARCH_RESULTS = (546, 232, 1300, 470)
SEARCH_PLACEHOLDER = (527, 168, 774, 228)
SEARCH_PLACEHOLDER_TAIL = (626, 180, 700, 216)
SEARCH_CLOSE = (1257, 185, 1278, 207)
COUNTS = (6, 16, 26, 36, 46)


CAPTURE_BUDGETS = (2.0, 5.0)


# R10: the New-project dialog as exact OCR anchors. Each entry is the control's
# printed label and the region it must appear in; a missing anchor is a refusal,
# never a guessed click. The register closes this adapter on Stage 3 evidence.
PROJECT_DIALOG = {
    "new": ("New project", (60, 60, 340, 200)),
    "name": ("Project name", (480, 280, 1520, 760)),
    "create": ("Create project", (480, 700, 1520, 1120)),
}
JSON_ACT = 0


def project_anchor(surface, step, frame, key):
    """Locate one dialog control by its exact label, or refuse by name."""
    label, region = PROJECT_DIALOG[key]
    try:
        return surface.locate_exact_text(step, frame, label, region), region
    except RuntimeError:
        raise RuntimeError(
            f"project-creation adapter: the {key} control {label!r} was not visible; "
            "not clicking a guess") from None


def create_project(surface, name):
    """R10: create a project from a dispatch and hand its session row back.

    Opens the New project dialog, names the project, creates it, and proves the
    new row exists before handing off: the returned row is the handoff, so the
    caller can target the new session. Every step is exact-OCR anchored and Jev
    confirmed, the name is read back off the field before creation, and a dialog
    that differs in any control refuses by name rather than creating something
    unnamed.
    """
    frame = surface.frame("project-before-new")
    point, region = project_anchor(surface, "project-new-ocr", frame, "new")
    surface.yes("project-new-confirm", frame, "Is the button labeled New project?",
                region=region)
    surface.act("project-new", CLICK,
                {"control": "New project", "point": point, "size": list(frame.size)})
    time.sleep(1)
    frame = surface.frame("project-dialog-open")
    name_point, name_region = project_anchor(surface, "project-name-ocr", frame, "name")
    create_point, create_region = project_anchor(surface, "project-create-ocr", frame, "create")
    surface.yes("project-dialog-confirm", frame,
                "Does this show a project name field and a create button?",
                region=(480, 240, 1520, 1120))
    surface.act("project-name-focus", CLICK,
                {"control": "Project name field", "point": name_point,
                 "size": list(frame.size)})
    surface.type_literal(name)
    frame = surface.frame("project-name-readback")
    reading = " ".join(surface.read_lines("project-name-read", frame, name_region))
    if surface._norm(reading) != surface._norm(name):
        raise RuntimeError(
            f"project-creation adapter: the name field reads {reading!r}, not {name!r}")
    surface.act("project-create", CLICK,
                {"control": "Create project", "point": create_point,
                 "size": list(frame.size)})
    frame, rows = surface.settled_roster("project-created", SIDEBAR, attempts=6)
    for row in rows:
        if surface._norm(row["text"]) == surface._norm(name):
            surface.audit.append("verification", step_id="project-created",
                                 row=row["text"], name=name)
            return row
    raise RuntimeError(
        f"project-creation adapter: no session row reads {name!r} after {create_region}")


EXPIRED_BANNER_REGION = (630, 560, 1550, 860)
RESUME_CONTROL_REGION = (630, 590, 1550, 960)
START_CONTROL_REGION = (500, 180, 1600, 1100)
RESUMED_WITHOUT_SEND = "resumed-and-running"


def expired_with_staged_mission(banner_lines, staged_lines):
    """R7: is this composer an expired session holding a staged /mission?

    Exact OCR of both halves, never a model opinion: the banner must say the
    free session expired and the editor must hold a /mission draft. This is the
    state the restart path used to refuse outright.
    """
    banner = "".join(banner_lines).casefold().replace(" ", "")
    staged = " ".join(staged_lines).casefold().replace(" ", "")
    return "yourfreesessionhasexpired" in banner and ("/mission" in staged or "missionstart" in staged)


def resume_staged_session(surface, frame, *, attempts=6):
    """R7: click Resume mission, then Start mission, and leave the lane starting.

    The staged /mission is the owner's own work, so it is resumed rather than
    overwritten with the continuation. Each click is exact-OCR located, Jev
    confirmed, and re-read before input; a running Stop cue is the proof. The
    returned outcome tells the caller a send already happened, so the phase list
    stops instead of sending 'continue in full' over a running mission.
    """
    point = surface.locate_exact_text("resume-staged-ocr", frame, "Resume mission",
                                      RESUME_CONTROL_REGION)
    surface.yes("resume-staged-confirm", frame, "Does the button say Resume mission?",
                region=RESUME_CONTROL_REGION)
    surface.frame("resume-staged-readback")
    surface.act("resume-staged", CLICK,
                {"control": "Resume mission", "point": point, "size": list(frame.size)})
    time.sleep(2)
    frame = surface.settle_view("resume-staged-response")
    if surface.stop_visible(frame):
        surface.audit.append("verification", step_id="resume-staged-running", stop_cue=True)
        return "resumed"
    point = surface.locate_exact_text("start-staged-ocr", frame, "Start mission",
                                      START_CONTROL_REGION)
    surface.yes("start-staged-confirm", frame, "Does the button say Start mission?",
                region=START_CONTROL_REGION)
    surface.frame("start-staged-readback")
    surface.act("start-staged", CLICK,
                {"control": "Start mission", "point": point, "size": list(frame.size)})
    for attempt in range(1, attempts + 1):
        time.sleep(3)
        frame = surface.frame(f"start-staged-response-{attempt}")
        if surface.stop_visible(frame):
            surface.audit.append("verification", step_id="start-staged-running",
                                 stop_cue=True, attempts=attempt)
            return "started"
    raise RuntimeError(
        "Resume mission and Start mission were clicked but no running Stop cue appeared")


def bounded_capture(capture, *, budgets=CAPTURE_BUDGETS, clock=time.monotonic):
    """Capture the window, tolerating one slow frame before escalating.

    A single 2 s budget escalated dispatch 7122154514 in its search walk
    (`sidebar-top-3-after: capture exceeded 2s`, 2026-11-24T04:38:53Z) while the
    window was healthy: the frame took longer than the budget because the app
    was rendering, not because ownership or identity had changed. A capture is
    only ever a snapshot, so a slow one is re-taken once under a wider budget
    instead of failing the run; if the retry is also slow the run escalates with
    the same refusal as before. Returns (payload, elapsed, attempts).
    """
    elapsed = 0.0
    for attempt, budget in enumerate(budgets, start=1):
        started = clock()
        payload = capture()
        elapsed = clock() - started
        if elapsed <= budget:
            return payload, elapsed, attempt
    raise RuntimeError(
        f"capture exceeded {budgets[-1]:.0f}s on {len(budgets)} attempts "
        f"(last {elapsed:.3f}s)")


def same_rows(previous, current):
    """Do two censuses describe the same list?

    Identical positions settle. A single extra row also settles: the OCR engine
    invents rows on this app (measured: a phantom "\u00b0 8-9" line appearing and
    disappearing above the same rows), and a phantom only ever adds or drops
    one entry without moving the rest. A row that MOVES is not a superset and
    must never settle.
    """
    if previous == current:
        return True
    small, large = sorted((tuple(previous), tuple(current)), key=len)
    return len(large) - len(small) == 1 and set(small) <= set(large)


class Dispatch:
    def __init__(self, output, key, *, thread=THREAD, scoped_input=False, standing=False):
        from PIL import Image, ImageOps

        self.image = Image
        self.image_ops = ImageOps
        self.window = FreeBuffWindow()
        self.user = self.window.user
        self.user.SetThreadDpiAwarenessContext.argtypes = (ctypes.c_void_p,)
        self.user.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        self.user.SetThreadDpiAwarenessContext(-4)
        self.user.WindowFromPoint.argtypes = (wintypes.POINT,)
        self.user.WindowFromPoint.restype = wintypes.HWND
        self.user.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        self.user.GetAncestor.restype = wintypes.HWND
        self.user.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
        self.user.ScreenToClient.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
        self.user.PostMessageW.argtypes = (
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        self.dwm = ctypes.WinDLL("dwmapi")
        self.dwm.DwmGetWindowAttribute.argtypes = (
            wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
        self.output = output
        self.key = key
        self.thread = thread
        self.scoped_input = scoped_input
        self.standing = standing
        self.label, self.text = SESSIONS[thread]
        self.project = PROJECT_OF.get(thread, self.label)
        self.goal = (GOAL if thread == THREAD else
                     f"Restart the existing {self.label} FreeBuff session ({thread}) once in place.")
        self.composer_renderer = None
        self.search_renderer = None
        self.allow_navigation = False
        self.phase = None
        self.send_deadline = None
        self.send_composer = None
        self.audit = AuditLog(output / "driver.jsonl")
        self.screen = WindowsWindowScreen(self.window, source="windows-freebuff")
        self.driver = Driver(settings=Settings(jev_api_key=key, allow_write=True),
                             vocabulary=VOCABULARY, audit=self.audit)
        self.driver.register_executor(FOCUS.name, self.focus)
        self.driver.register_executor(CLICK.name, self.click)
        self.driver.register_executor(TYPE.name, self.type_text)
        self.driver.register_executor(SEND.name, self.send)
        self.driver.register_executor(QUERY.name, self.query)
        self.driver.register_executor(SCROLL.name, self.scroll)

    def describe(self, hwnd):
        if not hwnd:
            return "no foreground window"
        return (f"hwnd {hwnd} pid {self.window.pid(hwnd)} "
                f"title {self.window.api.title_of(hwnd)!r}")

    def transient_holder(self, hwnd):
        """Is the foreground holder a console that lives in the temp tree?

        Measured 2026-11-23: a scheduler starts the standing watch every two
        minutes from a temp venv, and its console window takes the foreground
        for a few seconds before exiting. That holder is the driver's own
        machinery, so it may be displaced. Any other window is the owner's
        surface and is never taken.
        """
        if not hwnd:
            return False
        title = self.window.api.title_of(hwnd) or ""
        roots = (os.environ.get("TEMP"), os.environ.get("TMP"), os.environ.get("LOCALAPPDATA"))
        if not any(root and root.casefold() in title.casefold() for root in roots):
            return False
        # The console host owns the window (measured: Windows Terminal hosts it
        # in another process), so the class varies; the title is the stable
        # fact and names the temp interpreter that was launched.
        buffer = ctypes.create_unicode_buffer(64)
        self.user.GetClassNameW(hwnd, buffer, 64)
        console = buffer.value.casefold() in {"consolewindowclass", "cascadia_hosting_window_class",
                                              "pseudoconsolewindow"}
        return console or title.strip().casefold().endswith("python.exe")

    def require_foreground(self, attempts=6, timeout=8.0):
        """FreeBuff must hold the foreground; obtain and prove it before giving up.

        The measured holder of a lost foreground was a transient temp console
        (the standing watch), so one observation that FreeBuff is not in front
        is not a reason to park a lane. Every executor path re-asserts and
        re-proves the foreground here; a standing run reclaims only a verified
        transient console and refuses from any other surface.
        """
        hwnd = self.window.require_window()
        started = time.monotonic()
        deadline = started + timeout
        for attempt in range(1, attempts + 1):
            current = self.window.api.foreground()
            if current == hwnd:
                return hwnd
            # Name the holder: an unnamed park cannot be resolved from its evidence.
            self.audit.append("escalation", step_id=f"foreground-{attempt}", expected=hwnd,
                              holder=current, holder_detail=self.describe(current))
            if self.standing and not self.transient_holder(current):
                break
            if not activate_exact(hwnd, self.window.api.foreground):
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.6)
                continue
            time.sleep(0.5)
            if self.window.api.foreground() == hwnd:
                self.audit.append("verification", step_id="foreground-obtained", attempt=attempt,
                                  holder=current, holder_detail=self.describe(current),
                                  age_seconds=round(time.monotonic() - started, 3))
                return hwnd
            if time.monotonic() >= deadline:
                break
        current = self.window.api.foreground()
        raise RuntimeError(f"FreeBuff is not the foreground window; held by {self.describe(current)}")

    def focus(self, action, params):
        hwnd = self.window.require_window()
        if params["title"] not in (TITLE, self.window.title):
            raise RuntimeError("the requested window title differs")
        if self.standing:
            from .windows_freebuff_watch import desktop_idle

            if not desktop_idle():
                raise RuntimeError("desktop activity resumed before taking FreeBuff focus")
        if not activate_exact(hwnd, self.window.api.foreground):
            raise RuntimeError("Windows did not grant exact FreeBuff foreground")
        self.require_foreground()

    def compositor_bounds(self):
        hwnd = self.require_foreground()
        rect = wintypes.RECT()
        if self.dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)):
            raise RuntimeError("could not read FreeBuff compositor bounds")
        return rect

    def renderer_point(self, params):
        hwnd = self.require_foreground()
        rect = self.compositor_bounds()
        width, height = params["size"]
        if abs(rect.right - rect.left - width) > 2 or abs(rect.bottom - rect.top - height) > 2:
            raise RuntimeError("FreeBuff compositor geometry changed after capture")
        px, py = params["point"]
        if not (0 <= px < width and 0 <= py < height):
            raise RuntimeError("the proposed click is outside the verified frame")
        x, y = rect.left + px, rect.top + py
        hit = self.user.WindowFromPoint(wintypes.POINT(x, y))
        if not hit or self.user.GetAncestor(hit, 2) != hwnd:
            raise RuntimeError("the click point is obstructed by a different window")
        name = ctypes.create_unicode_buffer(128)
        self.user.GetClassNameW(hit, name, len(name))
        if name.value != "Chrome_RenderWidgetHostHWND":
            raise RuntimeError("the verified point did not land in the FreeBuff renderer")
        return hit, x, y

    def click(self, action, params):
        hit, x, y = self.renderer_point(params)
        client = wintypes.POINT(x, y)
        if not self.user.ScreenToClient(hit, ctypes.byref(client)):
            raise RuntimeError("could not convert the click into renderer coordinates")
        packed = (client.x & 0xFFFF) | ((client.y & 0xFFFF) << 16)
        for message, keys in ((0x0200, 0), (0x0201, 1), (0x0202, 0)):
            if self.require_foreground() != self.user.GetAncestor(hit, 2):
                raise RuntimeError("the FreeBuff renderer changed before the click")
            if not self.user.PostMessageW(hit, message, keys, packed):
                raise RuntimeError(f"renderer rejected click message (Win32 {ctypes.get_last_error()})")
            time.sleep(0.05)
        if params["control"] == f"{self.label} composer":
            self.composer_renderer = hit
        if params["control"] == "Search chats field":
            self.search_renderer = hit

    def type_text(self, action, params):
        if params["text"] != self.text:
            raise RuntimeError("the text differs from the approved continuation")
        hit = self.composer_renderer
        keyboard = osal._WindowsInputApi()
        for character in self.text:
            if not hit or self.user.GetAncestor(hit, 2) != self.require_foreground():
                raise RuntimeError("the verified composer renderer is no longer available")
            if self.standing or self.text == DISK_POINTER or (self.scoped_input and self.thread == DISK_THREAD):
                if not self.user.PostMessageW(hit, 0x0102, ord(character), 1):
                    raise RuntimeError("the verified FreeBuff composer refused a character")
            else:
                keyboard.type_text(character)

    def send(self, action, params):
        if params["thread"] != self.thread or params["text"] != self.text:
            raise RuntimeError("the thread or text differs from the approved continuation")
        if self.standing:
            if self.thread in {THREAD, VISION_THREAD}:
                self.verify_session_identity()
            else:
                self.verify_active_session()
            fresh = self.frame("send-executor-fresh")
            if (fresh.crop(COMPOSER).tobytes() != self.send_composer or self.turn_running(fresh)):
                raise RuntimeError("the standing composer changed after approval")
        if self.send_deadline is None or time.monotonic() > self.send_deadline:
            raise RuntimeError("the verified send window expired before input")
        self.click(action, params)

    def query(self, action, params):
        if (params["thread"] != self.thread or params["text"] != self.label
                or params["control"] != "Search chats field"):
            raise RuntimeError("search parameters differ from the approved session")
        renderer = self.search_renderer
        for character in self.label:
            if not renderer or self.user.GetAncestor(renderer, 2) != self.require_foreground():
                raise RuntimeError("the verified search renderer changed")
            if not self.user.PostMessageW(renderer, 0x0102, ord(character), 1):
                raise RuntimeError("FreeBuff refused a search character")

    def act(self, step, action, params):
        if self.standing:
            from .windows_freebuff_watch import desktop_idle, guard_approval

            guard_approval()
            if not desktop_idle():
                raise RuntimeError("owner desktop activity resumed before input")
        grant = Consent(True, action.name, params, by=f"operator:freebuff-{self.thread}")
        result = self.driver.executor.execute(action.name, params, consent=grant, step_id=step)
        if not result.ok:
            raise RuntimeError(f"{step}: {result.detail}")

    def frame(self, step):
        try:
            capture, elapsed, attempts = bounded_capture(
                lambda: self.screen.capture_isolated(
                    Target("existing FreeBuff desktop", GUI), self.output / f"{step}.png"))
        except RuntimeError as error:
            raise RuntimeError(f"{step}: {error}") from error
        (self.output / f"{step}.png").write_bytes(capture.payload)
        self.audit.append("capture", step_id=step, **capture.summary(),
                          foreground=self.window.api.foreground() == self.window.handle,
                          capture_seconds=round(elapsed, 3), capture_attempts=attempts)
        return self.image.open(io.BytesIO(capture.payload)).convert("RGB")

    def ask(self, step, frame, questions, *, region):
        left, top, right, bottom = region
        if not (0 <= left < right <= frame.width and 0 <= top < bottom <= frame.height):
            raise RuntimeError(f"{step}: the required crop falls outside the captured window")
        image = frame.crop(region)
        if max(image.size) < 200:
            image = image.resize((image.width * 4, image.height * 4))
        data = io.BytesIO()
        image.save(data, format="PNG")
        fitted, why = osal.prepare_image_bytes(data.getvalue())
        if fitted is None:
            raise RuntimeError(f"{step}: {why}")
        assets = {"frame": {"type": "image", "format": "png",
                            "data_base64": base64.b64encode(fitted).decode("ascii")}}
        started = time.monotonic()
        response = transport.call_service(
            SYSTEM_ONE_URL, questions, headers={"Authorization": f"Bearer {self.key}"},
            timeout=10, body_extra={"state": {"goal": self.goal, "screen": "frame"},
                                    "model": "jev-1.14.0"},
            assets=assets, images_enabled=True)
        latency_ms = round((time.monotonic() - started) * 1000, 1)
        if not response.ok:
            raise RuntimeError(f"{step}: {response.outcome}: {response.detail}")
        answers = response.payload["answers"]
        usage = response.payload.get("usage")
        self.audit.append("decision", step_id=step, goal=self.goal, model=response.payload.get("model"),
                          answers=answers, usage=usage, latency_ms=latency_ms)
        return answers

    def yes(self, step, frame, question, *, region):
        answers = self.ask(step, frame, {"yes": transport.noul(question)}, region=region)
        probability = answers.get("yes", {}).get("noul", 0)
        if not isinstance(probability, (int, float)) or not 0.9 <= probability <= 1:
            raise RuntimeError(f"{step}: Jev target confidence was {probability}, requires 0.90")

    def choose(self, step, frame, question, choices, *, region, threshold=0.9):
        answers = self.ask(step, frame, {"choice": transport.choice(question, choices)},
                           region=region)
        choice = answers.get("choice", {})
        selected = choice.get("choice")
        probability = choice.get("probabilities", {}).get(selected, 0)
        if selected not in choices or not isinstance(probability, (int, float)):
            raise RuntimeError(f"{step}: malformed Jev choice")
        if not threshold <= probability <= 1:
            raise RuntimeError(f"{step}: Jev choice {selected!r} confidence was {probability}")
        return selected

    def locate_exact_text(self, step, frame, label, region, *, whole=False, with_bounds=False, scale=3):
        left, top, right, bottom = region
        crop = frame.crop(region).resize(((right - left) * scale, (bottom - top) * scale))
        # Windows OCR resolves files by absolute path only.
        path = (self.output / f"{step}-ocr.png").resolve()
        self.image_ops.invert(self.image_ops.grayscale(crop)).save(path)
        command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-File",
                   str(Path(__file__).with_name("windows_ocr_exact.ps1")),
                   "-Path", str(path), "-Label", label]
        if whole:
            command.append("-WholeText")
        result = osal.run(command, timeout=8)
        if not result.ok:
            raise RuntimeError(f"{step}: exact OCR label {label!r} was not verified")
        point = json.loads(result.stdout)
        xy = [left + round(point["x"] / scale), top + round(point["y"] / scale)]
        self.audit.append("extraction", step_id=step, source="windows-ocr",
                          exact_label=label, point=xy)
        if with_bounds:
            bounds = [round(value / scale) + origin for value, origin in
                      zip(point["bounds"], (left, top, left, top), strict=True)]
            return xy, bounds
        return xy

    def open_lane(self):
        frame = self.frame("before-focus")
        self.yes("identify-freebuff", frame,
                 "Does the image contain the clearly printed word Freebuff beside a white logo?",
                 region=(65, 55, 285, 130))
        self.act("foreground", FOCUS, {"title": TITLE})
        frame = self.frame("foreground")
        self.require_foreground()
        self.yes("identify-lane1", frame, f"Is the exact {LANE} visible?",
                 region=(80, 590, 350, 690))
        point = self.locate_exact_text("locate-lane1", frame, "Lane 1", (128, 638, 300, 686))
        self.act("open-lane1", CLICK, {"control": LANE, "point": point, "size": list(frame.size)})
        time.sleep(0.7)
        frame = self.frame("lane1-open")
        self.verify_lane(frame)

    def read_roster(self, step, frame, region):
        """OCR one candidate list: the printed text and where its first word starts."""
        left, top, right, bottom = region
        crop = frame.crop(region)
        crop = crop.resize((crop.width * 2, crop.height * 2))
        path = (self.output / f"{step}-roster.png").resolve()
        self.image_ops.invert(self.image_ops.grayscale(crop)).save(path)
        result = osal.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-File",
                           str(Path(__file__).with_name("windows_ocr_exact.ps1")),
                           "-Path", str(path), "-ReadLines"], timeout=15)
        if not result.ok:
            raise RuntimeError(f"{step}: the roster OCR could not be read")
        rows = []
        for line in json.loads(result.stdout).get("lines") or []:
            words = line.get("words") or []
            label = (line.get("text") or "").strip()
            if not words or not label:
                continue
            rows.append({"text": label,
                         "x": left + min(word["x"] for word in words) / 2,
                         "y": top + min(word["y"] for word in words) / 2,
                         "x1": left + max(word["x"] for word in words) / 2 + 12})
        self.audit.append("extraction", step_id=f"{step}-roster", rows=len(rows),
                          texts=[row["text"] for row in rows][:16])
        return rows

    @classmethod
    def identity_of(cls, rows):
        """The roster's rows as an order-free identity set.

        Lanes start and finish while the list is open, so the same rows move;
        identity is what the census must agree on, geometry is what a click
        must re-prove immediately before it lands.
        """
        return tuple(sorted(cls._norm(row["text"]) for row in rows))

    @classmethod
    def identities_compatible(cls, previous, current):
        """Whether two censuses read the same rows, allowing OCR slips.

        Geometry alone is not enough: a different row can occupy the same slot
        (measured: a whole roster changing under one stationary position), while
        the OCR engine also re-reads a stationary row differently ("Kalshi Paper
        Bumd" vs "Kalshi Paper Burndc V").
        """
        if previous == current:
            return True
        if not previous or not current or len(previous) != len(current):
            return False
        return all(SequenceMatcher(None, left, right).ratio() >= 0.7
                   for left, right in zip(previous, current))

    def settled_roster(self, step, region, attempts=6):
        """A roster two consecutive censuses agree on, or a refusal naming both."""
        previous = None
        previous_identity = None
        previous_rows = []
        rows = []
        frame = self.frame(f"{step}-0")
        for attempt in range(1, attempts + 1):
            rows = self.read_roster(f"{step}-{attempt}", frame, region)
            # Settling is about where the rows ARE: the OCR engine alternates
            # icons and truncations on a stationary list (measured: "Kalshi
            # Paper Bumd" vs "Kalshi Paper Burndc V" on one unchanged row), so
            # comparing text can never settle and comparing geometry can.
            current = tuple(round(row["y"] / 2) for row in rows)
            identity = self.identity_of(rows)
            if (rows and previous is not None and same_rows(previous, current)
                    and self.identities_compatible(previous_identity, identity)):
                self.audit.append("verification", step_id=f"{step}-settled", rows=len(rows),
                                  censuses=attempt, settled_by="geometry",
                                  texts=[row["text"] for row in rows][:16])
                return frame, rows
            previous = current
            # A live lane reorders the list while it renders (measured: the
            # SCM walk never settled in five censuses while other lanes moved).
            # The same rows in a different order is a usable census as long as
            # every click re-proves its own row in a fresh frame. An empty read
            # is never a census: the app re-renders with an empty sidebar for a
            # while (measured R17: three empty censuses "settled" during a
            # reload and the selection probe then refused a correct click).
            if (attempt >= 3 and rows and previous_identity is not None
                    and identity == previous_identity and len(rows) == len(previous_rows)):
                self.audit.append("verification", step_id=f"{step}-settled", rows=len(rows),
                                  censuses=attempt, settled_by="identity",
                                  texts=[row["text"] for row in rows][:16])
                return frame, rows
            previous_identity = identity
            previous_rows = rows
            time.sleep(0.7)
            frame = self.frame(f"{step}-resettle-{attempt}")
        raise RuntimeError(f"{step}: the roster did not settle in {attempts} censuses; "
                           f"last rows: {[row['text'] for row in rows][:12]}")

    @staticmethod
    def _norm(text):
        return "".join(character for character in text.casefold() if character.isalnum())

    @classmethod
    def row_matches(cls, text, label):
        """Exact title, or the same row read through OCR slips and sidebar clipping.

        Real rows read "Kalshi Paper Bumdown V" for "Kalshi Paper Burndown"
        (the engine joins rn into m) and are cut off at the sidebar edge, so a
        prefix rule cannot work. A long shared opening plus a high similarity
        over the clipped length can; ambiguity is still refused downstream by
        requiring exactly one matching row.
        """
        wanted = cls._norm(label)
        # Rows carry their status glyph into the OCR text ("B Lane 1",
        # "Ra Kalshi Paper Burndown"), so the leading one-to-three character
        # token is not part of the name - without this, a short label like
        # "Lane 1" could never match its own row at all (measured, l5).
        candidates = {cls._norm(text)}
        head, _, tail = text.strip().partition(" ")
        if len(head) <= 3 and tail:
            candidates.add(cls._norm(tail))
        if not wanted or not any(candidates):
            return False
        if wanted in candidates:
            return True
        # A row that OPENS with the configured name is that name (its tail is
        # the app's own longer title); this is what lets a short label match
        # "Ra Lane 2 Waist Composition Mission Brief".
        for name in (text.strip(), tail):
            if name and name.casefold().startswith(label.strip().casefold()):
                return True
        for seen in candidates:
            if len(seen) < 10:
                continue
            common = 0
            for left, right in zip(seen, wanted):
                if left != right:
                    break
                common += 1
            if common < 6:
                continue
            if wanted.startswith(seen):
                return True
            window = wanted[:len(seen)] if len(seen) <= len(wanted) else wanted
            if SequenceMatcher(None, seen, window).ratio() >= 0.85:
                return True
        return False

    @classmethod
    def heading_name(cls, text):
        """Which project heading this row is, if it is one.

        Headings carry the project's icon glyph into the OCR text ("B GitHub"),
        so the leading one-to-three character token is stripped exactly as
        row_matches does for session titles. "harness CLOUD" and "Harness" are
        distinct headings and must never collapse into one another.
        """
        normed = cls._norm(text)
        for name in PROJECT_HEADINGS:
            if normed == cls._norm(name):
                return name
        head, _, tail = text.strip().partition(" ")
        if len(head) <= 3 and tail:
            for name in PROJECT_HEADINGS:
                if cls._norm(tail) == cls._norm(name):
                    return name
        return None

    @classmethod
    def project_of_row(cls, rows, row):
        """The project heading above a row in this frame, or None if offscreen."""
        heading = None
        for candidate in sorted(rows, key=lambda item: item["y"]):
            if candidate["y"] > row["y"] + 2:
                break
            name = cls.heading_name(candidate["text"])
            if name:
                heading = name
        return heading

    @classmethod
    def session_candidates(cls, rows, label, project):
        """Rows that are the session, and the project heading if it collided.

        The app names a project and a chat alike (measured: heading
        "B SCMessenger", chat "SCMessenger"). The heading carries the icon
        glyph into the OCR text; the chat does not, so a prefixed row that
        reads as a heading is the section, never the session.
        """
        found, heading = [], None
        for row in rows:
            if cls.project_of_row(rows, row) != project:
                continue
            if not cls.row_matches(row["text"], label):
                continue
            if cls.heading_name(row["text"]) and row["text"].strip() != label.strip():
                heading = row
                continue
            found.append(row)
        if len(found) > 1:
            # Prefix rivals are distinct chats, not clipped copies of this one
            # (measured: the SCMessenger project holds "SCMessenger", "SCMessenger
            # Audit Lar", "SCMessenger Fresh Re", "SCMessenger Bumdown Tc", "Ra
            # SCMessenger Fast Mode Pc"). The row whose title IS the label wins;
            # any other tie is still refused.
            exact = [row for row in found
                     if row["text"].strip() == label.strip()
                     or cls._norm(row["text"].partition(" ")[2] or "") == cls._norm(label)]
            if len(exact) == 1:
                found = exact
        return found, heading

    @classmethod
    def scoped_row(cls, rows, row, label, project):
        """Is this row the configured session, in its own project?

        Title alone is not identity: the app has a CLOUD "Lane 1" and a LOCAL
        "Lane 1", and the 19:30Z receipt read the CLOUD row green for the local
        lane. A row with no visible heading above it is unscoped and refused.
        """
        return (cls.row_matches(row["text"], label)
                and cls.project_of_row(rows, row) == project)

    def scroll(self, action, params):
        """Scroll the renderer read-only: hover, then one wheel step."""
        hit, x, y = self.renderer_point(params)
        client = wintypes.POINT(x, y)
        if not self.user.ScreenToClient(hit, ctypes.byref(client)):
            raise RuntimeError("could not bind the scroll point to the renderer")
        hover = (client.x & 0xFFFF) | ((client.y & 0xFFFF) << 16)
        if not self.user.PostMessageW(hit, 0x0200, 0, hover):
            raise RuntimeError("the renderer rejected the hover")
        packed = (x & 0xFFFF) | ((y & 0xFFFF) << 16)
        if not self.user.PostMessageW(hit, 0x020A, (params["delta"] & 0xFFFF) << 16, packed):
            raise RuntimeError("the renderer rejected scrolling")

    def relocated_click(self, step, label):
        """Click a row that moved after its census: re-census, then click where it is."""
        frame, rows = self.settled_roster(f"{step}-relocate", SIDEBAR, attempts=4)
        found, _ = self.session_candidates(rows, label, self.project)
        if not found:
            found = [row for row in rows if row["text"].strip() == label.strip()]
        if len(found) != 1:
            raise RuntimeError(f"{step}: the row moved and was not uniquely relocatable "
                               f"({len(found)} matches, label {label!r})")
        row = found[0]
        point = [round((row["x"] + row["x1"]) / 2), round(row["y"] + 8)]
        self.act(f"{step}-relocated", CLICK,
                 {"control": f"session row {label}", "point": point,
                  "size": list(frame.size)})
        self.audit.append("action", step_id=f"{step}-relocated", row=row["text"],
                          reason="the census row moved; re-located by text")
        return row

    def click_exact_row(self, step, frame, row):
        """Click one row already chose from a settled census."""
        point = [round((row["x"] + row["x1"]) / 2), round(row["y"] + 8)]
        scope = (round(row["x"] - 6), round(row["y"] - 4),
                 round(row["x1"] + 6), round(row["y"] + 20))
        fresh = self.frame(f"{step}-readback")
        if fresh.crop(scope).tobytes() != frame.crop(scope).tobytes():
            return self.relocated_click(step, row["text"])
        self.act(step, CLICK, {"control": f"session row {row['text']}", "point": point,
                               "size": list(frame.size)})
        return row

    def click_roster_row(self, step, frame, rows, label):
        matches = [row for row in rows if self.row_matches(row["text"], label)]
        if len(matches) > 1:
            # The app names a chat the same as its project (measured: the
            # SCMessenger project heading and one chat both read "SCMessenger").
            # The heading carries the project's icon glyph into the OCR text,
            # the chat does not, so exactly one plain row is the unique match.
            plain = [row for row in matches if row["text"].strip() == label.strip()]
            if len(plain) == 1:
                self.audit.append("verification", step_id=f"{step}-unique-plain",
                                  row=plain[0]["text"], rivals=len(matches))
                matches = plain
        if len(matches) != 1:
            raise RuntimeError(f"{step}: {label!r} matched {len(matches)} settled rows; "
                               f"roster: {[row['text'] for row in rows][:14]}")
        row = matches[0]
        point = [round((row["x"] + row["x1"]) / 2), round(row["y"] + 8)]
        scope = (round(row["x"] - 6), round(row["y"] - 4),
                 round(row["x1"] + 6), round(row["y"] + 20))
        fresh = self.frame(f"{step}-readback")
        if fresh.crop(scope).tobytes() != frame.crop(scope).tobytes():
            return self.relocated_click(step, row["text"])
        self.act(step, CLICK, {"control": f"session row {row['text']}", "point": point,
                               "size": list(frame.size)})
        return row

    def highlighted_row(self, frame, rows):
        gray = frame.convert("L")
        best = None
        for row in rows:
            x0, y0 = round(row["x"]), round(row["y"])
            scores = 0
            for offset in COUNTS:
                x, y = x0 + offset, y0 + 8
                if x >= gray.width or y - 26 < 0:
                    continue
                if gray.getpixel((x, y)) - gray.getpixel((x, y - 26)) >= 8:
                    scores += 1
            if scores >= 3 and (best is None or scores > best[0]):
                best = (scores, row)
        return best[1] if best else None

    @classmethod
    def exact_session_title(cls, text, label):
        """Is this row's title exactly the lane, not a heading or a rival?

        Measured on the SCMessenger project: heading 'B SCMessenger', the lane
        'SCMessenger', and four chats that only OPEN with the name. Only the
        plain row whose title is the label qualifies.
        """
        stripped = text.strip()
        if stripped == label.strip():
            return True
        return cls._norm(stripped.partition(" ")[2] or "") == cls._norm(label)

    def selected_exact_session(self, wait=8):
        """Prove the lane from the app's own selection when no route is exposed.

        Chromium publishes no route on this window (measured 2026-11-24: three
        structure reads returned nothing after a clean selection), so the
        selection is the primary source. It must be this lane's exact title
        inside the pinned project; a project heading or a title that merely
        opens with the name is refused.
        """
        deadline = time.monotonic() + wait
        while True:
            try:
                frame, rows = self.settled_roster("selected-exact-probe", SIDEBAR, attempts=5)
            except RuntimeError as error:
                # A census that could not settle is not a verdict on the click:
                # the app can be re-rendering. Retry until the wait is spent.
                self.audit.append("escalation", step_id="selected-exact-probe",
                                  reason=str(error))
                if time.monotonic() >= deadline:
                    return False
                time.sleep(1.2)
                continue
            row = self.highlighted_row(frame, rows)
            # A project heading and one chat can share a name (SCMessenger); the
            # chat is always the lower of the two rows, so the selection must be
            # the lowest exact title in this project, never the heading.
            exacts = [candidate for candidate in rows
                      if self.exact_session_title(candidate["text"], self.label)
                      and self.project_of_row(rows, candidate) == self.project]
            lowest = max(exacts, key=lambda candidate: candidate["y"]) if exacts else None
            if row is not None and lowest is not None and row["y"] == lowest["y"]:
                self.audit.append("verification", step_id="selected-exact-session",
                                  row=row["text"], project=self.project)
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.8)

    def selected_label_matches(self, wait=0):
        deadline = time.monotonic() + wait
        while True:
            try:
                frame, rows = self.settled_roster("selected-row-probe", SIDEBAR, attempts=5)
            except RuntimeError as error:
                # Same rule as the exact probe: an unsettled census is not the
                # app saying the click failed.
                self.audit.append("escalation", step_id="selected-row-probe", reason=str(error))
                if time.monotonic() >= deadline:
                    return False
                time.sleep(1.2)
                continue
            row = self.highlighted_row(frame, rows)
            if row and self.row_matches(row["text"], self.label):
                project = self.project_of_row(rows, row)
                if project == self.project:
                    self.audit.append("verification", step_id="selected-row", row=row["text"],
                                      project=project)
                    return True
                # A highlighted same-titled row in another project is the
                # false-green defect, not this lane.
                self.audit.append("escalation", step_id="selected-row-project", row=row["text"],
                                  project=project, expected=self.project)
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.8)

    def reloaded(self, frame):
        """Has the renderer thrown its session away and landed on a new chat?

        Measured 2026-11-23: mid-phase the app replaces the session view with a
        blank "What can I help build?" page - the draft vanishes, the sidebar
        censuses empty, and the accessibility tree goes quiet. That greeting is
        the app stating its own state, so it is the detector.
        """
        for step, label, region in (("reload-greeting", "What can I help build?",
                                     (700, 280, 1460, 430)),
                                    ("reload-composer", "Ask Freebuff... Use / for commands",
                                     (640, 930, 1300, 1000))):
            lines = self.read_lines(step, frame, region)
            reading = self._norm(" ".join(lines))
            if reading and self._norm(label) in reading:
                self.audit.append("extraction", step_id=f"{step}-reading", text=reading[:160])
                return True
        return False

    def stable_window(self, step, seconds=25, attempts=12):
        """Wait for a window that has finished re-rendering.

        A reloaded app answers with an empty sidebar for a while. Nothing may be
        selected or typed until the roster is non-empty and two consecutive
        censuses agree, which is the same two-census rule the order requires.
        """
        deadline = time.monotonic() + seconds
        previous = None
        rows = []
        frame = self.frame(f"{step}-0")
        for attempt in range(1, attempts + 1):
            rows = self.read_roster(f"{step}-{attempt}", frame, SIDEBAR)
            current = tuple(round(row["y"] / 2) for row in rows)
            if rows and previous is not None and same_rows(previous, current):
                self.audit.append("verification", step_id=f"{step}-stable", rows=len(rows),
                                  censuses=attempt)
                return frame, rows
            if time.monotonic() >= deadline:
                break
            previous = current
            time.sleep(1.0)
            frame = self.frame(f"{step}-{attempt}-resettle")
        raise RuntimeError(f"{step}: the window did not reach a stable roster in {seconds}s "
                           f"(last census {len(rows)} rows)")

    def reestablish_if_reloaded(self, step):
        """Detect a reload, wait it out, re-open the lane and re-stage the draft.

        This is the cure for the defect that killed Lane 1's proof: the app
        reloaded between the draft check and the click, so the send had nothing
        to send into. Waiting for stability first and re-preparing inside the
        settled window is the only version of the send that is not a race.
        """
        frame = self.frame(f"{step}-reload-detect")
        if not self.reloaded(frame):
            return False
        self.audit.append("escalation", step_id=f"{step}-reload",
                          reason="the renderer reloaded onto a new chat; re-establishing the lane")
        self.stable_window(f"{step}-reload-stable")
        allowed = self.allow_navigation
        self.allow_navigation = True
        try:
            opened = self.navigate_by_session_list() or self.navigate_by_unique_prefix()
        finally:
            self.allow_navigation = allowed
        if not opened:
            raise RuntimeError(f"{step}: the app reloaded and {self.label!r} could not be re-opened "
                               "from the project session list")
        self.audit.append("verification", step_id=f"{step}-reopened", label=self.label)
        self.settle_view(f"{step}-reopened-settle", seconds=25)
        self.recovering = True
        try:
            self.prepare_draft()
        finally:
            self.recovering = False
        return True

    def scroll_by(self, step, frame, point, delta):
        """A scroll step; a compositor change between capture and input is retried."""
        try:
            self.act(step, SCROLL, {"point": point, "size": list(frame.size), "delta": delta})
            return True
        except RuntimeError as error:
            self.audit.append("escalation", step_id=step, reason=str(error))
            return False

    def scroll_sidebar_to_top(self, steps=8):
        """Reach the top of the project list, proven by two identical rosters."""
        previous = None
        frame = self.frame("sidebar-top-0")
        for attempt in range(1, steps + 1):
            rows = self.read_roster(f"sidebar-top-{attempt}", frame, SIDEBAR)
            current = tuple(self._norm(row["text"]) for row in rows)
            if current and current == previous:
                return frame
            previous = current
            if not self.scroll_by(f"sidebar-top-scroll-{attempt}", frame, [196, 600], 1200):
                frame = self.frame(f"sidebar-top-{attempt}-recapture")
                continue
            time.sleep(0.8)
            frame = self.frame(f"sidebar-top-{attempt}-after")
        return frame

    def advance_sidebar(self, step, frame, deltas=(-240, -900)):
        """Scroll the sidebar down one page, proving the census actually moved.

        Measured (R16): a single -240 wheel step can land on a viewport whose
        rows read identically to the one before it (the app's clipped column
        and the wheel's rounding both absorb small steps), and the walk's
        "same page twice" test then concluded the list had ENDED with the
        SCMessenger section still below it - twice (runs 1620 and 1740). One
        census is evidence of a viewport, never of the list's depth, so the
        step is retried with a larger delta before the end is believed.
        """
        before = self.identity_of(self.read_roster(f"{step}-before", frame, SIDEBAR))
        for index, delta in enumerate(deltas, 1):
            if not self.scroll_by(f"{step}-scroll-{index}", frame, [196, 850], delta):
                frame = self.frame(f"{step}-recapture-{index}")
                continue
            time.sleep(0.9)
            frame = self.frame(f"{step}-after-{index}")
            after = self.identity_of(self.read_roster(f"{step}-after-{index}", frame, SIDEBAR))
            if after and after != before:
                self.audit.append("verification", step_id=f"{step}-advanced",
                                  delta=delta, rows=len(after))
                return frame, True
        self.audit.append("verification", step_id=f"{step}-end",
                          reason="the census stopped changing; this is the end of the list")
        return frame, False

    def walk_session_list(self, pages=20):
        """Walk the project session list page by page until the LIST itself ends.

        Twenty pages is a bound, not the plan: the walk stops when a further
        scroll stops changing the census (R16), so a longer list is censused
        in full and the end is never inferred from one repeated page.

        A page that holds only chats which OPEN with the configured name
        cannot decide which chat a lane is (measured: the SCMessenger project
        holds "SCMessenger", "SCMessenger Audit Lar", "SCMessenger Fresh Re",
        "SCMessenger Bumdown Tc", "Ra SCMessenger Fast Mode Pc"), so a clipped
        candidate is held back and only an exact title is picked on sight.
        """
        frame = self.scroll_sidebar_to_top()
        seen, rivals = [], []
        for page in range(1, pages + 1):
            try:
                frame, rows = self.settled_roster(f"session-list-{page}", SIDEBAR, attempts=5)
            except RuntimeError as error:
                # A page that never settles (the list is reordering under the
                # census) must not end the walk; the next page may settle.
                self.audit.append("escalation", step_id=f"walk-session-list-{page}",
                                  reason=str(error))
                frame, moved = self.advance_sidebar(f"walk-session-list-{page}", frame)
                if not moved:
                    break
                continue
            texts = [row["text"] for row in rows]
            if texts in seen:
                frame, moved = self.advance_sidebar(f"walk-session-list-{page}", frame)
                if not moved:
                    break
                continue
            seen.append(texts)
            matches = [row for row in rows if self.row_matches(row["text"], self.label)]
            unrelated = [row["text"] for row in matches
                         if self.project_of_row(rows, row) != self.project]
            if unrelated:
                self.audit.append("escalation", step_id=f"session-list-foreign-{page}",
                                  rows=unrelated[:6], expected=self.project)
            scoped, heading = self.session_candidates(rows, self.label, self.project)
            if not scoped and heading is not None:
                # A collapsed project shows its heading and no chats; open it
                # once, then census the same page again.
                try:
                    self.click_exact_row(f"session-list-open-project-{page}", frame, heading)
                    time.sleep(1.0)
                    frame, rows = self.settled_roster(f"session-list-{page}-opened", SIDEBAR,
                                                      attempts=4)
                    scoped, heading = self.session_candidates(rows, self.label, self.project)
                    self.audit.append("verification", step_id=f"session-list-open-project-{page}",
                                      opened=True, rows=len(rows))
                except RuntimeError as error:
                    self.audit.append("escalation", step_id=f"session-list-open-project-{page}",
                                      reason=str(error))
            exact = [row for row in scoped
                     if self.exact_session_title(row["text"], self.label)]
            if len(exact) == 1:
                # Click the scoped row itself: the title-only matcher would see
                # the same-titled row in the other project and refuse.
                self.click_exact_row(f"session-list-pick-{page}", frame, exact[0])
                self.audit.append("verification", step_id=f"session-list-pick-{page}",
                                  row=exact[0]["text"], project=self.project)
                return True
            for row in (() if exact else scoped):
                if self._norm(row["text"]) in {self._norm(item["text"]) for item in rivals}:
                    continue
                rivals.append(row)
            if len(scoped) > 1 and not exact:
                self.audit.append("escalation", step_id=f"session-list-ambiguous-{page}",
                                  rows=[row["text"] for row in scoped])
            expand = next((row for row in rows
                           if row["text"].strip() in {"Show more", "More chats"}), None)
            if expand:
                self.click_roster_row(f"session-list-expand-{page}", frame, rows, expand["text"])
                time.sleep(1.0)
                continue
            frame, moved = self.advance_sidebar(f"session-list-{page}", frame)
            if not moved:
                break
        if len(rivals) == 1:
            # The whole list was censused and exactly one chat opens with this
            # name: the app clipped that one title, and it is the pick.
            self.audit.append("verification", step_id="session-list-clipped-unique",
                              row=rivals[0]["text"], label=self.label)
            return self.click_row_by_text(rivals[0]["text"], pages=pages)
        self.audit.append("escalation", step_id="session-list-census", label=self.label,
                          candidates=[row["text"] for row in rivals][:8],
                          reason="no exact session row in the whole list; not guessing")
        return False

    def routes(self):
        """Whatever routes the app exposes, whatever shape the helper returns.

        Measured: the helper answers `[]` on most handles (dead accessibility
        tree) and a list of routes when the tree is live; it is never assumed
        to be either.
        """
        payload = None
        for attempt in (1, 2, 3):
            try:
                payload = self.read_app_structure()
            except RuntimeError as error:
                self.audit.append("escalation", step_id=f"routes-{attempt}", reason=str(error))
                payload = None
            if payload:
                if attempt > 1:
                    self.audit.append("verification", step_id="routes-retry", attempt=attempt)
                break
            time.sleep(0.7)
        if payload is None:
            return []
        if isinstance(payload, dict):
            items = payload.get("documents") or payload.get("routes") or []
        elif isinstance(payload, list):
            items = payload
        else:
            return []
        return [str(item.get("route") or item.get("url") or item)
                if isinstance(item, dict) else str(item) for item in items]

    def expand_project(self, page, frame, rows, step):
        """Open a collapsed project before censusing its sessions.

        Measured after a reload: the SCMessenger project was collapsed, so its
        sessions were nowhere in the eight censused pages and the lane looked
        absent. "Show more" is the app's own control for that, so it is clicked
        once per page and the page is re-censused.
        """
        expand = next((row for row in rows
                       if row["text"].strip() in {"Show more", "More chats"}), None)
        if expand is None:
            return frame, rows
        try:
            self.click_exact_row(f"{step}-expand-{page}", frame, expand)
        except RuntimeError as error:
            self.audit.append("escalation", step_id=f"{step}-expand-{page}", reason=str(error))
            return frame, rows
        time.sleep(1.1)
        try:
            return self.settled_roster(f"{step}-{page}-expanded", SIDEBAR, attempts=4)
        except RuntimeError as error:
            self.audit.append("escalation", step_id=f"{step}-expand-{page}", reason=str(error))
            return frame, rows

    def candidates_in(self, rows, page, found):
        """Collect the rows on one page that could be this lane, by identity."""
        for row in rows:
            if (self._prefix_matches(row["text"], self.label)
                    and self.project_of_row(rows, row) == self.project):
                if all(self._norm(row["text"]) != self._norm(name) for _, name in found):
                    found.append((page, row["text"]))
        return found

    def narrow_session_list(self, steps=3):
        """Filter the session list with the app's own search field.

        Measured 2026-11-24T04:48-04:52Z: the exhaustive sidebar walk needed
        eight pages at roughly 30 s each and spent the register's whole 240 s
        bound before it could pick, so no dispatch ever reached its phases. The
        field returns every row whose text carries the label - rivals and
        clipped rows included, which is exactly the set the uniqueness proof
        needs - so the same proof runs over far fewer pages while the bound and
        the no-guessing rule stay as they are. Refuses by name when the field
        itself cannot be located, rather than silently falling back to a walk
        that cannot finish.
        """
        self.require_foreground()
        frame = self.ensure_search_dialog(self.frame("narrow-before-search"))
        # Each phase is its own process, and the query phase has usually already
        # put this label in the field. Typing again would read "Lane 1Lane 1" and
        # match nothing, so the field's own text decides.
        try:
            typed = " ".join(self.read_lines("narrow-field-read", frame, SEARCH_PLACEHOLDER))
        except RuntimeError:
            typed = ""
        if self._norm(self.label) and self._norm(self.label) in self._norm(typed):
            self.audit.append("verification", step_id="narrow-reused-query",
                              reason="the search field already carries this label")
        else:
            try:
                point = self.locate_exact_text("narrow-search-field", frame, "Search chats",
                                               SEARCH_PLACEHOLDER)
            except RuntimeError:
                frame = self.frame("narrow-search-caret")
                point = self.locate_exact_text("narrow-search-field-tail", frame, "chats",
                                               SEARCH_PLACEHOLDER_TAIL)
            self.act("narrow-focus-search", CLICK,
                     {"control": "Search chats field", "point": point,
                      "size": list(frame.size)})
            self.act("narrow-query", QUERY, {"thread": self.thread, "text": self.label,
                                             "control": "Search chats field"})
            time.sleep(1.4)
        rows = []
        for index in range(1, steps + 1):
            frame, page = self.settled_roster(f"narrowed-{index}", SIDEBAR, attempts=3)
            rows.extend(page)
            if index >= steps or not self.scroll_by(
                    f"narrowed-scroll-{index}", frame, [196, 850], -400):
                break
            time.sleep(0.9)
            frame = self.frame(f"narrowed-{index}-after")
        self.audit.append("verification", step_id="narrowed-roster", label=self.label,
                          rows=len(rows))
        return frame, rows

    def _prefix_matches(self, text, label):
        """Is this row plausibly the configured lane, allowing app clipping?"""
        seen, wanted = self._norm(text), self._norm(label)
        return bool(seen and wanted and len(wanted) >= 4
                    and (seen.startswith(wanted) or wanted.startswith(seen)))

    def navigate_by_unique_prefix(self, pages=8, narrow=True):
        """Open the configured lane when exactly ONE session list row can be it.

        The configured names are ours and the app clips its own rows (measured:
        no row reads "Lane 2", one reads "Lane 2 Waist Composition Mission
        Brief"; none reads "BigEnergyCo", five read "BigEnergyCo ..."). One
        candidate is a pick; several are named and refused, never guessed.

        The proof is unchanged by `narrow`: the candidate set is restricted with
        the app's search field first, which only removes rows that cannot carry
        the label, and the same exact-wins and one-candidate rules then run over
        what is left. `narrow=False` keeps the exhaustive walk for the cold runs
        that need to census the whole list.
        """
        found = []
        if narrow:
            try:
                frame, rows = self.narrow_session_list()
            except RuntimeError as error:
                self.audit.append("escalation", step_id="narrow-walk", reason=str(error))
                return False
            found = self.candidates_in(rows, 1, found)
        else:
            frame = self.scroll_sidebar_to_top()
            seen = []
            for page in range(1, pages + 1):
                try:
                    frame, rows = self.settled_roster(f"prefix-{page}", SIDEBAR, attempts=4)
                except RuntimeError as error:
                    self.audit.append("escalation", step_id="prefix-walk", reason=str(error))
                    return False
                frame, rows = self.expand_project(page, frame, rows, "prefix")
                texts = [self._norm(row["text"]) for row in rows]
                if texts in seen:
                    break
                seen.append(texts)
                found = self.candidates_in(rows, page, found)
                if not self.scroll_by(f"prefix-scroll-{page}", frame, [196, 850], -400):
                    frame = self.frame(f"prefix-{page}-recapture")
                    continue
                time.sleep(0.9)
                frame = self.frame(f"prefix-{page}-after")
        if len(found) > 1:
            # Chats that merely OPEN with this name are rivals, not copies of it
            # (measured: five chats open with "SCMessenger", one IS SCMessenger).
            exact = [(page, name) for page, name in found
                     if name.strip() == self.label.strip()
                     or self._norm(name.partition(" ")[2] or "") == self._norm(self.label)]
            if len(exact) == 1:
                self.audit.append("verification", step_id="prefix-exact-wins",
                                  row=exact[0][1], rivals=len(found))
                found = exact
        if len(found) != 1:
            self.audit.append("escalation", step_id="prefix-census", label=self.label,
                              candidates=[name for _, name in found][:8], count=len(found),
                              reason="no unique session row for this lane; not guessing")
            return False
        page, name = found[0]
        self.audit.append("verification", step_id="prefix-unique", label=self.label,
                          row=name, page=page)
        frame = self.scroll_sidebar_to_top()
        # Page boundaries drift between walks (measured: the candidate was one
        # page past where the first walk found it), so the re-walk looks for the
        # row from the top through one page beyond the recorded one.
        for index in range(1, min(page + 2, pages + 1)):
            try:
                frame, rows = self.settled_roster(f"prefix-pick-{index}", SIDEBAR, attempts=6)
            except RuntimeError as error:
                # A re-rendering list is not a reason to lose the pick: the click
                # itself re-captures and refuses if the row moved, so one census
                # is enough evidence to attempt it.
                self.audit.append("escalation", step_id=f"prefix-pick-{index}", reason=str(error))
                frame = self.frame(f"prefix-pick-{index}-single")
                rows = self.read_roster(f"prefix-pick-{index}-single", frame, SIDEBAR)
            row = next((candidate for candidate in rows
                        if self._norm(candidate["text"]) == self._norm(name)
                        and self.project_of_row(rows, candidate) == self.project), None)
            if row is not None:
                self.click_exact_row("prefix-pick", frame, row)
                time.sleep(1.2)
                return True
            if not self.scroll_by(f"prefix-pick-scroll-{index}", frame, [196, 850], -400):
                frame = self.frame(f"prefix-pick-{index}-recapture")
            time.sleep(0.9)
            frame = self.frame(f"prefix-pick-{index}-after")
        self.audit.append("escalation", step_id="prefix-pick", row=name,
                          reason="the candidate row was not on any page when re-walked")
        return False

    def identify_by_content(self, limit=8):
        """Pick the lane whose own transcript carries the marker the order names.

        BigEnergyCo has five sessions that all open with its name, so the name
        cannot choose between them. The transcripts can: the order describes
        `0d7e2f37` as the Codex #466/#467 queue, and a transcript that mentions
        both is that lane. Several or none is a refusal naming the census.
        """
        markers = LANE_MARKERS.get(self.thread, ())
        if not markers:
            return False
        frame = self.scroll_sidebar_to_top()
        seen, hits = [], []
        for page in range(1, 9):
            try:
                frame, rows = self.settled_roster(f"content-{page}", SIDEBAR, attempts=4)
            except RuntimeError as error:
                self.audit.append("escalation", step_id="content-walk", reason=str(error))
                return False
            frame, rows = self.expand_project(page, frame, rows, "content")
            texts = [self._norm(row["text"]) for row in rows]
            if texts in seen:
                break
            seen.append(texts)
            for row in rows:
                if not self._prefix_matches(row["text"], self.label):
                    continue
                if self._norm(row["text"]) in [self._norm(name) for name in hits]:
                    continue
                if limit <= 0:
                    break
                limit -= 1
                try:
                    self.click_exact_row(f"content-{page}-{len(hits)}", frame, row)
                except RuntimeError as error:
                    self.audit.append("escalation", step_id="content-click", reason=str(error))
                    frame = self.frame(f"content-{page}-after")
                    continue
                time.sleep(1.2)
                frame = self.settle_view(f"content-{page}-{len(hits)}-settle", seconds=8)
                lines = self.read_lines(f"content-{page}-{len(hits)}-transcript", frame,
                                        (560, 180, 1720, 900))
                reading = self._norm(" ".join(lines))
                found = all(self._norm(marker) in reading for marker in markers)
                self.audit.append("extraction", step_id=f"content-{page}-{len(hits)}-markers",
                                  row=row["text"], matched=found)
                if found:
                    hits.append(row["text"])
            if not self.scroll_by(f"content-scroll-{page}", frame, [196, 850], -400):
                frame = self.frame(f"content-{page}-recapture")
                continue
            time.sleep(0.9)
            frame = self.frame(f"content-{page}-after")
        if len(hits) != 1:
            self.audit.append("escalation", step_id="content-census", label=self.label,
                              matched=hits[:6], reason="no unique transcript carries the markers")
            return False
        self.audit.append("verification", step_id="content-unique", label=self.label, row=hits[0])
        return self.click_row_by_text(hits[0])

    def click_row_by_text(self, name, pages=8):
        """Re-open one row by its own text, wherever the list now has it."""
        frame = self.scroll_sidebar_to_top()
        for page in range(1, pages + 1):
            try:
                frame, rows = self.settled_roster(f"pick-{page}", SIDEBAR, attempts=6)
            except RuntimeError as error:
                self.audit.append("escalation", step_id="pick-walk", reason=str(error))
                frame = self.frame(f"pick-{page}-single")
                rows = self.read_roster(f"pick-{page}-single", frame, SIDEBAR)
            row = next((row for row in rows if self._norm(row["text"]) == self._norm(name)), None)
            if row is not None:
                self.click_exact_row("pick-row", frame, row)
                time.sleep(1.2)
                self.audit.append("verification", step_id="pick-row", row=row["text"], page=page)
                return True
            if not self.scroll_by(f"pick-scroll-{page}", frame, [196, 850], -400):
                frame = self.frame(f"pick-{page}-recapture")
                continue
            time.sleep(0.9)
            frame = self.frame(f"pick-{page}-after")
        return False

    def identify_by_route(self, limit=8):
        """Open candidate sessions until the app's own route names the pinned thread.

        Configured session names are ours; the app's are not always the same
        string (measured: no session is titled "Lane 2", but one is titled
        "Lane 2 Waist Composition Mission Brief"). The route is the only
        identity the app states itself, so an unnamed lane is resolved by
        opening its candidates and reading what the app says it opened.
        """
        wanted = self._norm(self.label)
        # Opening a candidate types nothing, so this stays available in the
        # select phase; the callers (search and select) are the ones that run
        # before a draft exists, and send never calls it.
        frame = self.scroll_sidebar_to_top()
        frame = self.ensure_search_closed(frame)  # a live dialog covers the list
        seen = []
        for page in range(1, 9):
            try:
                frame, rows = self.settled_roster(f"identify-{page}", SIDEBAR, attempts=3)
            except RuntimeError as error:
                self.audit.append("escalation", step_id="identify-route", reason=str(error))
                return False
            texts = [self._norm(row["text"]) for row in rows]
            if texts in seen:
                break
            seen.append(texts)
            for index, row in enumerate(rows):
                seen_text = self._norm(row["text"])
                # Rows are clipped by the app's own column width (measured:
                # "SCMessenger Audit L"), so a plain substring test misses the
                # very rows this path exists to find.
                if wanted and wanted not in seen_text and not self.row_matches(
                        row["text"], self.label):
                    continue
                if seen_text == wanted:
                    # A bare label is also how the app names project headings
                    # and duplicate sessions; this path exists for the rows the
                    # exact matcher could not settle, so those are not clicked
                    # blind here.
                    continue
                if limit <= 0:
                    return False
                limit -= 1
                try:
                    self.click_exact_row(f"identify-{page}-{index}", frame, row)
                except RuntimeError as error:
                    self.audit.append("escalation", step_id=f"identify-{page}-{index}",
                                      reason=str(error))
                    frame = self.frame(f"identify-{page}-{index}-after")
                    continue
                frame = self.frame(f"identify-{page}-{index}-opened")
                routes = self.routes()
                hit = [route for route in routes if self.thread in route]
                if hit:
                    self.audit.append("verification", step_id="identify-route", row=row["text"],
                                      exact_id=hit[0], exposed=routes[:6])
                    return True
                self.audit.append("extraction", step_id=f"identify-{page}-{index}-routes",
                                  row=row["text"], exposed=routes[:6])
            if not self.scroll_by(f"identify-scroll-{page}", frame, [196, 850], -400):
                frame = self.frame(f"identify-{page}-recapture")
                continue
            time.sleep(0.9)
            frame = self.frame(f"identify-{page}-after")
        return False

    def find_highlighted_row(self, pages=8):
        """Find the selected row wherever the project list has it, read-only."""
        frame = self.scroll_sidebar_to_top()
        seen = []
        for page in range(1, pages + 1):
            try:
                frame, rows = self.settled_roster(f"highlight-{page}", SIDEBAR, attempts=3)
            except RuntimeError as error:
                self.audit.append("escalation", step_id="find-highlight", reason=str(error))
                return None
            texts = [self._norm(row["text"]) for row in rows]
            if texts in seen:
                return None
            seen.append(texts)
            row = self.highlighted_row(frame, rows)
            if row and self.project_of_row(rows, row) == self.project:
                return row
            band = frame.crop((SIDEBAR[0], SIDEBAR[1], SIDEBAR[2], SIDEBAR[3] - 10)).tobytes()
            if not self.scroll_by(f"highlight-scroll-{page}", frame, [196, 850], -400):
                frame = self.frame(f"highlight-{page}-recapture")
                continue
            time.sleep(0.9)
            frame = self.frame(f"highlight-{page}-after")
            if frame.crop((SIDEBAR[0], SIDEBAR[1], SIDEBAR[2], SIDEBAR[3] - 10)).tobytes() == band:
                return None
        return None

    def navigate_by_session_list(self):
        """Open the lane from the project session list: no dialog, no typing."""
        if self.selected_label_matches():
            self.audit.append("verification", step_id="navigate-session-list", state="already open")
            return True
        try:
            if not self.walk_session_list():
                self.audit.append("escalation", step_id="navigate-session-list",
                                  reason=f"{self.label!r} is not in the project session list "
                                         "within the bounded walk")
                return False
        except RuntimeError as error:
            self.audit.append("escalation", step_id="navigate-session-list", reason=str(error))
            return False
        time.sleep(1.2)
        if self.selected_label_matches(wait=8):
            self.audit.append("verification", step_id="navigate-session-list", label=self.label,
                              source="project session list")
            return True
        self.audit.append("escalation", step_id="navigate-session-list",
                          reason="the clicked session row did not become the selected session")
        return False

    def list_only(self):
        """Standup lanes navigate by the session list, never by the dialog.

        The dialog is the last resort in the approved order, and in the filed
        runs it is also the least reliable surface on this app: a toggle that
        closes what it is asked to open, an icon that scrolls out of reach, and
        a result list that shows transcript when the panel is gone. The project
        session list, walked and censused, has been correct every time.
        """
        return self.thread in SESSIONS and self.thread != DISK_THREAD

    def open_search(self):
        frame = self.frame("freebuff-before-search")
        if self.window.api.foreground() != self.window.handle:
            self.verify_freebuff_logo(frame, "identify-freebuff-for-search")
            self.act("search-foreground", FOCUS, {"title": self.window.title})
            frame = self.frame("freebuff-search-foreground")
        self.require_foreground()
        if self.thread == VISION_THREAD and self.standing:
            self.open_vision_seat()
            return
        if self.navigate_by_session_list():
            return
        if self.list_only():
            if (self.navigate_by_unique_prefix() or self.identify_by_content()
                    or self.identify_by_route()):
                return
            raise RuntimeError(f"the project session list does not hold {self.label!r} "
                               "and no candidate exposes this thread's route")
        self.ensure_search_dialog(frame)

    def ensure_search_dialog(self, frame):
        """Open the session-search dialog, verified, without touching the list.

        The narrowed prefix walk needs this field in whichever phase it runs,
        and each phase is its own process, so the dialog is usually closed by
        then. It is opened here by the same verified Search-icon click open_search
        uses - not by open_search itself, which falls back to walking the whole
        list and would put the 240 s cost straight back.
        """
        if self.dialog_open(frame):
            return frame
        frame = self.ensure_search_closed(frame)
        region = (296, 75, 333, 104)
        left, top, _, _ = region
        for attempt in (1, 2):
            pixels = frame.crop(region).convert("L")
            box = pixels.point(lambda level: 255 if level >= 140 else 0).getbbox()
            if box is None or not (8 <= box[2] - box[0] <= 25 and 8 <= box[3] - box[1] <= 25):
                raise RuntimeError("the verified Search icon outline could not be located")
            point = [left + (box[0] + box[2]) // 2, top + (box[1] + box[3]) // 2]
            self.act(f"open-session-search-{attempt}", CLICK,
                     {"control": "FreeBuff session search", "point": point,
                      "size": list(frame.size)})
            try:
                return self.wait_dialog(True, seconds=8)
            except RuntimeError:
                # A toggle that closed a stale dialog reads the same as one that
                # failed to open it; one more verified click settles which it was.
                self.audit.append("escalation", step_id=f"open-session-search-{attempt}",
                                  reason="the dialog was not open after the click")
                frame = self.frame(f"search-open-retry-{attempt}")
        raise RuntimeError("the search dialog did not open after two verified search clicks")

    def open_vision_seat(self):
        """Inspect the observed GitHub-project row, then require the pinned route."""
        frame = self.ensure_search_closed(self.frame("vision-seat-sidebar"))
        for page in range(1, 7):
            frame, rows = self.settled_roster(f"vision-seat-{page}", SIDEBAR, attempts=4)
            matches = [row for row in rows if self.row_matches(row["text"], self.label)]
            if len(matches) > 1:
                raise RuntimeError("more than one visible vision-seat row matched")
            if matches:
                row = matches[0]
                scope = (round(row["x"] - 6), round(row["y"] - 4),
                         round(row["x1"] + 6), round(row["y"] + 20))
                self.yes("vision-seat-row", frame,
                         "Does this label contain the words Vision Driver Standup?", region=scope)
                self.click_exact_row("vision-seat-open", frame, row)
                time.sleep(2)
                self.verify_session_identity()
                return
            if not self.scroll_by(f"vision-seat-scroll-{page}", frame, [196, 850], -400):
                raise RuntimeError("the project sidebar could not advance to the vision seat")
            time.sleep(0.8)
            frame = self.frame(f"vision-seat-after-{page}")
        raise RuntimeError("the vision-seat row was not visible in the bounded project-list walk")

    def wait_dialog(self, open_state, seconds=4):
        """Poll the dialog state until it matches, then return that frame."""
        deadline = time.monotonic() + seconds
        frame = self.frame("dialog-wait")
        while True:
            if self.dialog_open(frame) == open_state:
                return frame
            if time.monotonic() >= deadline:
                state = "open" if open_state else "closed"
                raise RuntimeError(f"the search dialog did not become {state} within {seconds}s")
            time.sleep(0.5)
            frame = self.frame("dialog-wait-again")

    def cross_glyph(self, frame):
        """The dialog's own close control: a small four-cornered X in its header."""
        cross = frame.crop(SEARCH_CLOSE).convert("L").point(lambda level: 255 if level > 160 else 0)
        box = cross.getbbox()
        if not box:
            return False
        x, y, right, bottom = box
        if not (8 <= right - x <= 16 and 8 <= bottom - y <= 16):
            return False
        return all(cross.crop(corner).getbbox() for corner in (
            (x, y, x + 3, y + 3), (right - 3, y, right, y + 3),
            (x, bottom - 3, x + 3, bottom), (right - 3, bottom - 3, right, bottom)))

    def dialog_open(self, frame):
        """The dialog's own text and close control are the state, not a model opinion."""
        if self.cross_glyph(frame):
            return True
        for step, label, region in (("probe-search-placeholder", "Search chats", SEARCH_PLACEHOLDER),
                                    ("probe-search-placeholder-tail", "chats", SEARCH_PLACEHOLDER_TAIL)):
            try:
                self.locate_exact_text(step, frame, label, region)
                return True
            except RuntimeError:
                continue
        return False

    def close_search_if_open(self, frame):
        """Backwards-compatible name for the deterministic dialog reset."""
        return self.ensure_search_closed(frame)

    def ensure_search_closed(self, frame):
        """Reset to a known dismissed dialog state, then re-census until it settles."""
        if not self.dialog_open(frame):
            return frame
        self.audit.append("verification", step_id="search-reset", state="open")
        self.act("close-search-dialog", CLICK, {"control": "FreeBuff search Close",
                                                "point": [1269, 197], "size": list(frame.size)})
        frame = self.wait_dialog(False)
        self.audit.append("verification", step_id="search-reset", state="closed")
        return frame

    def search_for_session(self):
        self.require_foreground()
        if self.list_only():
            if self.selected_label_matches(wait=2):
                self.audit.append("verification", step_id="query-skip",
                                  reason="the target row is already the selected session")
                return
            if (self.navigate_by_session_list() or self.navigate_by_unique_prefix()
                    or self.identify_by_content() or self.identify_by_route()):
                return
            raise RuntimeError(f"the project session list does not hold {self.label!r} "
                               "and no candidate exposes this thread's route")
        if self.selected_label_matches():
            self.audit.append("verification", step_id="query-skip",
                              reason="the target row is already the selected session")
            return
        frame = self.frame("freebuff-before-query")
        if not self.dialog_open(frame):
            # The search phase may have opened the lane from the session list
            # instead, so this phase makes the dialog itself rather than assume it.
            self.audit.append("escalation", step_id="query",
                              reason="no dialog was open; ensuring the lane is open")
            self.open_search()
            if self.selected_label_matches(wait=4):
                return
            frame = self.frame("freebuff-before-query-open")
            if not self.dialog_open(frame):
                raise RuntimeError("the search dialog is not open for the query")
        try:
            point = self.locate_exact_text("locate-search-field", frame, "Search chats",
                                           SEARCH_PLACEHOLDER)
        except RuntimeError:
            frame = self.frame("search-field-caret")
            # A caret can touch the first glyph. Locate the unaffected second word.
            point = self.locate_exact_text("locate-search-field-unobscured", frame, "chats",
                                           SEARCH_PLACEHOLDER_TAIL)
        self.act("focus-search-field", CLICK,
                 {"control": "Search chats field", "point": point, "size": list(frame.size)})
        self.act("query-session", QUERY, {"thread": self.thread, "text": self.label,
                                          "control": "Search chats field"})
        time.sleep(1.4)
        self.frame("freebuff-search-results")

    def select_search_result(self):
        self.require_foreground()
        if self.selected_label_matches():
            self.audit.append("verification", step_id="select-skip",
                              reason="the target row is already the selected session")
            return
        if self.navigate_by_session_list():
            return
        if self.list_only():
            if (self.navigate_by_unique_prefix() or self.identify_by_content()
                    or self.identify_by_route()):
                return
            raise RuntimeError(f"the project session list does not hold {self.label!r} "
                               "and no candidate exposes this thread's route")
        frame = self.frame("before-select-session-0")
        if not self.dialog_open(frame):
            # Each phase is its own process: a phase may not assume the one
            # before it left the dialog standing.
            self.audit.append("escalation", step_id="select",
                              reason="the dialog was closed behind this phase; establishing it")
            self.search_for_session()
            if self.selected_label_matches(wait=3):
                return
            frame = self.frame("before-select-session-reopened")
            if not self.dialog_open(frame):
                raise RuntimeError("the search dialog is not open for the selection")
        frame, rows = self.settled_roster("before-select-session", SEARCH_RESULTS)
        try:
            row = self.click_roster_row("select-existing-session", frame, rows, self.label)
        except RuntimeError:
            # No result carries the configured name: the name is ours, not the
            # app's. Let the app's own route say which candidate this thread is.
            if self.identify_by_route():
                return
            raise
        time.sleep(1.5)
        self.frame("existing-session-selected")
        self.audit.append("verification", step_id="select", row=row["text"],
                          source="settled search results")

    def verify_lane(self, frame):
        self.require_foreground()
        if self.thread != DISK_THREAD:
            # One identity proof for every local lane: the fixed LANE_NAV crop
            # only works while the list happens to be scrolled to it (measured:
            # Lane 1 parked at send with its draft staged and verified when the
            # row had scrolled out of that box).
            self.verify_session_identity()
            return
        if self.thread == DISK_THREAD:
            # Bind Disk Audit to the active session before verifying tab/cache (Codex P1):
            # a global LevelDB UUID hit plus the word 'Disk' can pass while another
            # Disk-labeled session is open.
            sessions = self.routes()
            if sessions:
                matched = [route for route in sessions if self.thread in route]
                if not matched:
                    raise RuntimeError(
                        "the active FreeBuff document does not match Disk Audit (f90f01e9)")
                self.audit.append("verification", step_id="active-session-id", exact_id=matched[0],
                                  exposed=sessions[:8])
            elif not self.selected_exact_session(wait=3):
                raise RuntimeError(
                    "Disk Audit (f90f01e9) could not be bound to the active session")
            self.yes("verify-disk-audit-tab", frame,
                     "Does the selected dark tab show the word 'Disk'?",
                     region=(1436, 0, 1551, 60))
            self.require_cached_session("verify-disk-audit-id", b"f90f01e9-128f-497b-b64f-2662ee4051e0")
            return
        region = LANE_NAV
        if self.scoped_input:
            (_, y), box = self.locate_exact_text("locate-selected-lane1", frame, self.label,
                                                (128, 300, 300, 850), with_bounds=True)
            gray = frame.convert("L")
            samples = [gray.getpixel((x, y)) - gray.getpixel((x, y - 23))
                       for x in (210, 235, 260, 285, 310)]
            if sum(value >= 10 for value in samples) < 4:
                raise RuntimeError("the OCR Lane 1 row has no verified selection highlight")
            self.audit.append("verification", step_id="lane1-selection-highlight", samples=samples)
            region = (box[0] - 6, box[1] - 5, box[2] + 6, box[3] + 5)
            self.require_cached_session("verify-lane1-id", b"315608d2-1531-456b-918a-f7e97db56496")
            self.yes("verify-lane1", frame, "Does the printed text read 'Lane 1'?", region=region)
            return
        self.yes("verify-lane1", frame,
                 "Is the navigation row labeled exactly Lane 1 visibly selected or highlighted "
                 "in the sidebar? Reject a plain unselected row.",
                 region=region)

    def verify_session_identity(self):
        """Prove which session is open, from the app itself.

        The route is the strongest proof, but Chromium only publishes a route
        while its accessibility tree is live, and this window's tree is often
        empty (measured 2026-11-22: zero Document elements on a fresh handle).
        A dead tree is not evidence of the wrong session, so the fallback is
        the settled sidebar with the target's own row highlighted; both
        proofs are recorded, and neither is a model confidence.
        """
        sessions = self.routes()
        if sessions:
            matched = [route for route in sessions if self.thread in route]
            if matched:
                self.audit.append("verification", step_id="active-session-id", exact_id=matched[0],
                                  exposed=sessions[:8])
                return
            self.audit.append("escalation", step_id="active-session-id", exposed=sessions[:8],
                              reason="no exposed route is the pinned thread; trying the selection")
        if self.standing and self.thread == VISION_THREAD:
            self.verify_vision_seat()
            return
        if self.standing and self.thread == SCM_THREAD:
            if self.selected_exact_session():
                derived_uuid = PINNED_UUIDS.get(self.thread) or lookup_local_session_uuid(self.thread)
                self.audit.append("verification", step_id="active-session-id",
                                  route_fallback="exact-scoped-selection",
                                  thread=self.thread, project=self.project,
                                  pinned_uuid=derived_uuid)
                return
            raise RuntimeError("the exact pinned session route is required for this standing dispatch")
        if self.selected_label_matches(wait=3):
            self.audit.append("verification", step_id="active-session-row", label=self.label,
                              source="settled sidebar selection")
            return
        if self.allow_navigation and self.navigate_by_session_list():
            if self.selected_label_matches(wait=3):
                self.audit.append("verification", step_id="active-session-row", label=self.label,
                                  source="re-opened from the project session list")
                return
        row = self.find_highlighted_row()
        if row and self.row_matches(row["text"], self.label):
            self.audit.append("verification", step_id="active-session-row", label=self.label,
                              row=row["text"], source="highlight found in the project list")
            return
        if not self.standing and self.phase == "send" and self.saw_text(
                "send-identity-draft", self.frame("send-identity"),
                (640, 925, 1540, 1045), self.text):
            # Send must never navigate, and the accessibility tree is
            # intermittent. The draft is the one thing that cannot be stale: it
            # was typed into this session by this run's prepare, and the app
            # keeps drafts per session, so its presence in the composer is the
            # identity of the session it was typed into.
            self.audit.append("escalation", step_id="identity-on-draft",
                              reason="no route and no highlighted row; identity rests on the staged draft")
            self.audit.append("verification", step_id="active-session-row", label=self.label,
                              source="exact staged draft in the composer")
            return
        raise RuntimeError("no route and no highlighted sidebar row identified the pinned session "
                           f"({self.label})")

    def verify_vision_seat(self):
        if not self.selected_label_matches(wait=3):
            raise RuntimeError("the vision-seat row was not visibly selected")
        self.require_cached_session("verify-vision-seat-cached-id",
                                    b"6d39cf4f-2469-4f47-8cf0-3948309f5f2b")
        for attempt in range(6):
            frame = self.frame(f"vision-seat-work-{attempt}")
            lines = self.read_lines(f"vision-seat-work-{attempt}", frame, (630, 350, 1550, 750))
            words = self._norm(" ".join(lines))
            if "scmessenger" in words and "obsoleteguard" in words:
                self.yes("verify-vision-seat-work", frame,
                         "Does the text say SCMessenger had an obsolete guard that was being removed?",
                         region=(630, 350, 1550, 750))
                self.audit.append("verification", step_id="vision-seat-identity",
                                  source="selected title, cached UUID, and matching last work")
                return
            draft = self._norm(" ".join(self.read_lines(
                f"vision-seat-draft-{attempt}", frame, (640, 745, 1530, 1048))))
            if "harnessjevvisiondriverfullstandup" in draft and "implementationlane" in draft:
                self.yes("verify-vision-seat-mission", frame,
                         "Does the text describe the harness vision driver full standup mission?",
                         region=(640, 745, 1530, 1048))
                self.audit.append("verification", step_id="vision-seat-identity",
                                  source="selected title, cached UUID, and matching mission draft")
                return
            time.sleep(2)
        raise RuntimeError("the vision-seat selected view did not expose the expected last work")

    def resume_vision_mission(self):
        frame = self.settle_view("vision-before-resume")
        self.verify_session_identity()
        if self.stop_visible(frame):
            raise RuntimeError("the requested session is already running; no restart input")
        options = {"resume": "A visible button labeled Resume mission.",
                   "other": "No button labeled Resume mission is visible."}
        route = self.choose("vision-resume-route", frame, "Which button is visible?", options,
                            region=(630, 590, 1550, 960))
        if route == "other":
            self.prepare_draft()
            self.send_draft()
            return
        region = (630, 590, 1550, 960)
        point, box = self.locate_exact_text("vision-resume-ocr", frame, "Resume mission", region, with_bounds=True)
        scope = (box[0] - 6, box[1] - 5, box[2] + 6, box[3] + 5)
        self.yes("vision-resume-confirm", frame, "Does the button say Resume mission?", region=scope)
        fresh = self.frame("vision-resume-readback")
        if fresh.crop(scope).tobytes() != frame.crop(scope).tobytes():
            raise RuntimeError("the Resume mission control changed before input")
        self.act("vision-resume", CLICK,
                 {"control": "Vision Driver Resume mission", "point": point, "size": list(frame.size)})
        time.sleep(2)
        frame = self.frame("vision-resume-response")
        self.verify_session_identity()
        if self.stop_visible(frame):
            self.audit.append("verification", step_id="vision-running-after-resume", stop_cue=True)
            return
        region = (500, 180, 1600, 1100)
        point, box = self.locate_exact_text("vision-start-ocr", frame, "Start mission", region, with_bounds=True)
        scope = (box[0] - 6, box[1] - 5, box[2] + 6, box[3] + 5)
        self.yes("vision-start-confirm", frame, "Does the button say Start mission?", region=scope)
        fresh = self.frame("vision-start-readback")
        if fresh.crop(scope).tobytes() != frame.crop(scope).tobytes():
            raise RuntimeError("the Start mission control changed before input")
        self.act("vision-start", CLICK,
                 {"control": "Vision Driver Start mission", "point": point, "size": list(frame.size)})
        time.sleep(3)
        frame = self.frame("vision-start-response")
        self.verify_session_identity()
        if not self.stop_visible(frame):
            raise RuntimeError("Start mission was clicked but a running Stop cue was not verified")
        self.audit.append("verification", step_id="vision-running-after-start", stop_cue=True)

    def start_staged_vision(self, *, focus_cure=False):
        """Complete the staged mission produced by the recorded Resume action."""
        started = time.monotonic()
        frame = self.frame("vision-start-before-focus")
        if self.window.api.foreground() != self.window.handle:
            self.verify_freebuff_logo(frame, "vision-start-window")
            self.act("vision-start-foreground", FOCUS, {"title": self.window.title})
        frame = self.settle_view("vision-staged-before-start")
        self.verify_session_identity()
        if self.stop_visible(frame):
            raise RuntimeError("the requested session is already running; no restart input")
        draft = self._norm(" ".join(self.read_lines("vision-staged-heading", frame, (640, 745, 1530, 1048))))
        if "harnessjevvisiondriverfullstandup" not in draft:
            raise RuntimeError("the resumed vision mission is not visibly staged")
        self.yes("vision-staged-mission", frame,
                 "Does this editor contain the harness vision driver full standup mission?",
                 region=(640, 745, 1530, 1048))
        region = SEND_CONTROL
        self.yes("vision-staged-start-arrow", frame,
                 "Does this crop show a white button containing a black upward arrow?", region=region)
        left, top, _, _ = region
        outline = frame.crop(region).convert("L").point(lambda level: 255 if level >= 205 else 0).getbbox()
        if outline is None or not (26 <= outline[2] - outline[0] <= 47 and 26 <= outline[3] - outline[1] <= 47):
            raise RuntimeError("the staged mission's arrow outline was not located")
        point = [left + (outline[0] + outline[2]) // 2, top + (outline[1] + outline[3]) // 2]
        fresh = self.frame("vision-staged-before-click")
        if fresh.crop(COMPOSER).tobytes() != frame.crop(COMPOSER).tobytes():
            raise RuntimeError("the staged mission changed before the start action")
        self.verify_session_identity()
        if time.monotonic() - started > 60:
            raise RuntimeError("the staged mission verification expired before start")
        suffix = "-focus-cure" if focus_cure else ""
        marker = (Path(os.environ["LOCALAPPDATA"]) / "harness-freebuff-runner" /
                  f"vision-start-7111294374{suffix}.json")
        with marker.open("x", encoding="utf-8") as handle:
            json.dump({"thread": self.thread, "step": "vision-start-staged"}, handle)
        self.act("vision-submit-staged-mission", CLICK,
                 {"control": "Vision Driver staged mission start arrow", "point": point, "size": list(frame.size)})
        for attempt, delay in enumerate((2, 8, 15), start=1):
            time.sleep(delay)
            current = self.frame(f"vision-staged-response-{attempt}")
            running = self.stop_visible(current)
            if running and attempt == 3:
                self.audit.append("verification", step_id="vision-running", stop_cue=True,
                                  observation_seconds=25)
                return
            if not running:
                notice = self._norm(" ".join(self.read_lines(
                    f"vision-staged-notice-{attempt}", current, (630, 350, 1550, 960))))
                draft = self._norm(" ".join(self.read_lines(
                    f"vision-staged-returned-draft-{attempt}", current, (640, 745, 1530, 1048))))
                if ("yourfreesessionhasexpired" in notice
                        and "harnessjevvisiondriverfullstandup" in draft):
                    raise RuntimeError("platform returned the staged mission with: Your free session has expired. "
                                       "Send your message again to start a new one.")
        raise RuntimeError("the staged mission was submitted once but a sustained Stop cue was not verified")

    def verify_active_session(self):
        sessions = self.routes()
        if len(sessions) != 1 or self.thread not in sessions[0]:
            raise RuntimeError("the active FreeBuff document did not expose the exact pinned thread")
        self.require_foreground()
        self.audit.append("verification", step_id="active-session-id", exact_id=sessions[0])

    def read_app_structure(self, *options):
        hwnd = self.require_foreground()
        helper = Path(__file__).with_name("windows_freebuff_active_session.ps1")
        result = osal.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-File",
                           str(helper), "-Window", str(hwnd), *options], timeout=8)
        if not result.ok:
            raise RuntimeError("the scoped FreeBuff accessibility evidence could not be read")
        self.require_foreground()
        return json.loads(result.stdout)

    def verify_freebuff_logo(self, frame, step):
        hwnd = self.window.require_window()
        box = (87, 73, 218, 107)
        self.locate_exact_text(f"{step}-ocr", frame, "Freebuff", box)
        self.audit.append("verification", step_id=step, hwnd=hwnd, pid=self.window.process,
                          exact_label="Freebuff", source="native-window-and-ocr")

    def require_cached_session(self, step, session_id):
        profile = Path(os.environ["APPDATA"]) / "Freebuff" / "Partitions"
        stores = ("*/Local Storage/leveldb", "*/IndexedDB/https_freebuff.com_0.indexeddb.leveldb")
        for store in stores:
            for root in profile.glob(store):
                for path in root.iterdir():
                    if path.suffix not in (".log", ".ldb"):
                        continue
                    try:
                        with path.open("rb") as handle:
                            tail = b""
                            while block := handle.read(1024 * 1024):
                                data = tail + block
                                if session_id in data:
                                    self.audit.append("extraction", step_id=step,
                                                      exact_id=session_id.decode("ascii"), store=store)
                                    return
                                tail = data[-len(session_id):]
                    except OSError:
                        continue
        raise RuntimeError("the exact UUID was absent from the FreeBuff session stores")

    def read_lines(self, step, frame, region):
        left, top, right, bottom = region
        crop = frame.crop(region)
        crop = crop.resize((crop.width * 3, crop.height * 3))
        path = (self.output / f"{step}-text.png").resolve()
        self.image_ops.invert(self.image_ops.grayscale(crop)).save(path)
        result = osal.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-File",
                           str(Path(__file__).with_name("windows_ocr_exact.ps1")),
                           "-Path", str(path), "-ReadLines"], timeout=10)
        if not result.ok:
            return []
        return [(line.get("text") or "").strip()
                for line in json.loads(result.stdout).get("lines") or []]

    def saw_text(self, step, frame, region, wanted):
        """Is this text on screen, allowing the slips the OCR engine makes?"""
        lines = self.read_lines(step, frame, region)
        reading = self._norm(" ".join(lines))
        target = self._norm(wanted)
        self.audit.append("extraction", step_id=f"{step}-reading", text=reading[:300])
        if not target or not reading:
            return False
        if target in reading:
            return True
        return SequenceMatcher(None, target, reading).ratio() >= 0.9

    def verify_draft(self, frame):
        pointer = self.text == DISK_POINTER
        region = (644, 949, 1528, 1039) if pointer else (640, 925, 1540, 1045)
        if pointer:
            self.locate_exact_text("read-exact-draft", frame, self.text, region, whole=True)
        elif not self.saw_text("read-exact-draft", frame, region, self.text):
            time.sleep(0.4)  # A blinking caret can obscure the last OCR glyph.
            frame = self.frame("draft-ocr-retry")
            self.verify_lane(frame)
            if not self.saw_text("read-exact-draft-retry", frame, region, self.text):
                raise RuntimeError(f"the draft was not read back as {self.text!r}")
        self.yes("verify-staged-text", frame,
                 ("Is this user-entered text a D-007 mission pointer?" if pointer else
                  f"Does the visible text read exactly '{self.text}'?"),
                 region=region)
        return frame

    def prepare_pointer(self):
        self.text = DISK_POINTER
        self.goal = "Steer the running verified Disk Audit session to the pinned D-007 artifact."
        frame = self.frame("disk-before-steering")
        self.verify_lane(frame)
        region = (645, 944, 1170, 1015)
        self.yes("verify-disk-queue", frame,
                 "Does the empty composer placeholder say 'added to the queue'?",
                 region=region)
        point = self.locate_exact_text("locate-empty-queue", frame,
                                       "Type a message — added to the queue", region)
        self.act("focus-disk-composer", CLICK,
                 {"control": f"{self.label} composer", "point": point, "size": list(frame.size)})
        self.act("type-d007-pointer", TYPE, {"text": self.text})
        time.sleep(3)
        self.verify_draft(self.frame("disk-pointer-staged"))

    def prior_send_refused_before_input(self):
        """Did the prior marker's send-once fail before the renderer click?"""
        trace = self.output / "driver.jsonl"
        if not trace.is_file():
            return False
        for line in trace.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if (row.get("kind") == "action" and row.get("step_id") == "send-once"
                    and not row.get("ok")):
                return "FreeBuff is not the foreground window" in row.get("detail", "")
        return False

    def type_literal(self, text):
        """Type a project name into a field this adapter already focused."""
        self.require_foreground()
        keyboard = osal._WindowsInputApi()
        for character in text:
            keyboard.type_text(character)
        self.audit.append("verification", step_id="project-name-typed", text=text)

    def create_project(self, name):
        """R10: create the project and hand back the row that now names it."""
        row = create_project(self, name)
        self.label = name
        self.handoff = row
        return row

    def send_draft(self):
        pointer = self.text == DISK_POINTER
        operation = "steer" if pointer else "send"
        marker = self.output.parent / f"harness-freebuff-{self.thread}-{operation}-20261122.json"
        if marker.exists():
            if not self.prior_send_refused_before_input():
                raise RuntimeError("the one-send marker already exists; inspect the prior outcome")
            # A refused foreground check dispatched no input, so the marker was
            # never consumed; park it and let the verified retry use the budget.
            marker.replace(marker.with_name(marker.name + ".aborted"))
            self.audit.append("escalation", step_id="send-marker-released",
                              reason="the prior send-once was refused before any input")
        frame = self.frame("lane1-before-send")
        if self.reestablish_if_reloaded("send"):
            frame = self.frame("lane1-before-send-recovered")
        self.verify_lane(frame)
        # Identity may have re-opened the lane from the project list after a
        # reload. Read the draft on a frame captured after that, and start the
        # send window at this read rather than at the stale pre-identity one.
        frame = self.frame("lane1-after-identity")
        observed_at = time.monotonic()
        frame = self.verify_draft(frame)
        if self.scoped_input and not pointer and self.turn_running(frame):
            raise RuntimeError("the requested session resumed before send; no restart input")
        region = (1439, 1040, 1487, 1105) if pointer else SEND_CONTROL
        self.yes("verify-send-arrow", frame,
                 "Does this image show a white button containing a black upward arrow?",
                 region=region)
        left, top, _, _ = region
        crop = frame.crop(region).convert("L")
        box = crop.point(lambda level: 255 if level >= 205 else 0).getbbox()
        if box is None or not (26 <= box[2] - box[0] <= 47 and 26 <= box[3] - box[1] <= 47):
            raise RuntimeError("the verified Send button outline could not be located")
        point = [left + (box[0] + box[2]) // 2, top + (box[1] + box[3]) // 2]
        control = f"{self.label} queue arrow" if pointer else f"{self.label} Send (up arrow)"
        params = {"thread": self.thread, "text": self.text, "control": control,
                  "point": point, "size": list(frame.size)}
        self.require_foreground()
        if self.thread in BURN_SESSIONS or self.thread == SCM_THREAD:
            # Identity, not the route alone: a dead accessibility tree must not
            # become a dead-end at the click.
            self.verify_session_identity()
        if self.standing:
            fresh = self.frame("pre-send-readback")
            if (frame.crop(COMPOSER).tobytes() != fresh.crop(COMPOSER).tobytes()
                    or (not pointer and self.turn_running(fresh))):
                raise RuntimeError("composer changed between verification and send")
        age = time.monotonic() - observed_at
        if age > 60:
            raise RuntimeError("the verified session and composer observations expired before send")
        self.audit.append("verification", step_id="pre-send-freshness", age_seconds=round(age, 3))
        self.send_deadline = observed_at + 60
        self.send_composer = frame.crop(COMPOSER).tobytes() if self.standing else None
        with marker.open("x", encoding="utf-8") as handle:
            json.dump({"thread": self.thread, "step": f"{operation}-once", "text": self.text,
                       "evidence": self.output.name}, handle)
        self.act(f"{operation}-once", SEND, params)
        if pointer:
            time.sleep(2)
            response_frame = self.frame("disk-steering-response")
            notice = self.platform_refusal_notice("disk-steering-refusal", response_frame)
            if notice:
                self.audit.append("escalation", step_id="platform-refused", reason=notice)
                print(f"Platform state: refused: {notice}")
                raise RuntimeError(f"platform refused steering: {notice}")
            print("Platform state: running")
            return
        for observation, delay in enumerate((1.2, 2.0, 3.0, 5.0), start=1):
            time.sleep(delay)
            frame = self.frame(f"platform-response-{observation}")
            if not self.stop_visible(frame):
                notice = self.platform_refusal_notice(f"platform-refusal-{observation}", frame)
                if notice:
                    self.audit.append("escalation", step_id="platform-refused", reason=notice)
                    print(f"Platform state: refused: {notice}")
                    raise RuntimeError(f"platform refused restart: {notice}")
                continue
            try:
                self.locate_exact_text("verify-queue-placeholder", frame,
                                       QUEUE_PLACEHOLDER, QUEUE_REGION)
            except RuntimeError:
                continue
            self.verify_lane(frame)
            working_seconds = self.working_banner("verify-working-seconds", frame)
            self.audit.append("verification", step_id="platform-running",
                              target=self.thread, stop_cue=True,
                              working_seconds=working_seconds)
            print("Platform state: running")
            return
        print("Platform state: refused: Stop square and exact queue placeholder were not verified")
        raise RuntimeError("one send dispatched; the Stop square and exact queue placeholder were not verified")

    def platform_refusal_notice(self, step, frame):
        """Return a named refusal/expiry string if FreeBuff displayed one after send."""
        lines = self.read_lines(step, frame, (630, 350, 1550, 960))
        joined = " ".join(lines)
        reading = self._norm(joined)
        markers = (
            ("yourfreesessionhasexpired", "free session expired"),
            ("usagelimit", "usage limit notice"),
            ("ratelimit", "rate limit notice"),
            ("failedtosend", "failed to send message"),
            ("errorsubmitting", "error submitting message"),
        )
        for needle, label in markers:
            if needle in reading:
                return f"{label}: {joined[:160]}".strip()
        return None

    def settle_view(self, step, seconds=12):
        """A session view still rendering its transcript is not a composer state.

        Pixel equality is the wrong test here: a focused composer blinks a
        caret, so the band never repeats byte for byte. Settled means the
        change has fallen to caret-sized noise, not zero.
        """
        from PIL import ImageChops, ImageStat

        deadline = time.monotonic() + seconds
        frame = self.frame(f"{step}-0")
        previous = None
        while True:
            current = frame.crop(COMPOSER).convert("L")
            if previous is not None:
                drift = ImageStat.Stat(ImageChops.difference(previous, current)).mean[0]
                if drift <= 0.8:
                    self.audit.append("verification", step_id=f"{step}-settled", drift=round(drift, 3))
                    return frame
            if time.monotonic() >= deadline:
                raise RuntimeError(f"{step}: the session view did not settle within {seconds}s")
            previous = current
            time.sleep(0.7)
            frame = self.frame(f"{step}-settle")

    def composer_written_route(self, written, placeholder):
        """What the composer's own text says, before any model opinion.

        Measured R18: the SCM lane's composer held a staged mission preamble
        while Jev answered "stop" at 0.67, so typing would have appended to a
        foreign order. The text is not an opinion, and a draft that is not
        this lane's continuation is refused by name.
        """
        reading = self._norm(" ".join(written))
        if not reading or self._norm(placeholder) in reading:
            return None
        if self._norm(self.text) and self._norm(self.text) in reading:
            return "staged"
        return "foreign"

    def prepare_draft(self):
        if not getattr(self, "recovering", False):
            self.reestablish_if_reloaded("prepare")
        frame = self.settle_view("lane1-before-draft")
        self.verify_lane(frame)
        if self.scoped_input and self.turn_running(frame):
            raise RuntimeError("the requested session is already running; no restart input")
        # Primary-source cues before the model: a live stop control means the
        # lane is mid-turn (no restart input), and the placeholder's own glyphs
        # mean an empty editor. Jev decides only what these cannot (measured:
        # a 0.53 'stop' guess on a composer the OCR could read outright).
        point = None
        placeholder = "Ask Freebuff... Use / for commands, @ for files"
        try:
            point = self.locate_exact_text("locate-empty-placeholder", frame, placeholder,
                                           (646, 950, 1260, 1014))
            route = "placeholder"
            self.audit.append("verification", step_id="composer-placeholder-ocr",
                              source="exact OCR, not a model choice")
        except RuntimeError:
            banner_lines = self.read_lines("composer-expired-banner", frame, EXPIRED_BANNER_REGION)
            staged_lines = self.read_lines("composer-staged-mission", frame, (640, 745, 1530, 1048))
            if expired_with_staged_mission(banner_lines, staged_lines):
                self.audit.append("verification", step_id="composer-expired-staged-mission",
                                  source="exact OCR, not a model choice")
                # R7: resolve the expired state instead of refusing it. The
                # staged mission is the owner's work, so Resume then Start is
                # the only path that does not overwrite it with the continuation
                # - and no continuation is sent afterwards.
                self.resume_outcome = resume_staged_session(self, frame)
                self.audit.append("verification", step_id="restart-path-resumed",
                                  state=self.resume_outcome)
                return
            written = self.read_lines("composer-written", frame, COMPOSER_TEXT)
            route = self.composer_written_route(written, placeholder)
            if route == "foreign":
                raise RuntimeError(
                    "composer-route: the composer holds a foreign draft, not "
                    f"{self.text!r}; not typing over it "
                    f"({self._norm(' '.join(written))[:120]!r})") from None
            if route is None:
                route = self.choose("composer-route", frame,
                                "Read the controls in this composer screenshot. Which is visible?", {
                                "staged": "Solid lowercase text 'continue in full' with"
                                          " an up-arrow send button.",
                                "empty": "Dim suggestion text with a small visible Tab badge"
                                         " below it and a waveform icon at lower right.",
                                "placeholder": "Ask Freebuff... Use / for commands, @ for files"
                                               " is the only text in the editor, with a waveform button.",
                                "resume": "A button labeled Resume mission.",
                                    "stop": "A stop square, an unrelated draft, or no recognizable state.",
                                }, region=COMPOSER)
        if route == "staged":
            self.verify_draft(frame)
            return
        if route == "placeholder":
            if point is None:
                point = self.locate_exact_text("locate-empty-placeholder", frame, placeholder,
                                               (646, 950, 1260, 1014))
        elif route == "empty":
            self.yes("verify-empty-editor", frame,
                     "Is there a small button or badge labeled Tab below the gray text?",
                     region=(642, 937, 1195, 1048))
            point = self.locate_exact_text("locate-tab-hint", frame, "Tab", (646, 1007, 707, 1051))
            point[1] -= 68
        else:
            raise RuntimeError(f"composer-route: stopped on {route!r} without typing")
        self.act("focus-verified-composer", CLICK,
                 {"control": f"{self.label} composer", "point": point, "size": list(frame.size)})
        self.act("type-continuation", TYPE, {"text": self.text})
        time.sleep(1.5)
        frame = self.frame("lane1-draft-ready")
        self.verify_draft(frame)

    def turn_ended_banner(self, frame):
        """Has the app itself said this turn is over?

        Measured 2026-11-23: the send control flickers the solid stop glyph on
        an ended turn whose banner reads "This turn reached the 120-minute
        limit ... send a message to continue". The banner is the app's own
        statement that the turn has ended, so it outranks the glyph.
        """
        lines = self.read_lines("turn-ended-banner", frame, (640, 650, 1540, 790))
        reading = self._norm(" ".join(lines))
        return any(marker in reading for marker in (
            "120minutelimit", "sendamessagetocontinue", "pausedbecauseitshourended"))

    def working_banner(self, step, frame):
        """Read 'Working for Ns' from the FreeBuff status strip as a second running signal (I-1)."""
        lines = self.read_lines(step, frame, (630, 820, 1550, 960))
        match = re.search(r"\bworking\s+for\s+(\d+)\s*s\b", " ".join(lines), re.I)
        if not match:
            return None
        seconds = int(match.group(1))
        self.audit.append("extraction", step_id=step, working_seconds=seconds)
        return seconds

    def corroborates_running(self, frame, *, github_advanced=False):
        """I-3: a New-chat home frame never corroborates a running lane without GitHub advancement."""
        if github_advanced:
            return True
        if self.reloaded(frame):
            return False
        return bool(self.turn_running(frame) or self.working_banner("corroborate-working", frame) is not None)

    def turn_running(self, frame):
        return self.stop_visible(frame) and not self.turn_ended_banner(frame)

    @staticmethod
    def stop_visible(frame):
        if frame.size != (1800, 1131):
            raise RuntimeError("unsupported frame geometry for the running-turn cue")
        patch = frame.crop((1501, 1066, 1513, 1078)).convert("L")
        return sum(value < 60 for value in patch.get_flattened_data()) >= 101

    def observe_running(self):
        if self.thread != THREAD:
            raise RuntimeError("the separate-lane observation is bound to Lane 1")
        frame = self.frame("before-bystander-navigation")
        if self.window.api.foreground() != self.window.handle:
            self.verify_freebuff_logo(frame, "identify-freebuff-for-observation")
            self.act("observation-foreground", FOCUS, {"title": TITLE})
            frame = self.frame("bystander-navigation")
        self.require_foreground()
        frame = self.close_search_if_open(frame)
        point, box = self.locate_exact_text("locate-bystander-lane", frame, "Lane 1",
                                            (128, 300, 300, 850), with_bounds=True)
        region = (box[0] - 6, box[1] - 5, box[2] + 6, box[3] + 5)
        self.yes("verify-bystander-navigation", frame, "Does the printed text read 'Lane 1'?", region=region)
        fresh = self.frame("bystander-navigation-readback")
        if frame.crop(region).tobytes() != fresh.crop(region).tobytes():
            raise RuntimeError("the bystander navigation row moved before selection")
        self.act("navigate-to-bystander", CLICK, {
            "control": "Lane 1 sidebar navigation", "point": point, "size": list(frame.size),
        })
        time.sleep(1.5)
        frame = self.frame("observed-stop")
        self.verify_lane(frame)
        if not self.stop_visible(frame):
            raise RuntimeError("the separate Lane 1 Stop square is absent")
        self.locate_exact_text("observe-running-queue", frame, QUEUE_PLACEHOLDER, QUEUE_REGION)
        working_seconds = self.working_banner("bystander-working-seconds", frame)
        sha256 = hashlib.sha256((self.output / "observed-stop.png").read_bytes()).hexdigest()
        self.audit.append("verification", step_id="bystander-stop", stop_cue=True,
                          thread=self.thread, working_seconds=working_seconds, sha256=sha256)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--phase", choices=("open", "search", "query", "select", "prepare",
                                           "send", "steer-prepare", "steer-send", "observe-running", "vision-resume",
                                           "vision-start-staged", "vision-start-focus-cure"),
                        default="open")
    parser.add_argument("--thread", choices=tuple(SESSIONS), default=THREAD)
    parser.add_argument("--scoped-input", action="store_true")
    parser.add_argument("--standing", action="store_true")
    args = parser.parse_args()
    key = os.environ.pop("TYPESAFE_API_KEY", "")
    if not key:
        parser.error("the trusted child needs the existing TypeSafe key")
    args.evidence.mkdir()
    dispatch = Dispatch(args.evidence, key, thread=args.thread, scoped_input=args.scoped_input,
                        standing=args.standing)
    dispatch.allow_navigation = args.phase in {"prepare", "send"}
    dispatch.phase = args.phase
    try:
        if args.phase == "open":
            if args.thread != THREAD:
                raise RuntimeError("use verified search for this session")
            dispatch.open_lane()
        elif args.phase == "observe-running":
            dispatch.observe_running()
        elif args.phase == "vision-resume":
            if args.thread != VISION_THREAD or not args.standing:
                raise RuntimeError("vision resume requires the standing pinned vision seat")
            dispatch.resume_vision_mission()
        elif args.phase in {"vision-start-staged", "vision-start-focus-cure"}:
            if args.thread != VISION_THREAD or not args.standing:
                raise RuntimeError("vision start requires the standing pinned vision seat")
            dispatch.start_staged_vision(focus_cure=args.phase == "vision-start-focus-cure")
        elif args.phase == "search":
            dispatch.open_search()
        elif args.phase == "query":
            dispatch.search_for_session()
        elif args.phase == "select":
            dispatch.select_search_result()
        elif args.phase == "steer-prepare":
            if args.thread != DISK_THREAD:
                raise RuntimeError("D-007 steering is authorized only for Disk Audit")
            dispatch.prepare_pointer()
        elif args.phase == "steer-send":
            if args.thread != DISK_THREAD:
                raise RuntimeError("D-007 steering is authorized only for Disk Audit")
            dispatch.text = DISK_POINTER
            dispatch.goal = "Steer the running verified Disk Audit session to the pinned D-007 artifact."
            dispatch.send_draft()
        elif args.phase == "prepare":
            # The old refusal for SCMessenger's composer is gone: prepare now
            # proves the composer route and reads the draft back, and send
            # proves identity and the exact staged text, which is the scoping
            # that guard was standing in for (measured: Lane 1, Lane 2 and
            # Harness Audit all send through this same composer path).
            dispatch.prepare_draft()
            if getattr(dispatch, "resume_outcome", None):
                # The staged mission is already running: stop the phase list
                # here so the runner never sends the continuation over it.
                print(f"Platform state: {RESUMED_WITHOUT_SEND} via {dispatch.resume_outcome}")
        else:
            dispatch.send_draft()
    except (OSError, RuntimeError, KeyError, TypeError, ValueError) as error:
        dispatch.audit.append("escalation", step_id="dispatch", reason=str(error))
        print(f"BLOCKED: {error}")
        return 1
    print(json.dumps(dispatch.audit.verify().to_dict()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
