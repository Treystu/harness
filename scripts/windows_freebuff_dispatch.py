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
from datetime import datetime, timezone
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
# A1 (owner ruling 2026-11-26, #684 c.7208601549): a composer holding
# unrecognizable machine text is not an owner draft, so it is dismissed and the
# approved continuation is typed after it. The action carries the control it
# dismisses so the executor can refuse a request aimed anywhere else.
CLEAR = Action("clear_freebuff_composer", MUTATING, "clear_freebuff_composer",
               ("control",),
               "Dismiss composer text that is not the owner's draft, after that "
               "text is relayed verbatim on #684.", "gui")
VOCABULARY = Vocabulary("windows-freebuff-dispatch", "1.3.0",
                        [FOCUS, CLICK, TYPE, SEND, QUERY, SCROLL, CLEAR])
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
    # Measured 2026-11-24 23:38 HST by the read-only local lookup (the same call
    # that pinned Lane 1 and Disk Audit), after the corrected fleet order found
    # CivicScope had no addressable identity at all.
    "46472fcc": "46472fcc-ca7e-469b-806a-1e05e5bb8d00",
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
    "0d7e2f37": "BigEnergyCo Full Burndown",
    "7d4a9b14": "Kalshi Paper Burndown",
    "9ecc3453": "Lane 2",
    "918dad1a": "Harness Audit Lane",
    "0319b9f6": "SCMessenger Audit Lane",
    "46472fcc": "CivicScope",
    "26646448": "Agensi Lane Queue Executi",
}
# Some lanes were created with a friendly name that the app never adopted: it
# titled the session itself and there is no rename control, so a census can
# never find the lane by the name the dispatch uses (measured 2026-11-27: Lane 2
# `9ecc3453` is the row "Carrier Census Verifica-" under the Harness heading,
# and every pick refused it as absent). The title below is the app's, read from
# the live sidebar; the label stays the name the dispatch and the receipts use.
SESSION_TITLES = {
    "9ecc3453": "Carrier Census Verification Mission",
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
    "46472fcc": "civicscope(cloud)",
    "26646448": "Agensi Skills Local",
}
PROJECT_HEADINGS = ("GitHub", "harness CLOUD", "Harness", "SCMessenger",
                    "Kalshi-Trader", "BigEnergyCo CLOUD", "BigEnergyCo",
                    "Agensi Skills Local", "agensi-skills", "civicscope(cloud)")
COMPOSER = (630, 918, 1550, 1110)
# The editor's own text band only: the toolbar below it carries labels
# (Build/Plan/Mission/Skills) that are not a draft.
COMPOSER_TEXT = (650, 930, 1520, 1050)
# An empty composer's own placeholder, as this app has worded it. The current one
# normalizes to thirty unbroken letters, which is exactly the shape the
# machine-text rule treats as a platform label - so an empty composer was being
# relayed and "cleared" as if it held a robot's text (measured 2026-11-27,
# dyn-7228544294: "composer-route: the machine text survived the clear
# ('typeamessagesentbeforethequeue')"). The placeholder list is therefore part of
# the route, not a guess: text that matches one of these is an empty composer.
COMPOSER_PLACEHOLDERS = (
    "Ask Freebuff... Use / for commands, @ for files",
    "Type a message — sent before the queue",
    "Type a message - sent before the queue",
    "Type a message",
)
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
# The open session's own title, top-left of the transcript pane: measured
# 2026-11-27 on dyn-7227296013's after capture (1800x1131), where the strip reads
# "Code | Chat | Lane 1". This is the app stating which session is open, which
# is a stronger identity than a selection band the theme may not paint.
OPEN_TAB_REGION = (350, 6, 900, 42)
SEARCH_CLOSE = (1257, 185, 1278, 207)
COUNTS = (6, 16, 26, 36, 46)


# A3 (2026-11-27, #684 c.7219862556): the standing watch parked Lane 1 on
# 'sidebar-top-10-after: capture exceeded 5s on 2 attempts (last 5.321s)'. A
# capture is a snapshot, so a frame that lands just past the last budget is a
# slow render, not a lost identity - the third attempt runs under a budget wide
# enough to absorb the measured case, and only then does the run escalate.
CAPTURE_BUDGETS = (2.0, 5.0, 10.0)
_COMPOSER_SIZE = (COMPOSER[2] - COMPOSER[0], COMPOSER[3] - COMPOSER[1])


def _crop_rgb_bytes(crop):
    if crop is None:
        return b"", None
    if isinstance(crop, (bytes, bytearray, memoryview)):
        return bytes(crop), None
    return crop.tobytes(), getattr(crop, "size", None)


def composer_unchanged(before_crop, after_crop, *, size=_COMPOSER_SIZE,
                       diff_threshold=12):
    """Compare COMPOSER crops while tolerating only Electron's 1x25px blinking caret.

    Measured 2026-11-25 across dyn-7149910847, dyn-7153590244, and dyn-7153647643
    (#684 7153690483): glyphs in 'continue in full' span 16px vertically while the
    focused insertion caret spans 1px x 25px (lit_pixels=25, density=1.00, well
    above the toolbar). Raw .tobytes() equality trips whenever the caret blinks
    between captures. Only a 1-2px wide, 21-30px tall solid vertical bar inside the
    text editor interior is tolerated; any glyph, punctuation, suggestion, banner,
    or toolbar change returns False.
    """
    before_bytes, b_size = _crop_rgb_bytes(before_crop)
    after_bytes, a_size = _crop_rgb_bytes(after_crop)
    if before_bytes == after_bytes:
        return True
    width, height = b_size or a_size or size
    expected_len = width * height * 3
    if len(before_bytes) != expected_len or len(after_bytes) != expected_len:
        return False
    row_bytes = width * 3
    min_x, max_x = width, -1
    min_y, max_y = height, -1
    lit_pixels = 0
    inner_right = width - 30
    inner_bottom = min(height, 115)
    for y in range(height):
        row_start = y * row_bytes
        row_end = row_start + row_bytes
        if before_bytes[row_start:row_end] == after_bytes[row_start:row_end]:
            continue
        if y < 15 or y >= inner_bottom:
            return False
        for x in range(width):
            off = row_start + x * 3
            if (abs(before_bytes[off] - after_bytes[off]) > diff_threshold
                    or abs(before_bytes[off + 1] - after_bytes[off + 1]) > diff_threshold
                    or abs(before_bytes[off + 2] - after_bytes[off + 2]) > diff_threshold):
                if x < 10 or x >= inner_right:
                    return False
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y
                lit_pixels += 1
    if max_x < min_x or max_y < min_y:
        return True
    box_w = max_x - min_x + 1
    box_h = max_y - min_y + 1
    if not (1 <= box_w <= 2 and 21 <= box_h <= 30):
        return False
    return lit_pixels >= int(box_w * box_h * 0.85)


# R10: the New-project dialog as exact OCR anchors. Each entry is the control's
# printed label and the region it must appear in; a missing anchor is a refusal,
# never a guessed click. The register closes this adapter on Stage 3 evidence.
PROJECT_DIALOG = {
    "new": ("New project", (60, 60, 340, 200)),
    "name": ("Project name", (480, 280, 1520, 760)),
    "create": ("Create project", (480, 620, 1520, 1120)),
}
JSON_ACT = 0


NARROW_FLAG = "narrow-walk.flag"


def narrowing_enabled(appdata=None):
    """Is the narrowed walk switched on for this machine?

    The narrowed path is being proven against the live panel one claim at a
    time, so it is opt-in rather than default: the flag is a local file beside
    the run receipts, it is visible in the evidence, and removing it puts the
    exhaustive walk back without a code change. A narrowed path that is not yet
    proven must never be the one the watch uses by default.
    """
    root = Path(appdata or os.environ["LOCALAPPDATA"]) / "harness-freebuff-runner"
    return (root / NARROW_FLAG).is_file()


def project_anchor(surface, step, frame, key):
    """Locate one dialog control by its exact label, or refuse by name."""
    label, region = PROJECT_DIALOG[key]
    try:
        return surface.locate_exact_text(step, frame, label, region), region
    except RuntimeError:
        raise RuntimeError(
            f"project-creation adapter: the {key} control {label!r} was not visible; "
            "not clicking a guess") from None


PROJECT_NAME_FIELD = (648, 545, 1160, 605)


def project_name_reads(reading, name):
    """Does the field hold this name, allowing the slips the OCR engine makes?

    Measured 2026-11-24 on the launch cold run: the field held
    'robby-battery-helper' and the reader returned 'robby-battery-helped'. The
    adapter had also been reading a region wider than the field, so it compared
    the whole dialog and the surrounding chat against the name. The read is now
    the field's own box, and one misread glyph is tolerated the way every other
    exact read in this driver tolerates it; a different name is still refused.
    """
    got = "".join(str(reading).casefold().split())
    want = "".join(str(name).casefold().split())
    if not want or not got:
        return False
    return got == want or SequenceMatcher(None, want, got).ratio() >= 0.9


def project_dialog_anchors(surface, key, *, attempts=6, delay=0.7):
    """Read the opened dialog until its controls exist, or refuse by name.

    Measured 2026-11-24 on the launch cold run: the adapter captured once, one
    second after clicking New project, and refused with "the name control 'Project
    name' was not visible" while the dialog was still animating in. The same frame
    one settle later resolves every anchor, so a single fixed sleep is the defect,
    not the dialog. The read is retried inside a bounded window and the measured
    Create button (y 698 in the live dialog) is inside its region.
    """
    last = None
    for attempt in range(1, attempts + 1):
        frame = surface.frame(f"project-dialog-open-{attempt}")
        try:
            name_point, name_region = project_anchor(surface, f"project-name-ocr-{attempt}",
                                                     frame, "name")
            create_point, create_region = project_anchor(
                surface, f"project-create-ocr-{attempt}", frame, "create")
        except RuntimeError as error:
            last = error
            if attempt < attempts:
                time.sleep(delay)
            continue
        if attempt > 1:
            surface.audit.append("verification", step_id="project-dialog-settled",
                                 attempt=attempt)
        return frame, name_point, name_region, create_point, create_region
    raise last if last is not None else RuntimeError(
        "project-creation adapter: the dialog could not be read")


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
    frame, name_point, name_region, create_point, create_region = project_dialog_anchors(
        surface, "project-dialog")
    surface.yes("project-dialog-confirm", frame,
                "Does this show a project name field and a create button?",
                region=(480, 240, 1520, 1120))
    surface.act("project-name-focus", CLICK,
                {"control": "Project name field", "point": name_point,
                 "size": list(frame.size)})
    surface.type_literal(name)
    frame = surface.frame("project-name-readback")
    reading = " ".join(surface.read_lines("project-name-read", frame, PROJECT_NAME_FIELD))
    if not project_name_reads(reading, name):
        raise RuntimeError(
            f"project-creation adapter: the name field reads {reading!r}, not {name!r}")
    surface.act("project-create", CLICK,
                {"control": "Create project", "point": create_point,
                 "size": list(frame.size)})
    frame, rows = surface.settled_roster("project-created", SIDEBAR, attempts=6)
    for row in rows:
        # Measured 2026-11-24: a created project's row reads 'B robby-battery-helper',
        # where the leading glyph is the folder icon the OCR cannot resolve. An exact
        # equality over the whole row therefore loses the project it just created; the
        # title rule this codebase already uses for session rows reads it correctly.
        if Dispatch.exact_session_title(row["text"], name):
            surface.audit.append("verification", step_id="project-created",
                                 row=row["text"], name=name)
            return row
    raise RuntimeError(
        f"project-creation adapter: no session row reads {name!r} after {create_region}")


LAUNCH_PLACEHOLDER = "Ask Freebuff... Use / for commands, @ for files"
LAUNCH_MARKER = "harness-freebuff-launch-{name}.json"


def launch_after_project(surface, row, name, mission, carrier, *, observation=25):
    """Launch one session carrying a mission of record, or refuse by name.

    Composed from the pieces that are already proven: the caller hands the row of
    the project it owns, the composer is typed into only after its own empty
    placeholder is read by exact OCR, the carrier line is read back off the field
    before anything is sent, and the send is one click on the arrow whose outline
    is measured in the same frame. A one-send marker keyed by the project name
    bounds the launch even though a brand-new chat has no session UUID yet.

    Split from the creation step so an interrupted launch resumes on the project it
    already created instead of making a second one.
    """
    time.sleep(1.5)
    frame = surface.settle_view("launch-after-create")
    try:
        point = surface.locate_exact_text("launch-composer-empty", frame, LAUNCH_PLACEHOLDER,
                                          (640, 925, 1540, 1060))
    except RuntimeError:
        # The new project may open its chat only when its row is opened.
        surface.act("launch-open-project", CLICK,
                    {"control": f"{name} project row",
                     "point": [int(row["x"]) + 20, int(row["y"]) + 8],
                     "size": list(frame.size)})
        time.sleep(1.5)
        frame = surface.settle_view("launch-after-open")
        point = surface.locate_exact_text("launch-composer-empty", frame, LAUNCH_PLACEHOLDER,
                                          (640, 925, 1540, 1060))
    surface.yes("launch-composer-confirm", frame,
                "Is this an empty composer showing the Ask Freebuff placeholder?",
                region=(640, 925, 1540, 1060))
    surface.text = mission
    surface.act("launch-focus-composer", CLICK,
                {"control": f"{name} composer", "point": point, "size": list(frame.size)})
    surface.act("launch-type-mission", TYPE, {"text": mission})
    time.sleep(1.5)
    frame = surface.frame("launch-mission-typed")
    reading = surface._norm(" ".join(surface.read_lines(
        "launch-carrier-readback", frame, (640, 900, 1540, 1080))))
    if surface._norm(carrier) not in reading:
        raise RuntimeError(
            f"launch: the carrier line {carrier!r} was not read back off the composer")
    surface.audit.append("verification", step_id="launch-carrier", carrier=carrier)
    region = SEND_CONTROL
    surface.yes("launch-send-arrow", frame,
                "Does this image show a white button containing a black upward arrow?",
                region=region)
    left, top, _, _ = region
    box = frame.crop(region).convert("L").point(
        lambda level: 255 if level >= 205 else 0).getbbox()
    if box is None or not (26 <= box[2] - box[0] <= 47 and 26 <= box[3] - box[1] <= 47):
        raise RuntimeError("launch: the send arrow outline was not located")
    send_point = [left + (box[0] + box[2]) // 2, top + (box[1] + box[3]) // 2]
    marker = surface.output / LAUNCH_MARKER.format(name=name)
    if marker.exists():
        raise RuntimeError("launch: the one-send marker already exists; inspect the prior outcome")
    with marker.open("x", encoding="utf-8") as handle:
        json.dump({"project": name, "carrier": carrier, "step": "launch-send"}, handle)
    surface.act("launch-send-once", SEND,
                {"thread": name, "text": mission, "control": f"{name} Send (up arrow)",
                 "point": send_point, "size": list(frame.size)})
    for attempt in range(1, 4):
        time.sleep(observation // 3)
        current = surface.frame(f"launch-response-{attempt}")
        if surface.stop_visible(current):
            surface.audit.append("verification", step_id="launch-running", stop_cue=True,
                                 observation_seconds=observation // 3 * attempt)
            return attempt
    raise RuntimeError("launch: the mission was submitted once but no running Stop cue appeared")


def launch_project_session(surface, name, mission, carrier, *, observation=25):
    """Create the owner-ordered project, then launch one session carrying it."""
    frame, rows = surface.settled_roster("launch-roster", SIDEBAR, attempts=5)
    if any(surface._norm(candidate["text"]) == surface._norm(name) for candidate in rows):
        raise RuntimeError(
            f"launch: the roster already holds {name!r}; launching would duplicate a session")
    row = create_project(surface, name)
    surface.audit.append("verification", step_id="launch-project-created",
                         row=row["text"], name=name)
    return launch_after_project(surface, row, name, mission, carrier, observation=observation)


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


# A1 composer gate: what the composer's own text IS, before any model opinion.
# The owner's ruling of 2026-11-26 (#684 c.7208601549) followed four parked
# Lane 1 restarts in one afternoon: the composer read
# 'typeamessagesentbeforethequeue' - the platform's own control labels
# ("type a message", "sent", "before the queue") glued together by the
# renderer, with no word boundary. That is not a draft and the lane must not
# stop on it. Parking stays reserved for text that reads as a person's writing,
# and even then the text is relayed verbatim before anything touches it
# (#684 c.7125400686, bounded by the ruling).
UI_LABEL_FRAGMENTS = (
    "typeamessage", "typeyourmessage", "askfreebuff", "useforcommands",
    "forfiles", "beforethequeue", "addedtothequeue", "sendamessage",
    "searchchats",
)
MIN_RUN_TOGETHER = 18


def composer_text_verdict(reading):
    """Classify the composer's own reading: 'empty', 'machine' or 'draft'.

    'machine' is the only verdict that authorizes a clear, and it is earned
    deterministically - a platform label joined into one unbroken alphabetic run
    (the measured instance is 30 characters with no space), or a known control
    label with its spaces lost. Everything else is treated as 'draft': text that
    could be the owner's own writing is never typed over, and is relayed
    verbatim and parked for the oversight's ruling instead.
    """
    text = " ".join(str(reading or "").split())
    folded = text.casefold()
    if not folded:
        return "empty"
    squashed = "".join(folded.split())
    machine = any(fragment in squashed for fragment in UI_LABEL_FRAGMENTS)
    if not machine:
        machine = (" " not in folded and len(squashed) >= MIN_RUN_TOGETHER
                   and squashed.isalpha())
    return "machine" if machine else "draft"


# A4: a restart never lands a lane on the free tier. The session's own model
# chip is the primary source; the free pool rate-limits (2026-09-21 probe: a
# 429 on the free gemma rung) and the model policy of record is the cheap PAID
# rung, so an explicit free marker is the one reading that refuses a send.
FREE_TIER = re.compile(r"\bfree\b|:free\b", re.I)


TIER_WORD = re.compile(r"[a-z0-9][a-z0-9.+-]*")


def tier_verdict(reading):
    """Classify the session's model chip: 'free', 'paid' or 'unknown'.

    An explicit free marker disqualifies. A reading with no recognizable word is
    'unknown' - OCR noise and a half-rendered chip are not a paid tier - and the
    gate refuses an unknown reading rather than assuming the seat of record.
    """
    text = " ".join(str(reading or "").split()).casefold()
    if not text:
        return "unknown"
    if FREE_TIER.search(text):
        return "free"
    if not any(len(token) >= 3 for token in TIER_WORD.findall(text)):
        return "unknown"
    return "paid"


CHIP_CALIBRATION = Path.home() / ".harness" / "driver-watch" / "model-chip.json"


def _calibrated_chip_box():
    """The install's own chip calibration, if one has been recorded.

    The env var is an override; this file is what survives a scheduled task.
    The watch runs from Task Scheduler, so a variable set during a session does
    not reliably reach the task's next tick, and an uncalibrated install refuses
    every restart by design. A file the child reads at prepare time is seen by
    the very next tick, which is what makes calibration an act rather than a
    reboot.
    """
    try:
        raw = CHIP_CALIBRATION.read_text(encoding="utf-8")
    except OSError:
        return ""
    try:
        data = json.loads(raw)
    except ValueError:
        return ""
    value = data.get("region") if isinstance(data, dict) else data
    if isinstance(value, (list, tuple)):
        return ",".join(str(int(part)) for part in value)
    return str(value or "").strip()


def model_chip_region(default=None):
    """The model chip's box: ``HARNESS_FREEBUFF_MODEL_CHIP``, else the file.

    The chip's position is an install fact, not something code may guess: a
    region read off the wrong place would refuse a paid lane or clear a free
    one, and both failures are silent. Until it is calibrated the gate refuses
    the restart as tier-unverified.
    """
    raw = os.environ.get("HARNESS_FREEBUFF_MODEL_CHIP", "").strip()
    if not raw:
        raw = _calibrated_chip_box()
    if not raw:
        return default
    try:
        left, top, right, bottom = (int(part) for part in raw.split(","))
    except ValueError:
        raise RuntimeError(
            "HARNESS_FREEBUFF_MODEL_CHIP must be 'left,top,right,bottom' integers") from None
    if not (0 <= left < right and 0 <= top < bottom):
        raise RuntimeError("HARNESS_FREEBUFF_MODEL_CHIP names an empty box")
    return (left, top, right, bottom)


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


class ForegroundLost(RuntimeError):
    """The desktop moved off FreeBuff, so no input in this run landed anywhere.

    Distinct from every other runtime refusal on purpose: a census that cannot
    scroll is not evidence about which sessions the list holds, and reporting it
    as one sends the next reader to the wrong place (measured 2026-11-24, Kalshi
    7127830177, held by a 'Windows Security' prompt on pid 12304).
    """


def _send_arrow_bbox(frame, region=SEND_CONTROL):
    """Locate the Send control's up-arrow in ``region``, or None.

    Two themes, two readings. The dark theme paints a white control on a dark
    page, so the control itself is the bright blob. The light theme paints a white
    control on a white page, where only the arrow has contrast: measured
    2026-11-27 on dyn-7229334626, the whole 55x57 region read 249 except the glyph,
    so the bright-blob rule returned a blob the size of the region, the locate
    failed, and the send phase parked on a 0.3 model guess. The dark-glyph pass is
    the same measurement on the other side of the contrast, and the composer's own
    bottom border is cropped out first so a line cannot pass for an arrow.
    """
    left, top, _, _ = region
    try:
        crop = frame.crop(region).convert("L")
    except (AttributeError, TypeError, ValueError):
        return None
    outline = crop.point(lambda level: 255 if level >= 205 else 0).getbbox()
    if (isinstance(outline, tuple) and len(outline) == 4
            and all(isinstance(v, (int, float)) for v in outline)):
        if 26 <= outline[2] - outline[0] <= 47 and 26 <= outline[3] - outline[1] <= 47:
            return [int(left + (outline[0] + outline[2]) // 2),
                    int(top + (outline[1] + outline[3]) // 2)]
    # Only a page as bright as the control itself is read this way: that is the
    # light theme's signature, and it keeps the dark-glyph pass from ever looking
    # for an arrow on a surface that is not one.
    if not (isinstance(outline, tuple) and len(outline) == 4
            and outline[2] - outline[0] >= crop.width - 2
            and outline[3] - outline[1] >= crop.height - 2):
        return None
    # A rule of the composer can run across this region; a line is wide and one
    # row tall or two, while the glyph is neither. Rows that are mostly dark are
    # dropped before the glyph is measured, so the point lands on the arrow.
    mask = crop.crop((0, 0, crop.width, max(1, int(crop.height * 0.6))))
    mask = mask.point(lambda level: 255 if level <= 120 else 0)
    keep = mask.copy()
    pixels = mask.load()
    kept = keep.load()
    wide = max(1, int(mask.width * 0.6))
    for y in range(mask.height):
        dark = sum(1 for x in range(mask.width) if pixels[x, y])
        if dark >= wide:
            for x in range(mask.width):
                kept[x, y] = 0
    glyph = keep.getbbox()
    if (isinstance(glyph, tuple) and len(glyph) == 4
            and all(isinstance(v, (int, float)) for v in glyph)):
        width, height = glyph[2] - glyph[0], glyph[3] - glyph[1]
        if 6 <= width <= 45 and 4 <= height <= 40:
            return [int(left + (glyph[0] + glyph[2]) // 2),
                    int(top + (glyph[1] + glyph[3]) // 2)]
    return None


def has_send_arrow_outline(frame, region=SEND_CONTROL):
    """True when the bright white circular Send button (luma >= 205) is visible."""
    return _send_arrow_bbox(frame, region=region) is not None


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
        self.driver.register_executor(CLEAR.name, self.clear_composer)

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
        if self.standing or self.text == DISK_POINTER or (self.scoped_input and self.thread == DISK_THREAD):
            for character in self.text:
                if not hit or self.user.GetAncestor(hit, 2) != self.require_foreground():
                    raise RuntimeError("the verified composer renderer is no longer available")
                if not self.user.PostMessageW(hit, 0x0102, ord(character), 1):
                    raise RuntimeError("the verified FreeBuff composer refused a character")
        else:
            # One call for the whole approved text: osal.type_text() is what
            # turns a newline into a real Return press, and typing character by
            # character would send U+000A as text no editor breaks on. The
            # launch mission of record depends on exactly that.
            if not hit or self.user.GetAncestor(hit, 2) != self.require_foreground():
                raise RuntimeError("the verified composer renderer is no longer available")
            keyboard.type_text(self.text)

    def send(self, action, params):
        if params["thread"] != self.thread or params["text"] != self.text:
            raise RuntimeError("the thread or text differs from the approved continuation")
        if self.standing:
            if self.thread in {THREAD, VISION_THREAD}:
                self.verify_session_identity()
            else:
                self.verify_active_session()
            fresh = self.frame("send-executor-fresh")
            if (not composer_unchanged(self.send_composer, fresh.crop(COMPOSER))
                    or self.turn_running(fresh)):
                raise RuntimeError("the standing composer changed after approval")
        if self.send_deadline is None or time.monotonic() > self.send_deadline:
            # The executor's own identity pass can outlive the window the caller
            # armed (measured 2026-11-27, dyn-7229793962: prepared, staged, exact
            # read-back, identity, arrow measured, then "the verified send window
            # expired before input" twice over). A fresh, unchanged composer is a
            # stronger statement than elapsed time, so it re-anchors the window
            # here too; anything else still refuses by name.
            recheck = self.frame("send-window-recheck")
            if (self.send_composer is None
                    or not composer_unchanged(self.send_composer, recheck.crop(COMPOSER))):
                raise RuntimeError("the verified send window expired before input")
            self.audit.append("escalation", step_id="send-window-reanchor",
                              reason="the executor's identity pass outlasted the window; the composer re-read unchanged")
            self.send_deadline = time.monotonic() + 60
        self.click(action, params)

    def query(self, action, params):
        if (params["thread"] != self.thread or params["text"] != self.session_name
                or params["control"] != "Search chats field"):
            raise RuntimeError("search parameters differ from the approved session")
        renderer = self.search_renderer
        for character in self.session_name:
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
    def _row_norm_forms(cls, text):
        forms = {cls._norm(text)}
        head, _, tail = text.strip().partition(" ")
        if len(head) <= 3 and tail:
            forms.add(cls._norm(tail))
        return {item for item in forms if item}

    @property
    def session_name(self):
        """The name the app prints for this session: its title, or our label.

        A property rather than a stored field so a lane whose title differs is
        found by every path that matches or types a name, including the harness
        doubles that set only ``thread`` and ``label``.
        """
        return SESSION_TITLES.get(getattr(self, "thread", None), self.label)

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
        candidates = cls._row_norm_forms(text)
        _, _, tail = text.strip().partition(" ")
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
            lane_row = self._lane_row_in(rows, label)
            found = [lane_row] if lane_row is not None else []
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

    def selection_band(self, gray, x, y, *, above=40, below=30, run=8, floor=38, contrast=12):
        """Does a selection band cover this row, read from the band's own fill?

        Measured 2026-11-24 on claim 7124952240: the app paints a uniform
        brighter fill (47 against a 24 background) across the selected row, and
        the old probe compared one pixel eight rows below the OCR baseline with
        one twenty-six above it. The band sat a few pixels off that assumption,
        so a visibly selected Lane 1 (archived frame, 47/47/47 across the band)
        read as no selection at all and prepare parked on identity.

        The band is read where only the fill exists - the row's left padding,
        left of the first glyph - as a vertical run of bright pixels. Glyph
        strokes cannot produce the run, so an unselected row stays dark there.
        """
        if x < 0 or x >= gray.width:
            return False
        column = [(row, gray.getpixel((x, row))) for row in range(max(0, y - above),
                                                                 min(gray.height, y + below))]
        if not column:
            return None
        values = [value for _, value in column]
        if max(values) < floor or max(values) - min(values) < contrast:
            return None
        longest = current = 0
        start = best_start = None
        for row, value in column:
            if value >= floor:
                current += 1
                if start is None:
                    start = row
                if current > longest:
                    longest, best_start = current, start
            else:
                current, start = 0, None
        if longest < run or best_start is None:
            return None
        return best_start + longest / 2

    def highlighted_row(self, frame, rows):
        """The row whose own text the selection band is centred on.

        The band's centre is measured, not assumed: OCR row geometry can be a
        text top, a baseline or a centre, and the earlier fixed-offset probe
        read a visibly selected row as unselected for exactly that reason. Two of
        three sample columns must agree, and the band has to sit within about
        half a row of the row's own baseline.
        """
        gray = frame.convert("L")
        best = None
        for row in rows:
            x0, y0 = round(row["x"]), round(row["y"])
            centres = [centre for centre in
                       (self.selection_band(gray, x0 - gap, y0) for gap in (6, 10, 14))
                       if centre is not None]
            close = [centre for centre in centres if abs(centre - y0) <= 18]
            if len(close) < 2:
                continue
            distance = min(abs(centre - y0) for centre in close)
            if best is None or distance < best[0]:
                best = (distance, row)
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
                      if self.exact_session_title(candidate["text"], self.session_name)
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
            if row and self.row_matches(row["text"], self.session_name):
                project = self.project_of_row(rows, row)
                # The lane lives under the cloud/local variant on this box
                # (measured 2026-11-27, dyn-7226574169: the selected row read
                # "Ra Lane 2" under "harness CLOUD"). Demanding the exact
                # heading here rejected the lane that was already open, so the
                # query phase re-walked the list and refused a live lane. Same
                # binding as the census: exact heading, then the project family.
                if project == self.project or self._same_project_family(project, self.project):
                    self.audit.append("verification", step_id="selected-row", row=row["text"],
                                      project=project)
                    return True
                if project is None and self._no_rival_for_name(rows, row):
                    # The heading can sit outside the frame while the selected
                    # row is visible (measured 2026-11-27, dyn-7226817360: the
                    # probe read "Ra Lane 2" with no heading, so no project could
                    # be compared and the open lane was refused twice). Without a
                    # heading the row's own name decides, and only when nothing
                    # else in the frame carries it.
                    self.audit.append("verification", step_id="selected-row-unbound",
                                      row=row["text"],
                                      reason="heading outside the frame; no rival row carries this name")
                    return True
                # A highlighted same-titled row in another project is the
                # false-green defect, not this lane.
                self.audit.append("escalation", step_id="selected-row-project", row=row["text"],
                                  project=project, expected=self.project)
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.8)

    def _no_rival_for_name(self, rows, row):
        """Is the selected row the only row in this frame carrying its name?"""
        here = (row.get("x"), row.get("y"))
        for candidate in rows:
            if (candidate.get("x"), candidate.get("y")) == here:
                continue
            if self.row_matches(candidate["text"], self.session_name):
                return False
        return True

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
        """A scroll step; a compositor change between capture and input is retried.

        A lost foreground is NOT a scroll that failed: it means no input landed at
        all, so every later census reads the same viewport. Measured 2026-11-24 on
        Kalshi (7127830177): every scroll in the run returned "FreeBuff is not the
        foreground window; held by hwnd 1049510 pid 12304 title 'Windows Security'",
        the walk then found identical rosters page after page, and it reported "the
        project session list does not hold 'Kalshi Paper Burndown'" - a misleading
        cause that sends the next reader to the lane instead of to the desktop.
        """
        try:
            self.act(step, SCROLL, {"point": point, "size": list(frame.size), "delta": delta})
            return True
        except RuntimeError as error:
            self.audit.append("escalation", step_id=step, reason=str(error))
            if "not the foreground window" in str(error):
                raise ForegroundLost(str(error)) from error
            return False

    def scroll_sidebar_to_top(self, steps=25):
        """Reach the top of the project list, proven by two censuses that agree.

        Settling is about where the rows ARE, not how the OCR reads them: on a
        stationary list the engine alternates icons and truncations, so text
        equality can never settle. Measured 2026-11-28 on dyn-7230559860, this
        loop spent an entire 480 s search budget scrolling a list that had
        already stopped moving, and the claim parked without searching at all.
        The roster settle already compares geometry (b4f2e40); this does too.
        """
        previous = None
        previous_identity = None
        frame = self.frame("sidebar-top-0")
        for attempt in range(1, steps + 1):
            rows = self.read_roster(f"sidebar-top-{attempt}", frame, SIDEBAR)
            current = tuple(round(row["y"] / 2) for row in rows)
            # In reading order, not as a sorted set: one row's text slip
            # ("B Harness" re-read as "Harness") otherwise reorders the set, and
            # two censuses of one still list never compare equal.
            identity = tuple(self._norm(row["text"]) for row in rows)
            if (rows and previous is not None and same_rows(previous, current)
                    and previous_identity is not None
                    and self.identities_compatible(previous_identity, identity)):
                self.audit.append("verification", step_id="sidebar-top-settled",
                                  rows=len(rows), censuses=attempt, settled_by="geometry")
                return frame
            previous = current
            previous_identity = identity
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
            matches = [row for row in rows if self.row_matches(row["text"], self.session_name)]
            unrelated = [row["text"] for row in matches
                         if self.project_of_row(rows, row) != self.project]
            if unrelated:
                self.audit.append("escalation", step_id=f"session-list-foreign-{page}",
                                  rows=unrelated[:6], expected=self.project)
            scoped, heading = self.session_candidates(rows, self.session_name, self.project)
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
                     if self.exact_session_title(row["text"], self.session_name)]
            if len(exact) == 1:
                # Click the scoped row itself: the title-only matcher would see
                # the same-titled row in the other project and refuse.
                self.click_exact_row(f"session-list-pick-{page}", frame, exact[0])
                self.audit.append("verification", step_id=f"session-list-pick-{page}",
                                  row=exact[0]["text"], project=self.project)
                return True
            for row in (() if exact else scoped):
                forms = self._row_norm_forms(row["text"])
                if any(forms & self._row_norm_forms(item["text"]) for item in rivals):
                    continue
                rivals.append(row)
            if len(scoped) > 1 and not exact:
                self.audit.append("escalation", step_id=f"session-list-ambiguous-{page}",
                                  rows=[row["text"] for row in scoped])
            # Several sections can be collapsed at once, and a single-row click
            # cannot choose between them (measured: 7127392246 aborted the whole
            # walk here on page one). Expand what is visible, then keep walking.
            frame, rows, expanded_sections = self.expand_sections(
                page, frame, rows, "session-list")
            if expanded_sections:
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

    def expand_sections(self, page, frame, rows, step, limit=4):
        """Expand every visible section control, the target's own section first.

        Measured 2026-11-24 on dispatch 7127392246 (Kalshi Paper Burndown): the
        sidebar carries one "Show more" per project section, so the first page
        held two, the single-row click refused with "'Show more' matched 2 settled
        rows", and that refusal aborted the ENTIRE session-list walk on page one -
        above the Kalshi-Trader heading the lane lives under. A later page in the
        same run censused "B Kalshi-Trader, Kalshi Paper Burndown" without ever
        getting there through this walk.

        So: every control is expanded in turn (the target project's section first
        when its heading is on the page), each click is coordinate-bound to the row
        already censused, and a control that cannot be clicked is skipped rather
        than ending the walk. Expansion is visibility only - the pick still has to
        prove the lane afterwards.
        """
        controls = [row for row in rows
                    if row["text"].strip() in {"Show more", "More chats"}]
        if not controls:
            return frame, rows, 0
        ordered = sorted(controls,
                         key=lambda row: self.project_of_row(rows, row) != self.project)
        expanded = 0
        for index, control in enumerate(ordered[:limit], start=1):
            try:
                self.click_exact_row(f"{step}-expand-{page}-{index}", frame, control)
            except RuntimeError as error:
                self.audit.append("escalation", step_id=f"{step}-expand-{page}-{index}",
                                  reason=str(error))
                continue
            expanded += 1
            time.sleep(1.0)
            frame = self.frame(f"{step}-{page}-expanded-{index}")
            rows = self.read_roster(f"{step}-{page}-expanded-{index}", frame, SIDEBAR)
        if expanded:
            self.audit.append("verification", step_id=f"{step}-expanded-{page}",
                              controls=len(controls), expanded=expanded)
        return frame, rows, expanded

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

    def query_search_field(self, frame, attempts=2):
        """Focus the search field, type the label, and prove the text landed.

        Measured on claim 7123056197: the click missed the field, the keystrokes
        went nowhere, and the results panel still showed four rows for a
        different query. A stale panel read as a census is worse than a refusal,
        so the field's own text is the proof - type, read it back, and refuse by
        name rather than narrow from a panel the query never reached. A second
        attempt retypes only into an empty field: text this lane did not put
        there is left alone, never typed over.
        """
        wanted = self._norm(self.session_name)
        for attempt in range(1, attempts + 1):
            try:
                point = self.locate_exact_text(f"narrow-search-field-{attempt}", frame,
                                               "Search chats", SEARCH_PLACEHOLDER)
            except RuntimeError:
                # The placeholder can be hidden by a caret; the field's own row
                # is the anchor, and the readback below is what proves focus.
                left, top, _right, bottom = SEARCH_PLACEHOLDER
                point = [left + 40, (top + bottom) // 2]
                self.audit.append("verification", step_id=f"narrow-anchor-{attempt}",
                                  source="field-row anchor, proven by readback")
            self.act(f"narrow-focus-{attempt}", CLICK,
                     {"control": "Search chats field", "point": point,
                      "size": list(frame.size)})
            self.act(f"narrow-query-{attempt}", QUERY,
                     {"thread": self.thread, "text": self.session_name,
                      "control": "Search chats field"})
            time.sleep(1.3)
            frame = self.frame(f"narrow-readback-{attempt}")
            try:
                reading = " ".join(self.read_lines(f"narrow-field-verify-{attempt}",
                                                   frame, SEARCH_PLACEHOLDER))
            except RuntimeError:
                reading = ""
            seen = self._norm(reading)
            if wanted and (
                    wanted in seen
                    or SequenceMatcher(None, wanted, seen).ratio() >= 0.9
                    or (len(seen) >= 12 and len(wanted) > len(seen)
                        and SequenceMatcher(None, wanted[:len(seen)], seen).ratio() >= 0.88)):
                # A one-glyph OCR slip is not foreign text: measured 2026-11-24, the
                # field read 'Kalshi Paper Burndow' for the query this run typed, and
                # the exact test then parked the lane as if someone else had written
                # in the box. The readback keeps its job - it proves the query landed
                # and that this run did not type over another lane's text - while
                # tolerating the same single-glyph error every other exact read here
                # tolerates.
                self.audit.append("verification", step_id="narrow-query-landed",
                                  attempt=attempt, reading=reading[:60],
                                  exact=wanted in seen)
                return frame
            self.audit.append("escalation", step_id=f"narrow-query-{attempt}",
                              reason="the field did not show the query after typing",
                              reading=reading[:60])
            if self._norm(reading):
                raise RuntimeError(
                    "the search field holds text this query did not write "
                    f"({reading[:60]!r}); not typing over it")
            frame = self.frame(f"narrow-retry-{attempt}")
        raise RuntimeError(
            f"the search field never showed the query after {attempts} attempts; "
            "refusing to narrow from a stale results panel")

    def resolve_unique(self, found):
        """Exactly one candidate row, or a named refusal - never a guess."""
        if len(found) > 1:
            # Chats that merely OPEN with this name are rivals, not copies of it
            # (measured: five chats open with "SCMessenger", one IS SCMessenger).
            exact = [(page, name) for page, name in found
                     if name.strip() == self.session_name.strip()
                     or self._norm(name.partition(" ")[2] or "") == self._norm(self.session_name)]
            if len(exact) == 1:
                self.audit.append("verification", step_id="prefix-exact-wins",
                                  row=exact[0][1], rivals=len(found))
                found = exact
        if len(found) != 1:
            self.audit.append("escalation", step_id="prefix-census", label=self.label,
                              candidates=[name for _, name in found][:8], count=len(found),
                              reason="no unique session row for this lane; not guessing")
            return None
        page, name = found[0]
        self.audit.append("verification", step_id="prefix-unique", label=self.label,
                          row=name, page=page)
        return page, name

    def exact_label_rows(self, rows, page, found):
        """Candidates in a search-results panel: rows whose text IS the label.

        No project heading exists in the panel, so a prefix match is only a
        rival chat that opens with the same words; placeholders are not rows.
        Ambiguity is still refused downstream by ``resolve_unique``.
        """
        want = self._norm(self.session_name)
        if not want:
            return found
        for row in rows:
            text = str(row.get("text", "")).strip()
            if not text:
                continue
            seen = self._norm(text).rstrip("-")
            if seen != want and not (len(seen) >= 18 and want.startswith(seen)):
                # The sidebar clips long titles ("Carrier Census Verifica-",
                # measured 2026-11-27). Only a SHORTER form of this lane's own
                # title is that clipping; a longer title that merely opens with
                # the same words is a different chat and is refused here, so
                # resolve_unique never sees it as a candidate.
                continue
            # Every exact row is counted: two rows with one name are two
            # sessions (the app keeps a CLOUD and a LOCAL of one lane), and
            # collapsing them would be the guess this proof exists to prevent.
            found.append((page, row["text"]))
        self.audit.append("verification", step_id="narrow-exact-rows",
                          label=self.label, rows=[r.get("text", "") for r in rows][:8],
                          exact=len(found))
        return found

    @staticmethod
    def _same_project_family(heading, project):
        """The app keeps a CLOUD and a LOCAL of one project under two headings.

        Measured 2026-11-27 (standing-20261127-coldlane2c): the roster held the
        row "Lane 2" under "harness CLOUD" while the lane is bound to "Harness",
        so the strict heading check dropped the only row that is the lane.
        """
        if not heading or not project:
            return False
        def norm(value):
            return "".join(character for character in str(value).casefold()
                           if character.isalnum())

        left, right = norm(heading), norm(project)
        if not left or not right:
            return False
        return left == right or left == right + "cloud" or right == left + "cloud"

    def _lane_row_in(self, rows, name):
        """The row that is this lane in one settled frame, by the census's binding.

        The pick leg used to re-derive what the census had already proved, with a
        stricter rule than the census used: it demanded an exact project heading
        even when the census had accepted the cloud/local variant, and it dropped
        the row outright when the heading had scrolled out of the frame. Measured
        2026-11-27 (standing-20261127-coldlane2e): the census resolved "Lane 2"
        under "harness CLOUD" at page 8 and the pick then lost it on every page it
        re-walked, which is how a located lane became a not-found verdict.

        The binding is: an exact heading outranks the variant, the variant counts
        only when nothing exact matched, a heading outside the frame leaves the
        exact text itself, and two rows for one name stay unresolved.
        """
        wanted = self._norm(name)
        exact, family, unbound = [], [], []
        for row in rows:
            if self._norm(row["text"]) != wanted:
                continue
            heading = self.project_of_row(rows, row)
            if heading is None:
                unbound.append(row)
            elif heading == self.project:
                exact.append(row)
            elif self._same_project_family(heading, self.project):
                family.append(row)
        for bucket in (exact, family, unbound):
            if bucket:
                return bucket[0] if len(bucket) == 1 else None
        return None

    def _remember_located(self, frame, rows, texts):
        """Keep the census frame and row that resolved a lane, for the pick.

        The pick must land on the row the census found. Remembering it is what
        makes that checkable instead of assumed: the audit records whether the
        clicked row sits where the census saw it.
        """
        memory = getattr(self, "_located_rows", None)
        if memory is None:
            memory = self._located_rows = {}
        wanted = {self._norm(text) for text in texts}
        for row in rows:
            if self._norm(row["text"]) in wanted:
                memory.setdefault(self._norm(row["text"]), (frame, row))

    def candidates_in(self, rows, page, found):
        """Collect the rows on one page that could be this lane, by identity.

        An exact heading outranks the cloud/local variant: when both surfaces
        carry one lane, the row under the bound heading is the one meant, and the
        other is left alone rather than turning a known lane into an ambiguity.
        """
        exact, family = [], []
        for row in rows:
            if not self._prefix_matches(row["text"], self.session_name):
                continue
            heading = self.project_of_row(rows, row)
            if heading == self.project:
                exact.append(row)
            elif self._same_project_family(heading, self.project):
                family.append(row)
        for row in (exact or family):
            if all(self._norm(row["text"]) != self._norm(name) for _, name in found):
                found.append((page, row["text"]))
        if not exact and family:
            self.audit.append("verification", step_id="project-family-heading",
                              project=self.project, rows=[r["text"] for r in family][:4])
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
        if self._norm(self.session_name) and self._norm(self.session_name) in self._norm(typed):
            self.audit.append("verification", step_id="narrow-reused-query",
                              reason="the search field already carries this label")
        else:
            frame = self.query_search_field(frame)
        # Measured on claim 7122996519: the field filters the dialog's result
        # panel, not the sidebar - reading the sidebar after typing returned 54
        # unfiltered rows. The results panel is the narrowed set.
        frame, rows = self.settled_roster("narrowed-results", SEARCH_RESULTS, attempts=3)
        self.audit.append("verification", step_id="narrowed-roster", label=self.label,
                          rows=len(rows), source="search-results panel")
        return frame, rows

    def _prefix_matches(self, text, label):
        """Is this row plausibly the configured lane, allowing app clipping?"""
        seen, wanted = self._norm(text), self._norm(label)
        return bool(seen and wanted and len(wanted) >= 4
                    and (seen.startswith(wanted) or wanted.startswith(seen)))

    def _census_prefix_walk(self, pages=8, found=None):
        """Scroll the whole session list and collect every candidate row.

        Returns (complete, found). ``complete`` is False only when a page could
        not be censused at all, and the caller then refuses rather than
        concluding anything from a partial list. A repeated page ends the walk
        because the list itself ended there.
        """
        found = [] if found is None else found
        frame = self.scroll_sidebar_to_top()
        seen = []
        for page in range(1, pages + 1):
            try:
                frame, rows = self.settled_roster(f"prefix-{page}", SIDEBAR, attempts=4)
            except RuntimeError as error:
                self.audit.append("escalation", step_id="prefix-walk", reason=str(error))
                return False, found
            frame, rows = self.expand_project(page, frame, rows, "prefix")
            texts = [self._norm(row["text"]) for row in rows]
            if texts in seen:
                break
            seen.append(texts)
            found = self.candidates_in(rows, page, found)
            self._remember_located(frame, rows, [name for _, name in found])
            if not self.scroll_by(f"prefix-scroll-{page}", frame, [196, 850], -400):
                frame = self.frame(f"prefix-{page}-recapture")
                continue
            time.sleep(0.9)
            frame = self.frame(f"prefix-{page}-after")
        return True, found

    def navigate_by_unique_prefix(self, pages=8, narrow=None):
        """Open the configured lane when exactly ONE session list row can be it.

        The configured names are ours and the app clips its own rows (measured:
        no row reads "Lane 2", one reads "Lane 2 Waist Composition Mission
        Brief"; none reads "BigEnergyCo", five read "BigEnergyCo ..."). One
        candidate is a pick; several are named and refused, never guessed.

        `narrow=True` restricts the candidate set with the app's search results
        panel first and runs the same exact-wins and one-candidate rules over
        what is left. Unproven live, so it is opt-in: `None` resolves through
        `narrowing_enabled()`, and with no flag the exhaustive walk runs.
        """
        if narrow is None:
            narrow = narrowing_enabled()
        found = []
        if narrow:
            def _close_narrow_modal():
                if hasattr(self, "window") and hasattr(self, "ensure_search_closed"):
                    self.ensure_search_closed(self.frame("narrow-cleanup"))

            try:
                frame, rows = self.narrow_session_list()
                # The results panel carries no project headings, so the
                # heading binding the sidebar walk relies on is unavailable
                # here; identity in the panel is the label itself. Measured
                # 2026-11-27 on standing-20261127-coldlane2b: the panel for
                # "Lane 2" held "Lane 2", "Lane 2 Waist Composition Mission
                # Brief" and "Loading...". The titled chat is a different
                # session and the placeholder is not a row, so an exact-only
                # read picks the lane instead of demanding a unique prefix.
                found = self.exact_label_rows(rows, 1, found)
                picked = self.resolve_unique(found)
                if picked is not None:
                    self.click_roster_row("narrow-pick", frame, rows, picked[1])
                    time.sleep(1.2)
                    return True
                self.audit.append("escalation", step_id="narrow-no-unique-row",
                                  label=self.label,
                                  reason="the narrowed panel held no unique row; a "
                                         "not-found verdict needs the full census")
            except RuntimeError as error:
                self.audit.append("escalation", step_id="narrow-walk", reason=str(error))
            _close_narrow_modal()
            # A3 (2026-11-27): a narrowed pass that cannot pick is not a census.
            # The field misses clipped rows and lookalike families, so the
            # exhaustive scroll walk runs before any not-found verdict is filed.
        ok, found = self._census_prefix_walk(pages, found)
        if not ok:
            return False
        picked = self.resolve_unique(found)
        if picked is None:
            return False
        page, name = picked
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
            row = self._lane_row_in(rows, name)
            if row is not None:
                located = getattr(self, "_located_rows", {}).get(self._norm(name))
                same = bool(located and [located[1].get("x"), located[1].get("y")]
                            == [row.get("x"), row.get("y")])
                self.audit.append("verification", step_id="prefix-pick-census-row",
                                  row=row["text"], census_page=page,
                                  same_position=same)
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
                if not self._prefix_matches(row["text"], self.session_name):
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

    def click_row_by_text(self, name, pages=20):
        """Re-open one row by its own text, wherever the list now has it."""
        frame = self.scroll_sidebar_to_top()
        target_forms = self._row_norm_forms(name)
        proj = getattr(self, "project", None)
        for page in range(1, pages + 1):
            try:
                frame, rows = self.settled_roster(f"pick-{page}", SIDEBAR, attempts=6)
            except RuntimeError as error:
                self.audit.append("escalation", step_id="pick-walk", reason=str(error))
                frame = self.frame(f"pick-{page}-single")
                rows = self.read_roster(f"pick-{page}-single", frame, SIDEBAR)
            row = next(
                (item for item in rows
                 if (self._row_norm_forms(item["text"]) & target_forms)
                 and (not proj or "y" not in item or self.project_of_row(rows, item) in {None, proj})),
                None,
            )
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
        wanted = self._norm(self.session_name)
        # Opening a candidate types nothing, so this stays available in the
        # select phase; the callers (search and select) are the ones that run
        # before a draft exists, and send never calls it.
        frame = self.ensure_search_closed(self.frame("identify-before-close"))
        frame = self.scroll_sidebar_to_top()
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
            # The app prints a long title clipped ("Carrier Census Verifica-"),
            # so an exact-title test can never accept it and this walk spent eight
            # pages clicking candidates whose routes the app does not expose at
            # all (measured 2026-11-28, dyn-7230748580). One row matching this
            # lane's title under this lane's own project heading is the same proof
            # the session-list pick uses; two or more is still a refusal.
            scoped_here = [row for row in rows
                           if self.project_of_row(rows, row) == self.project
                           and self.row_matches(row["text"], self.session_name)]
            unique_scoped = len(scoped_here) == 1
            for index, row in enumerate(rows):
                seen_text = self._norm(row["text"])
                # Rows are clipped by the app's own column width (measured:
                # "SCMessenger Audit L"), so a plain substring test misses the
                # very rows this path exists to find.
                if wanted and wanted not in seen_text and not self.row_matches(
                        row["text"], self.session_name):
                    continue
                if seen_text == wanted and self.project_of_row(rows, row) != self.project:
                    # A bare label is also how the app names project headings and
                    # duplicate sessions in OTHER projects; those are still never
                    # clicked blind. But when the exact title sits under this lane's
                    # own project heading it IS the lane: measured 2026-11-24, this
                    # walk censused "B Kalshi-Trader, Kalshi Paper Burndown" and then
                    # skipped its own exact row, so the fleet refused a lane that
                    # was on screen and scoped.
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
                if seen_text == wanted or (unique_scoped and row in scoped_here):
                    # The title, under this lane's own project heading, is the
                    # pick: measured 2026-11-24, this walk censused exactly that row
                    # for Kalshi and then read an empty route table, which on this
                    # app is the usual answer (dead accessibility tree). Title plus
                    # project scope is the same proof the session-list pick uses,
                    # and prepare still re-proves the lane before any input.
                    self.audit.append(
                        "verification",
                        step_id="identify-exact-scoped" if seen_text == wanted
                        else "identify-scoped-unique",
                        row=row["text"], project=self.project, page=page)
                    return True
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
        except ForegroundLost:
            # Do not convert a lost desktop into a statement about the lane.
            raise
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
        # Each claim starts from whatever the previous one left behind. Measured
        # 2026-11-27 (dyn-7227021046): the prior run had scrolled the list deep,
        # the Search icon could not be located, and the panel route that carried
        # the two claims before it was simply unavailable - the phase then spent
        # its budget on an eighteen-page walk. A proven top-of-list state costs
        # one scroll and makes the route choice deterministic.
        try:
            self.scroll_sidebar_to_top()
            self.frame("freebuff-search-reset")
        except RuntimeError as error:
            self.audit.append("escalation", step_id="search-state-reset", reason=str(error))
        # The panel is three steps and the roster walk is minutes; measured
        # 2026-11-27 (standing-20261127-coldlane2b) the walk spent the search
        # phase's whole budget on a lane whose sidebar row is clipped, while the
        # panel returned "Lane 2" itself. Cheap exact route first; the census
        # stays the fallback.
        if self.navigate_by_panel_exact():
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

    def navigate_by_panel_exact(self):
        """Pick the lane from the app's own search panel when it holds the row.

        Measured 2026-11-27: no sidebar row reads "Lane 2" (the app clips it to
        "Lane 2 Waist Composition Mission Brief"), so the sidebar's exact-row
        rule can never match this lane, and the search phase spent its entire
        budget walking to the same conclusion. The search panel returns "Lane 2"
        as a row of its own, so it is tried first, with the exact-only read, and
        the exhaustive walk remains the fallback it was written to be.
        """
        try:
            frame, rows = self.narrow_session_list()
            found = self.exact_label_rows(rows, 1, [])
            picked = self.resolve_unique(found)
            if picked is None:
                return False
            self.click_roster_row("panel-pick", frame, rows, picked[1])
            time.sleep(1.2)
            return True
        except RuntimeError as error:
            self.audit.append("escalation", step_id="panel-pick", reason=str(error))
            if hasattr(self, "ensure_search_closed"):
                self.ensure_search_closed(self.frame("panel-cleanup"))
            return False

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
            matches = [row for row in rows if self.row_matches(row["text"], self.session_name)]
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
        self.act("query-session", QUERY, {"thread": self.thread, "text": self.session_name,
                                          "control": "Search chats field"})
        time.sleep(1.4)
        self.frame("freebuff-search-results")

    def select_search_result(self):
        self.require_foreground()
        if self.selected_label_matches():
            self.audit.append("verification", step_id="select-skip",
                              reason="the target row is already the selected session")
            return
        if self.navigate_by_panel_exact():
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

    def verify_tier(self, frame):
        """Refuse a restart unless the session's own chip reads a paid tier (A4).

        Fail-closed by decision: an unreadable tier is not a reason to proceed.
        A restart that cannot prove where it lands is refused by name, because
        the failure it prevents - a lane burning its work on a free,
        rate-limited pool - is silent and expensive, while the refusal is loud,
        names the missing input, and leaves the run's own capture as the evidence
        that calibrates the chip box for the next attempt. Only a positive paid
        reading lets a restart through.
        """
        region = model_chip_region()
        if region is None:
            self.audit.append(
                "escalation", step_id="tier-unverified",
                reason="no model chip region is calibrated on this install "
                       "(HARNESS_FREEBUFF_MODEL_CHIP)")
            raise RuntimeError(
                "tier-unverified: the target session's tier cannot be read - no model chip "
                "region is calibrated (set HARNESS_FREEBUFF_MODEL_CHIP to "
                "'left,top,right,bottom'); refusing to restart a lane whose tier is "
                "unknown") from None
        try:
            lines = self.read_lines("tier-chip", frame, region)
        except RuntimeError as error:
            self.audit.append("escalation", step_id="tier-unverified", reason=str(error))
            raise RuntimeError(
                f"tier-unverified: the model chip could not be read ({error}); refusing to "
                "restart a lane whose tier is unknown") from None
        reading = " ".join(lines)
        verdict = tier_verdict(reading)
        self.audit.append("verification", step_id="tier-checked", verdict=verdict,
                          reading=reading[:80])
        if verdict == "free":
            raise RuntimeError(
                "tier-unverified: the target session reads as the free tier "
                f"({reading[:80]!r}); refusing to restart a lane onto it")
        if verdict != "paid":
            raise RuntimeError(
                "tier-unverified: the model chip read carries no recognizable tier "
                f"({reading[:80]!r}); refusing to restart a lane whose tier is unknown")
        return verdict

    def reveal_lane_row(self, pages=4, step="reveal-lane"):
        """Bring the lane's own row into view so its selection can be read.

        Measured on claim 7124457637: search, query and select all passed and the
        lane was open, then prepare refused with "no route and no highlighted
        sidebar row" because the walk had left the list scrolled away from the
        row. Visibility is not identity - this only scrolls the row into view,
        and verify_session_identity still requires the highlight or the route.
        Refuses by name when the row is not in the bounded reveal, never guesses.
        """
        frame = self.scroll_sidebar_to_top()
        for page in range(1, pages + 1):
            try:
                frame, rows = self.settled_roster(f"{step}-{page}", SIDEBAR, attempts=4)
            except RuntimeError as error:
                self.audit.append("escalation", step_id=f"{step}-{page}", reason=str(error))
                continue
            if (any(self.exact_session_title(row["text"], self.session_name) for row in rows)
                    or (self.thread != SCM_THREAD and any("y" in row for row in rows)
                        and bool(self.session_candidates(rows, self.label, self.project)[0]))):
                self.audit.append("verification", step_id=f"{step}-visible",
                                  page=page, label=self.label)
                return frame, rows
            if not self.scroll_by(f"{step}-scroll-{page}", frame, [196, 850], -400):
                break
            time.sleep(0.8)
            frame = self.frame(f"{step}-{page}-after")
        self.audit.append("escalation", step_id=step, label=self.label,
                          reason="the lane row was not visible in the bounded reveal")
        return frame, []

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
            derived_uuid = PINNED_UUIDS.get(self.thread) or lookup_local_session_uuid(self.thread)
            if self.selected_exact_session():
                self.audit.append("verification", step_id="active-session-id",
                                  route_fallback="exact-scoped-selection",
                                  thread=self.thread, project=self.project,
                                  pinned_uuid=derived_uuid)
                return
            if (getattr(self, "post_send", False)
                    and (getattr(self, "window", None) is not None
                         or "reveal_lane_row" in getattr(self, "__dict__", {}))):
                self.reveal_lane_row(step="post-send-reveal-lane")
                if self.selected_exact_session():
                    self.audit.append("verification", step_id="active-session-id",
                                      route_fallback="post-send-revealed-exact-selection",
                                      thread=self.thread, project=self.project,
                                      pinned_uuid=derived_uuid)
                    return
            if (getattr(self, "phase", None) != "send"
                    and getattr(self, "allow_navigation", False)
                    and (getattr(self, "window", None) is not None
                         or "navigate_by_session_list" in getattr(self, "__dict__", {}))
                    and self.navigate_by_session_list()
                    and self.selected_exact_session()):
                self.audit.append("verification", step_id="active-session-id",
                                  route_fallback="reopened-exact-scoped-selection",
                                  thread=self.thread, project=self.project,
                                  pinned_uuid=derived_uuid)
                return
            if self.identity_by_continuation():
                return
            raise RuntimeError("the exact pinned session route is required for this standing dispatch")
        if not sessions and (getattr(self, "post_send", False)
                             or (self.phase != "send" and getattr(self, "allow_navigation", True))):
            # The walk that opened the lane can leave the list scrolled past its
            # row; the selection is still the proof, it just has to be in view.
            step_name = "post-send-reveal-lane" if getattr(self, "post_send", False) else "reveal-lane"
            self.reveal_lane_row(step=step_name)
        # Measured 2026-11-27 across dyn-7227546381 and dyn-7227786555: the select
        # phase confirmed this same selection on this same screen, while prepare's
        # three-second probe reported no highlighted row - this theme paints its
        # band late and faintly, so the probe needs the time the selection itself
        # is given elsewhere. A longer window cannot invent a row: the row still
        # has to match the lane.
        if self.selected_label_matches(wait=10):
            self.audit.append("verification", step_id="active-session-row", label=self.label,
                              source="settled sidebar selection")
            return
        if self.allow_navigation and self.navigate_by_session_list():
            if self.selected_label_matches(wait=10):
                self.audit.append("verification", step_id="active-session-row", label=self.label,
                                  source="re-opened from the project session list")
                return
        row = self.find_highlighted_row()
        if row and self.row_matches(row["text"], self.session_name):
            self.audit.append("verification", step_id="active-session-row", label=self.label,
                              row=row["text"], source="highlight found in the project list")
            return
        # Send must never navigate, and the accessibility tree is intermittent. The
        # draft is the one thing that cannot be stale: it was typed into this
        # session by this run's prepare, and the app keeps drafts per session, so
        # its presence in the composer is the identity of the session it holds.
        if self.identity_by_continuation():
            return
        # Measured 2026-11-27 (dyn-7227296013): the lane was open, its transcript
        # on screen and its row visibly boxed, but this theme does not paint the
        # bright selection fill the band detector looks for, so every sidebar
        # proof failed and prepare refused a session it was looking at. The app
        # names the open session in its tab strip, so that reading is the last
        # proof before a refusal.
        if self.open_tab_matches("pinned-open-tab"):
            return
        if self.selection_handoff():
            return
        raise RuntimeError("no route and no highlighted sidebar row identified the pinned session "
                           f"({self.label})")

    def selection_handoff(self, step="identity-from-select"):
        """Take this run's own select proof, for the same lane and only while fresh.

        Measured 2026-11-27: select verified the selection on screen and prepare,
        seconds later, could not re-derive it from a theme whose selected row is
        a faint outline rather than a fill. The proof exists; re-deriving it is
        what fails. The runner records it once per run, and this reads it back
        only for this lane, only from this run's own directory, and only inside
        a fifteen-minute window - nothing a stale or different run could supply.
        """
        path = Path(self.output).parent / "selection.json"
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as error:
            self.audit.append("escalation", step_id=step, reason=str(error)[:160])
            return False
        if str(record.get("thread") or "") != str(self.thread):
            self.audit.append("escalation", step_id=step, thread=record.get("thread"),
                              reason="the recorded selection is another lane")
            return False
        try:
            at = datetime.fromisoformat(str(record.get("at") or "").replace("Z", "+00:00"))
        except ValueError:
            self.audit.append("escalation", step_id=step, reason="the recorded selection has no time")
            return False
        age = (datetime.now(timezone.utc) - at).total_seconds()
        if not 0 <= age <= 900:
            self.audit.append("escalation", step_id=step, age=round(age),
                              reason="the recorded selection is outside its window")
            return False
        self.audit.append("verification", step_id=step, thread=self.thread,
                          source="this run's select phase", age=round(age))
        return True

    def open_tab_matches(self, step="open-tab"):
        """Does the transcript pane's title name this lane?

        The title is small type, and line OCR drops its numeral (measured
        2026-11-27, dyn-7227546381: "Lane 1" came back as "lanelv", which cannot
        be told apart from "Lane 2" by similarity). So the proof is the exact
        locator the driver already trusts for "Search chats": it matches the
        label itself against the title region instead of reading glyphs. The
        line reading is kept in the audit for transparency, never used to decide.
        """
        try:
            frame = self.frame(f"{step}-capture")
        except RuntimeError as error:
            self.audit.append("escalation", step_id=step, reason=str(error))
            return False
        try:
            point = self.locate_exact_text(step, frame, self.label, OPEN_TAB_REGION)
        except RuntimeError as error:
            try:
                lines = self.read_lines(f"{step}-read", frame, OPEN_TAB_REGION)
                reading = self._norm(" ".join(lines))[:80]
            except RuntimeError:
                reading = ""
            self.audit.append("escalation", step_id=step, label=self.label,
                              reading=reading, reason=str(error)[:200])
            return False
        self.audit.append("verification", step_id=step, label=self.label,
                          source="the open session title, matched exactly",
                          point=list(point)[:2])
        return True

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

    def _submit_staged_carrier_arrow(self, frame, started):
        """Submit an already-staged /mission carrier via the verified white up-arrow button."""
        region = SEND_CONTROL
        self.yes("vision-staged-start-arrow", frame,
                 "Does this crop show a white button containing a black upward arrow?", region=region)
        point = _send_arrow_bbox(frame, region=region)
        if point is None:
            raise RuntimeError("the staged mission's arrow outline was not located")
        fresh = self.frame("vision-staged-before-click")
        if not composer_unchanged(frame.crop(COMPOSER), fresh.crop(COMPOSER)):
            raise RuntimeError("the staged mission changed before the start action")
        self.verify_session_identity()
        if time.monotonic() - started > 60:
            raise RuntimeError("the staged mission verification expired before start")
        marker = (self.output.parent
                  / f"harness-freebuff-{self.thread}-staged-start-20261122.json")
        with marker.open("x", encoding="utf-8") as handle:
            json.dump({"thread": self.thread, "step": "vision-submit-staged-mission",
                       "evidence": self.output.name}, handle)
        self.act("vision-submit-staged-mission", CLICK,
                 {"control": f"{self.label} staged mission start arrow",
                  "point": point, "size": list(frame.size)})
        self.post_send = True
        for attempt, delay in enumerate((2.0, 4.0, 6.0, 8.0), start=1):
            time.sleep(delay)
            current = self.frame(f"vision-staged-response-{attempt}")
            if not self.stop_visible(current):
                continue
            if attempt == 1:
                time.sleep(2.0)
                current = self.frame("vision-staged-response-1-confirm")
                if not self.stop_visible(current):
                    continue
            self.verify_session_identity()
            self.audit.append("verification", step_id="vision-running-after-staged-arrow", stop_cue=True)
            return
        raise RuntimeError("the staged mission was submitted once but a sustained Stop cue was not verified")

    def resume_vision_mission(self):
        frame = self.settle_view("vision-before-resume")
        self.verify_session_identity()
        if self.stop_visible(frame):
            raise RuntimeError("the requested session is already running; no restart input")
        started = time.monotonic()
        options = {"resume": "A visible button labeled Resume mission.",
                   "other": "No button labeled Resume mission is visible."}
        route = self.choose("vision-resume-route", frame, "Which button is visible?", options,
                            region=(630, 590, 1550, 960))
        if route == "resume":
            region = (630, 590, 1550, 960)
            point, box = self.locate_exact_text("vision-resume-ocr", frame, "Resume mission", region, with_bounds=True)
            scope = (box[0] - 6, box[1] - 5, box[2] + 6, box[3] + 5)
            self.yes("vision-resume-confirm", frame, "Does the button say Resume mission?", region=scope)
            fresh = self.frame("vision-resume-readback")
            if fresh.crop(scope).tobytes() != frame.crop(scope).tobytes():
                raise RuntimeError("the Resume mission control changed before input")
            self.act("vision-resume", CLICK,
                     {"control": f"{self.label} Resume mission", "point": point, "size": list(frame.size)})
            time.sleep(2)
            frame = self.frame("vision-resume-response")
            self.verify_session_identity()
            if self.stop_visible(frame):
                self.audit.append("verification", step_id="vision-running-after-resume", stop_cue=True)
                return
        region = (500, 180, 1600, 1100)
        try:
            point, box = self.locate_exact_text("vision-start-ocr", frame, "Start mission", region, with_bounds=True)
        except RuntimeError:
            staged_lines = self.read_lines("vision-staged-carrier", frame, (640, 745, 1530, 1048))
            if "/mission" in " ".join(staged_lines).casefold():
                self._submit_staged_carrier_arrow(frame, started)
                return
            if route == "other":
                self.prepare_draft()
                self.send_draft()
                return
            raise RuntimeError(
                "Resume mission was clicked but neither Start mission nor a staged /mission start arrow was verified"
            ) from None
        scope = (box[0] - 6, box[1] - 5, box[2] + 6, box[3] + 5)
        self.yes("vision-start-confirm", frame, "Does the button say Start mission?", region=scope)
        fresh = self.frame("vision-start-readback")
        if fresh.crop(scope).tobytes() != frame.crop(scope).tobytes():
            raise RuntimeError("the Start mission control changed before input")
        self.act("vision-start", CLICK,
                 {"control": f"{self.label} Start mission", "point": point, "size": list(frame.size)})
        self.post_send = True
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
        point = _send_arrow_bbox(frame, region=region)
        if point is None:
            raise RuntimeError("the staged mission's arrow outline was not located")
        fresh = self.frame("vision-staged-before-click")
        if not composer_unchanged(frame.crop(COMPOSER), fresh.crop(COMPOSER)):
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

    def identity_by_continuation(self):
        """Prove the session from the approved continuation or preserved foreign draft.

        The app keeps drafts per session, so the continuation typed into this lane
        after it was proved identifies the session it was typed into. Measured
        2026-11-24 on 7126349762: at send time the selection was drawn as an
        outline the fill probe cannot see, while the draft read back exactly.
        Under Standing Rule 7183684276, a verified foreign-staged draft marker
        recorded in prepare similarly identifies the exact session at send-only.
        """
        if self.phase != "send":
            return False
        pinned = PINNED_UUIDS.get(self.thread) or lookup_local_session_uuid(self.thread)
        marker_path = self._foreign_staged_marker()
        if marker_path is not None and marker_path.is_file():
            try:
                foreign_data = json.loads(marker_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                foreign_data = {}
            excerpt = self._norm(foreign_data.get("excerpt") or "")
            if foreign_data.get("thread") == self.thread and len(excerpt) >= 12:
                if self.saw_text("send-identity-foreign", self.frame("send-identity"),
                                 COMPOSER_TEXT, excerpt):
                    self.require_foreground()
                    self.audit.append("verification", step_id="active-session-id",
                                      route_fallback="foreign-staged-draft",
                                      thread=self.thread, project=self.project,
                                      pinned_uuid=pinned)
                    return True
        if not self.text:
            return False
        if not self.saw_text("send-identity-draft", self.frame("send-identity"),
                             COMPOSER_TEXT, self.text):
            return False
        self.require_foreground()
        self.audit.append("escalation", step_id="identity-on-draft",
                          reason="no route and no readable selection ring; identity rests on the "
                                 "approved continuation this lane already holds")
        self.audit.append("verification", step_id="active-session-id",
                          route_fallback="staged-continuation", thread=self.thread,
                          project=self.project, pinned_uuid=pinned)
        return True

    def verify_active_session(self):
        """Prove the active document is the pinned thread, by route or selection.

        Measured 2026-11-24 on dispatch 7125887396: prepare proved this lane four
        times over, typed the continuation exactly once, and the send then refused
        with "the active FreeBuff document did not expose the exact pinned thread"
        because the accessibility helper returned [] on this handle - the dead tree
        that routes() already documents, re-measured on the live window the same
        way. A channel that is usually absent cannot be the only identity a send
        may stand on, so the proofs are ordered and each is recorded by source:

        1. the exposed accessibility route, exactly one and naming this thread;
        2. the settled exact-selection for the pinned label in its pinned project;
        3. at send only, the approved continuation this lane already holds, which is
           exact because the app keeps drafts per session (7126349762 measured the
           selection ring drawn as an outline the fill probe cannot see, while the
           draft read back exactly).

        The send's other bounds are untouched: freshness, one send, no navigation,
        and the composer pixels must still match the approved frame.
        """
        sessions = self.routes()
        if len(sessions) == 1 and self.thread in sessions[0]:
            self.require_foreground()
            self.audit.append("verification", step_id="active-session-id", exact_id=sessions[0],
                              source="accessibility-route")
            return
        self.audit.append("escalation", step_id="active-session-id", exposed=sessions[:8],
                          reason="no single exposed route is the pinned thread; trying the selection")
        if not self.standing:
            raise RuntimeError("the active FreeBuff document did not expose the exact pinned thread")
        pinned = PINNED_UUIDS.get(self.thread) or lookup_local_session_uuid(self.thread)
        if self.selected_exact_session():
            if pinned and pinned != self.thread and not pinned.startswith(self.thread):
                raise RuntimeError("the selected lane is not the pinned thread")
            self.require_foreground()
            self.audit.append("verification", step_id="active-session-id",
                              route_fallback="exact-scoped-selection", thread=self.thread,
                              project=self.project, pinned_uuid=pinned)
            return
        # Third proof, and the one this app makes exact: a draft is kept per
        # session, so the continuation typed into this lane after it was proved
        # identifies the session it was typed into. Measured 2026-11-24 on 7126349762,
        # where the selection ring at send time was drawn as an outline the fill probe
        # cannot see; the draft was read back exactly, and the send bounds below still
        # hold (unchanged composer pixels since approval, freshness, one send).
        if self.identity_by_continuation():
            return
        raise RuntimeError("the active FreeBuff document did not expose the exact pinned thread")

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
                if (getattr(self, "phase", None) != "send"
                        and not getattr(self, "recovering", False)
                        and hasattr(self, "reloaded")
                        and self.reloaded(frame)
                        and self.reestablish_if_reloaded("draft-verify")):
                    return self.frame("draft-verify-recovered")
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

    _PRE_CLICK_REFUSALS = (
        "FreeBuff is not the foreground window",
        "the standing composer changed after approval",
        "owner desktop activity resumed before input",
        "the verified send window expired before input",
    )

    def prior_send_refused_before_input(self):
        """Did the prior marker's send-once fail before any renderer click?"""
        trace = self.output / "driver.jsonl"
        if not trace.is_file():
            return False
        rows = []
        for line in trace.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        for row in reversed(rows):
            if row.get("kind") == "action" and row.get("step_id") == "send-once" and not row.get("ok"):
                detail = row.get("detail", "")
                return any(reason in detail for reason in self._PRE_CLICK_REFUSALS)
            if row.get("kind") == "action" and row.get("step_id") == "send-once" and row.get("ok"):
                return False
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

    def _foreign_staged_marker(self):
        output = getattr(self, "output", None)
        return (output.parent / "foreign-staged-send-only.json") if output is not None else None

    _CLEAR_BACKSPACES = 320

    def relay_composer_text(self, written, frame):
        """File unrecognizable composer text VERBATIM on #684 before any clear.

        Relay-before-clear (#684 c.7125400686, bounded by the 2026-11-26 ruling):
        if the classification is ever wrong the text is fully recoverable from
        the issue, and oversight can fold anything worthwhile into a later
        steer. The filing is a precondition of the clear, so a failed relay
        raises and the lane parks rather than typing.
        """
        from .windows_freebuff_watch import ISSUE, issue_comment

        reading = " ".join(written)
        excerpt = self._norm(reading)[:400]
        sha = hashlib.sha256(reading.encode("utf-8")).hexdigest()
        issue_comment(
            f"Vision composer relay (A1, ruling 7208601549) / `{self.thread}`: the "
            "composer held text this driver cannot recognize as an owner draft; it "
            "is being cleared now to continue steering.\n\n"
            f"Verbatim reading: {excerpt!r}\n\n"
            f"SHA-256 of the reading: `{sha}`. Screenshot: the run's own "
            "`lane1-before-draft` capture in that run's evidence directory.\n\n"
            "If this was the owner's draft, say so here: the text is preserved in "
            "this comment, and A1 parks on anything that reads as a person's writing.")
        self.audit.append("verification", step_id="composer-text-relayed", sha256=sha,
                          excerpt=excerpt[:120], issue=ISSUE,
                          source="relay-before-clear")
        return excerpt

    def clear_composer(self, action, params):
        """Dismiss composer text that is not the owner's draft (A1 ruling).

        The dismiss uses the same channel the standing type path uses - WM_CHAR
        backspaces posted to the verified composer renderer - so no global key
        event can land outside FreeBuff. It is bounded, and the caller re-reads
        the composer afterwards: a clear that does not take is a named refusal,
        never a silent continue.
        """
        if params.get("control") != f"{self.label} composer":
            raise RuntimeError("the clear request names another control")
        hit = self.composer_renderer
        for attempt in range(1, self._CLEAR_BACKSPACES + 1):
            if attempt % 16 == 1 and (
                    not hit or self.user.GetAncestor(hit, 2) != self.require_foreground()):
                raise RuntimeError("the verified composer renderer is no longer available")
            # Chrome's editor consumes Backspace from the key channel; a bare
            # WM_CHAR is delivered but does not delete (measured 2026-11-27,
            # dyn-7228544294: 320 characters posted, the text read back intact).
            # Post the key pair and the character, to the same verified renderer.
            if not (self.user.PostMessageW(hit, 0x0100, 0x08, 1)
                    and self.user.PostMessageW(hit, 0x0101, 0x08, 0xC0000001)
                    and self.user.PostMessageW(hit, 0x0102, 0x08, 1)):
                raise RuntimeError("the verified FreeBuff composer refused the dismiss key")
            if attempt % 16 == 0:
                time.sleep(0.05)
        time.sleep(0.3)
        self.audit.append("verification", step_id="composer-cleared",
                          characters=self._CLEAR_BACKSPACES,
                          source="WM_CHAR backspace on the verified renderer")

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
        foreign_marker = self._foreign_staged_marker()
        foreign_data = None
        if not pointer and foreign_marker is not None and foreign_marker.is_file():
            foreign_data = json.loads(foreign_marker.read_text(encoding="utf-8"))
            if foreign_data.get("thread") != self.thread:
                raise RuntimeError("foreign-staged-send-only marker belongs to another thread")
            placeholder = "Ask Freebuff... Use / for commands, @ for files"
            written = self.read_lines("send-foreign-draft", frame, COMPOSER_TEXT)
            if self.composer_written_route(written, placeholder) != "foreign":
                raise RuntimeError("the preserved foreign staged draft was not verified at send")
            self.audit.append("verification", step_id="verify-foreign-staged-send-only",
                              excerpt=foreign_data.get("excerpt", "")[:120],
                              source="standing-rule-7183684276")
        else:
            frame = self.verify_draft(frame)
        if self.scoped_input and not pointer and self.turn_running(frame):
            raise RuntimeError("the requested session resumed before send; no restart input")
        region = (1439, 1040, 1487, 1105) if pointer else SEND_CONTROL
        # The arrow's own pixels answer this, and they answer it exactly: the
        # outline is located in the send control's own region. Asking a model
        # first parked a staged, identity-verified draft on a 0.31 guess
        # (measured 2026-11-27, dyn-7229043019), which is the same defect the
        # composer routes already cured. The model is asked only when there is no
        # outline to measure at all.
        point = _send_arrow_bbox(frame, region=region)
        if point is None:
            self.yes("verify-send-arrow", frame,
                     "Does this image show a white button containing a black upward arrow?",
                     region=region)
            point = _send_arrow_bbox(frame, region=region)
            if point is None:
                raise RuntimeError("the verified Send button outline could not be located")
        else:
            self.audit.append("verification", step_id="send-arrow-outline",
                              point=list(point)[:2], source="the send control's own pixels")
        if pointer:
            control = f"{self.label} queue arrow"
            send_text = self.text
        elif foreign_data is not None:
            control = f"{self.label} Send-only (foreign staged draft preserved)"
            send_text = foreign_data.get("excerpt") or "<foreign-staged-preserved>"
        else:
            control = f"{self.label} Send (up arrow)"
            send_text = self.text
        params = {"thread": self.thread, "text": send_text, "control": control,
                  "point": point, "size": list(frame.size)}
        self.require_foreground()
        if self.thread in BURN_SESSIONS or self.thread == SCM_THREAD:
            # Identity, not the route alone: a dead accessibility tree must not
            # become a dead-end at the click.
            self.verify_session_identity()
        if self.standing:
            fresh = self.frame("pre-send-readback")
            if (not composer_unchanged(frame.crop(COMPOSER), fresh.crop(COMPOSER))
                    or (not pointer and self.turn_running(fresh))):
                raise RuntimeError("composer changed between verification and send")
        age = time.monotonic() - observed_at
        if age > 60:
            # Identity re-verification can outlast the observation window by itself
            # (measured 2026-11-27, dyn-7229598525: the arrow verified, then
            # "send-once: the verified send window expired before input"). Time is
            # not the guarantee here - the composer is. Re-read it now, and extend
            # the window only when it is byte-identical to the verified one.
            fresh = self.frame("pre-send-reanchor")
            if not composer_unchanged(frame.crop(COMPOSER), fresh.crop(COMPOSER)):
                raise RuntimeError("the verified session and composer observations expired before send")
            self.audit.append("escalation", step_id="pre-send-reanchor",
                              age_seconds=round(age, 3),
                              reason="identity work outlasted the observation window; the composer re-read unchanged")
            observed_at = time.monotonic()
            age = 0.0
        self.audit.append("verification", step_id="pre-send-freshness", age_seconds=round(age, 3))
        self.send_deadline = observed_at + 60
        # The verified composer is the window's guarantee in both modes: the
        # executor re-reads it before input and after its own identity pass.
        self.send_composer = frame.crop(COMPOSER).tobytes()
        with marker.open("x", encoding="utf-8") as handle:
            json.dump({"thread": self.thread, "step": f"{operation}-once", "text": self.text,
                       "evidence": self.output.name}, handle)
        self.act(f"{operation}-once", SEND, params)
        self.post_send = True
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
            # Measured 2026-11-25 on the SCMessenger session: the app renders
            # "Today's hours are used up ... Your daily hours refill at 12:00 AM
            # HST" and never uses the phrase "usage limit", so the marker below
            # was the only thing a quota block could hit - and it named a UI
            # failure instead of the exhausted account it actually was.
            ("hoursareusedup", "daily hours exhausted"),
            ("dailyhoursrefill", "daily hours exhausted"),
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
        if any(self._norm(label) and self._norm(label) in reading
               for label in COMPOSER_PLACEHOLDERS):
            self.audit.append("verification", step_id="composer-placeholder-known",
                              reading=reading[:80], route="empty")
            # Primary evidence, recorded so the empty route does not ask a model
            # or depend on a hint glyph the composer is not drawing.
            self._placeholder_confirmed = True
            return None
        if self._norm(self.text) and self._norm(self.text) in reading:
            return "staged"
        return "foreign"

    def prepare_draft(self):
        if not getattr(self, "recovering", False):
            self.reestablish_if_reloaded("prepare")
        frame = self.settle_view("lane1-before-draft")
        self.verify_lane(frame)
        # A4: the tier is checked on the verified lane, before any input, so a
        # restart can never land on the free pool.
        self.verify_tier(frame)
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
            if route is None:
                # Nothing in the composer and the composer showing its own
                # placeholder are the same state, and that state is typed into,
                # not asked about. Measured 2026-11-27 (dyn-7228809373): the
                # empty composer fell through every primary cue to a 0.45
                # "stop" guess, which parked a lane that was ready for input.
                route = "empty"
                self.audit.append("verification", step_id="composer-route-empty",
                                  reading=self._norm(" ".join(written))[:80],
                                  source="the composer's own text")
            if route == "foreign":
                has_arrow = has_send_arrow_outline(frame)
                if not has_arrow:
                    tab_lines = self.read_lines("composer-tab-hint", frame, (646, 1007, 707, 1051))
                    norm_written = self._norm(" ".join(written))
                    has_tab_badge = any("tab" in self._norm(line) for line in tab_lines)
                    if has_tab_badge or norm_written.endswith("tab"):
                        # Measured on dyn-7179075691-2ae32937: SEND_CONTROL max_luma=187 (<205),
                        # so FreeBuff is showing dim grey autocomplete hint + Tab badge, NOT a draft.
                        self.audit.append(
                            "verification", step_id="composer-empty-autocomplete-ghost",
                            has_arrow=False, has_tab_badge=has_tab_badge,
                            ghost_preview=norm_written[:80],
                        )
                        route = "empty"
                if route == "foreign" and composer_text_verdict(" ".join(written)) == "machine":
                    # A1 ruling 2026-11-26 (#684 c.7208601549): unrecognizable
                    # machine text is not an owner draft. Relay it verbatim FIRST,
                    # then dismiss it and keep steering - never park on it.
                    self.relay_composer_text(written, frame)
                    # The clear posts WM_CHAR backspaces to the renderer a CLICK
                    # established. With text already in the composer this route
                    # never clicked, so the renderer was unknown and the clear
                    # refused (measured 2026-11-27, dyn-7228279746: "the verified
                    # composer renderer is no longer available" immediately
                    # before the clear). Focus it exactly as the typing route
                    # does, then clear.
                    left, top, right, bottom = COMPOSER_TEXT
                    self.act("focus-machine-composer", CLICK,
                             {"control": f"{self.label} composer",
                              "point": [round((left + right) / 2), round((top + bottom) / 2)],
                              "size": list(frame.size)})
                    time.sleep(0.2)
                    self.act("clear-machine-composer", CLEAR,
                             {"control": f"{self.label} composer"})
                    time.sleep(1.0)
                    frame = self.frame("lane1-composer-cleared")
                    leftover = self.read_lines("composer-cleared-readback", frame,
                                               COMPOSER_TEXT)
                    if composer_text_verdict(" ".join(leftover)) == "machine":
                        raise RuntimeError(
                            "composer-route: the machine text survived the clear "
                            f"({self._norm(' '.join(leftover))[:120]!r})") from None
                    self.audit.append(
                        "verification", step_id="composer-machine-text-replaced",
                        relayed=self._norm(" ".join(written))[:120],
                        source="owner ruling 7208601549: replace and continue")
                    try:
                        point = self.locate_exact_text(
                            "locate-empty-placeholder", frame, placeholder,
                            (646, 950, 1260, 1014))
                    except RuntimeError:
                        left, top, right, bottom = COMPOSER_TEXT
                        point = [(left + right) // 2, (top + bottom) // 2]
                    route = "placeholder"
                if route == "foreign":
                    if has_arrow and getattr(self, "standing", False):
                        # Standing Rule 7183684276: preserve foreign staged text without overwriting;
                        # hand off to send phase as Send-only once verified identity + pixels hold.
                        marker_path = self._foreign_staged_marker()
                        if marker_path is not None:
                            composer_sha = hashlib.sha256(frame.crop(COMPOSER).tobytes()).hexdigest()
                            excerpt = self._norm(" ".join(written))[:120]
                            marker_path.parent.mkdir(parents=True, exist_ok=True)
                            marker_path.write_text(json.dumps({
                                "thread": self.thread,
                                "composer_sha256": composer_sha,
                                "excerpt": excerpt,
                            }) + "\n", encoding="utf-8")
                            self.audit.append(
                                "verification", step_id="foreign-staged-send-only",
                                composer_sha256=composer_sha, excerpt=excerpt,
                                source="standing-rule-7183684276",
                            )
                            print("Platform state: foreign-staged-send-only")
                            return
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
            if getattr(self, "_placeholder_confirmed", False):
                # The composer's own placeholder is primary evidence that the
                # editor is empty. Measured 2026-11-27 (dyn-7228809373): this
                # route asked a model whether a Tab badge was present and the
                # 0.45 answer parked a lane that was ready for input; the badge
                # is not even drawn in this state.
                self.audit.append("verification", step_id="composer-empty-primary",
                                  source="the composer's own placeholder")
                try:
                    point = self.locate_exact_text("locate-empty-placeholder", frame,
                                                   self.text, COMPOSER_TEXT)
                except RuntimeError:
                    left, top, right, bottom = COMPOSER_TEXT
                    point = [round((left + right) / 2), round((top + bottom) / 2)]
            else:
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
        # The probe's job is to witness a bystander lane across the input, not to
        # gate the dispatch on it. Measured 2026-11-24: Kalshi (7127830177) and Disk
        # Audit (7127395609) both parked at "locate-bystander-lane: exact OCR label
        # 'Lane 1' was not verified" because Lane 1's row was scrolled out of the
        # sidebar by the previous lane's walk - a disposition about the SIDEBAR's
        # scroll position that had nothing to do with the target lane. The reveal is
        # bounded here, and a bystander that still cannot be seen is recorded as
        # unobserved instead of ending the run before its own first phase.
        try:
            frame = self.scroll_sidebar_to_top()
        except RuntimeError as error:
            self.audit.append("escalation", step_id="bystander-sidebar-top", reason=str(error))
        try:
            point, box = self.locate_exact_text("locate-bystander-lane", frame, "Lane 1",
                                                (128, 300, 300, 850), with_bounds=True)
        except RuntimeError as error:
            self.audit.append("verification", step_id="bystander-unobserved",
                              reason="the separate Lane 1 row is not in view; recording it as "
                                     "unobserved rather than blocking the dispatch",
                              detail=str(error)[:200])
            return
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
    dispatch.allow_navigation = args.phase in {"prepare", "send", "vision-resume"}
    dispatch.phase = args.phase
    try:
        if args.phase == "open":
            if args.thread != THREAD:
                raise RuntimeError("use verified search for this session")
            dispatch.open_lane()
        elif args.phase == "observe-running":
            dispatch.observe_running()
        elif args.phase == "vision-resume":
            if not args.standing or args.thread not in SESSIONS:
                raise RuntimeError("vision resume requires a standing pinned session")
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
