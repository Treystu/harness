"""Run the operator-approved FreeBuff Lane 1 dispatch with Harness vision."""

import argparse
import base64
import ctypes
import hashlib
import io
import json
import os
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
BURN_SESSIONS = {
    "0d7e2f37": "BigEnergyCo",
    "7d4a9b14": "Kalshi Paper Burndown",
    "9ecc3453": "Lane 2",
    "918dad1a": "Harness Audit Lane",
    "0319b9f6": "SCMessenger Audit Lane",
}
DISK_POINTER = ("Run D-007 from Treystu/slow-lane-ledger. Read "
                "DISK-AUDIT-MISSION-V3-2026-11-22.md in oversight/disk-audit-2026-11-19.")
SESSIONS = {
    THREAD: ("Lane 1", CONTINUATION),
    DISK_THREAD: ("Disk Audit", CONTINUATION),
    SCM_THREAD: ("SCMessenger", CONTINUATION),
    **{thread: (label, CONTINUATION) for thread, label in BURN_SESSIONS.items()},
}
COMPOSER = (630, 918, 1550, 1110)
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

    def require_foreground(self, attempts=3):
        """FreeBuff must hold the foreground; re-assert it before giving up.

        The measured holder of a lost foreground was the driver's own phase
        child (a console window titled with its interpreter path), so a single
        observation that FreeBuff is not in front is not a reason to park a
        lane. Take the foreground back, then prove it.
        """
        hwnd = self.window.require_window()
        for attempt in range(1, attempts + 1):
            current = self.window.api.foreground()
            if current == hwnd:
                return hwnd
            # Name the holder: an unnamed park cannot be resolved from its evidence.
            self.audit.append("escalation", step_id=f"foreground-{attempt}", expected=hwnd,
                              holder=current, holder_detail=self.describe(current))
            if self.standing or attempt == attempts:
                break
            if not activate_exact(hwnd, self.window.api.foreground):
                time.sleep(0.6)
                continue
            time.sleep(0.5)
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
            self.verify_active_session()
            fresh = self.frame("send-executor-fresh")
            if (fresh.crop(COMPOSER).tobytes() != self.send_composer or self.stop_visible(fresh)):
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
        started = time.monotonic()
        capture = self.screen.capture(Target("existing FreeBuff desktop", GUI))
        elapsed = time.monotonic() - started
        if elapsed > 2:
            raise RuntimeError(f"{step}: capture exceeded 2s")
        (self.output / f"{step}.png").write_bytes(capture.payload)
        self.audit.append("capture", step_id=step, **capture.summary(),
                          foreground=self.window.api.foreground() == self.window.handle,
                          capture_seconds=round(elapsed, 3))
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
        response = transport.call_service(
            SYSTEM_ONE_URL, questions, headers={"Authorization": f"Bearer {self.key}"},
            timeout=10, body_extra={"state": {"goal": self.goal, "screen": "frame"},
                                    "model": "jev-1.14.0"},
            assets=assets, images_enabled=True)
        if not response.ok:
            raise RuntimeError(f"{step}: {response.outcome}: {response.detail}")
        answers = response.payload["answers"]
        self.audit.append("decision", step_id=step, goal=self.goal, model=response.payload.get("model"),
                          answers=answers)
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

    def locate_exact_text(self, step, frame, label, region, *, whole=False, with_bounds=False):
        left, top, right, bottom = region
        crop = frame.crop(region).resize(((right - left) * 3, (bottom - top) * 3))
        # Windows OCR resolves files by absolute path only.
        path = (self.output / f"{step}-ocr.png").resolve()
        self.image_ops.invert(self.image_ops.grayscale(crop)).save(path)
        command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-File",
                   str(Path(__file__).with_name("windows_ocr_exact.ps1")),
                   "-Path", str(path), "-Label", label]
        if whole:
            command.append("-WholeText")
        result = osal.run(command, timeout=8)
        if not result.ok:
            raise RuntimeError(f"{step}: exact OCR label {label!r} was not verified")
        point = json.loads(result.stdout)
        xy = [left + round(point["x"] / 3), top + round(point["y"] / 3)]
        self.audit.append("extraction", step_id=step, source="windows-ocr",
                          exact_label=label, point=xy)
        if with_bounds:
            bounds = [round(value / 3) + origin for value, origin in
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
        result = osal.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-File",
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

    def settled_roster(self, step, region, attempts=6):
        """A roster two consecutive censuses agree on, or a refusal naming both."""
        previous = None
        rows = []
        frame = self.frame(f"{step}-0")
        for attempt in range(1, attempts + 1):
            rows = self.read_roster(f"{step}-{attempt}", frame, region)
            # Settling is about where the rows ARE: the OCR engine alternates
            # icons and truncations on a stationary list (measured: "Kalshi
            # Paper Bumd" vs "Kalshi Paper Burndc V" on one unchanged row), so
            # comparing text can never settle and comparing geometry can.
            current = tuple(round(row["y"] / 2) for row in rows)
            if rows and previous is not None and same_rows(previous, current):
                self.audit.append("verification", step_id=f"{step}-settled", rows=len(rows),
                                  censuses=attempt,
                                  texts=[row["text"] for row in rows][:16])
                return frame, rows
            previous = current
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
        seen = max(candidates, key=len)
        if len(seen) < 10:
            return False
        common = 0
        for left, right in zip(seen, wanted):
            if left != right:
                break
            common += 1
        if common < 6:
            return False
        if wanted.startswith(seen):
            return True
        window = wanted[:len(seen)] if len(seen) <= len(wanted) else wanted
        return SequenceMatcher(None, seen, window).ratio() >= 0.85

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

    def click_exact_row(self, step, frame, row):
        """Click one row already chose from a settled census."""
        point = [round((row["x"] + row["x1"]) / 2), round(row["y"] + 8)]
        scope = (round(row["x"] - 6), round(row["y"] - 4),
                 round(row["x1"] + 6), round(row["y"] + 20))
        fresh = self.frame(f"{step}-readback")
        if fresh.crop(scope).tobytes() != frame.crop(scope).tobytes():
            raise RuntimeError(f"{step}: the settled row moved before the click")
        self.act(step, CLICK, {"control": f"session row {row['text']}", "point": point,
                               "size": list(frame.size)})
        return row

    def click_roster_row(self, step, frame, rows, label):
        matches = [row for row in rows if self.row_matches(row["text"], label)]
        if len(matches) != 1:
            raise RuntimeError(f"{step}: {label!r} matched {len(matches)} settled rows; "
                               f"roster: {[row['text'] for row in rows][:14]}")
        row = matches[0]
        point = [round((row["x"] + row["x1"]) / 2), round(row["y"] + 8)]
        scope = (round(row["x"] - 6), round(row["y"] - 4),
                 round(row["x1"] + 6), round(row["y"] + 20))
        fresh = self.frame(f"{step}-readback")
        if fresh.crop(scope).tobytes() != frame.crop(scope).tobytes():
            raise RuntimeError(f"{step}: the settled row moved before the click")
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

    def selected_label_matches(self, wait=0):
        deadline = time.monotonic() + wait
        while True:
            try:
                frame, rows = self.settled_roster("selected-row-probe", SIDEBAR, attempts=5)
            except RuntimeError as error:
                self.audit.append("escalation", step_id="selected-row-probe", reason=str(error))
                return False
            row = self.highlighted_row(frame, rows)
            if row and self.row_matches(row["text"], self.label):
                self.audit.append("verification", step_id="selected-row", row=row["text"])
                return True
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

    def walk_session_list(self, pages=8):
        """Walk the project session list page by page, each page settled before a pick."""
        frame = self.scroll_sidebar_to_top()
        seen = []
        for page in range(1, pages + 1):
            try:
                frame, rows = self.settled_roster(f"session-list-{page}", SIDEBAR, attempts=5)
            except RuntimeError as error:
                self.audit.append("escalation", step_id="walk-session-list", reason=str(error))
                return False
            texts = [row["text"] for row in rows]
            if texts in seen:
                return False
            seen.append(texts)
            matches = [row for row in rows if self.row_matches(row["text"], self.label)]
            if len(matches) == 1:
                self.click_roster_row(f"session-list-pick-{page}", frame, rows, self.label)
                return True
            expand = next((row for row in rows
                           if row["text"].strip() in {"Show more", "More chats"}), None)
            if expand:
                self.click_roster_row(f"session-list-expand-{page}", frame, rows, expand["text"])
                time.sleep(1.0)
                continue
            band = frame.crop((SIDEBAR[0], SIDEBAR[1], SIDEBAR[2], SIDEBAR[3] - 10)).tobytes()
            if not self.scroll_by(f"session-list-scroll-{page}", frame, [196, 850], -240):
                frame = self.frame(f"session-list-scrolled-{page}-recapture")
                continue
            time.sleep(0.9)
            frame = self.frame(f"session-list-scrolled-{page}")
            if frame.crop((SIDEBAR[0], SIDEBAR[1], SIDEBAR[2], SIDEBAR[3] - 10)).tobytes() == band:
                return False
        return False

    def routes(self):
        """Whatever routes the app exposes, whatever shape the helper returns.

        Measured: the helper answers `[]` on most handles (dead accessibility
        tree) and a list of routes when the tree is live; it is never assumed
        to be either.
        """
        try:
            payload = self.read_app_structure()
        except RuntimeError as error:
            self.audit.append("escalation", step_id="routes", reason=str(error))
            return []
        if isinstance(payload, dict):
            items = payload.get("documents") or payload.get("routes") or []
        elif isinstance(payload, list):
            items = payload
        else:
            return []
        return [str(item.get("route") or item.get("url") or item)
                if isinstance(item, dict) else str(item) for item in items]

    def _prefix_matches(self, text, label):
        """Is this row plausibly the configured lane, allowing app clipping?"""
        seen, wanted = self._norm(text), self._norm(label)
        return bool(seen and wanted and len(wanted) >= 4
                    and (seen.startswith(wanted) or wanted.startswith(seen)))

    def navigate_by_unique_prefix(self, pages=8):
        """Open the configured lane when exactly ONE session list row can be it.

        The configured names are ours and the app clips its own rows (measured:
        no row reads "Lane 2", one reads "Lane 2 Waist Composition Mission
        Brief"; none reads "BigEnergyCo", five read "BigEnergyCo ..."). One
        candidate is a pick; several are named and refused, never guessed.
        """
        frame = self.scroll_sidebar_to_top()
        found, seen = [], []
        for page in range(1, pages + 1):
            try:
                frame, rows = self.settled_roster(f"prefix-{page}", SIDEBAR, attempts=4)
            except RuntimeError as error:
                self.audit.append("escalation", step_id="prefix-walk", reason=str(error))
                return False
            texts = [self._norm(row["text"]) for row in rows]
            if texts in seen:
                break
            seen.append(texts)
            for row in rows:
                if self._prefix_matches(row["text"], self.label):
                    if all(self._norm(row["text"]) != self._norm(name) for _, name in found):
                        found.append((page, row["text"]))
            if not self.scroll_by(f"prefix-scroll-{page}", frame, [196, 850], -400):
                frame = self.frame(f"prefix-{page}-recapture")
                continue
            time.sleep(0.9)
            frame = self.frame(f"prefix-{page}-after")
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
        for index in range(1, min(page + 2, 9)):
            frame, rows = self.settled_roster(f"prefix-pick-{index}", SIDEBAR, attempts=4)
            row = next((candidate for candidate in rows
                        if self._norm(candidate["text"]) == self._norm(name)), None)
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
            if row:
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
                                  reason=f"{self.label!r} is not in the project session list")
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
        if self.navigate_by_session_list():
            return
        if self.list_only():
            if self.navigate_by_unique_prefix() or self.identify_by_route():
                return
            raise RuntimeError(f"the project session list does not hold {self.label!r} "
                               "and no candidate exposes this thread's route")
        frame = self.ensure_search_closed(self.frame("freebuff-before-search-reset"))
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
                frame = self.wait_dialog(True, seconds=8)
                break
            except RuntimeError:
                # A toggle that closed a stale dialog reads the same as one that
                # failed to open it; one more verified click settles which it was.
                self.audit.append("escalation", step_id=f"open-session-search-{attempt}",
                                  reason="the dialog was not open after the click")
                frame = self.frame(f"search-open-retry-{attempt}")
        else:
            raise RuntimeError("the search dialog did not open after two verified search clicks")

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
                    or self.identify_by_route()):
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
            if self.navigate_by_unique_prefix() or self.identify_by_route():
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
        if self.phase == "send" and self.saw_text(
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

    def verify_active_session(self):
        sessions = self.routes()
        if len(sessions) != 1 or self.thread not in sessions[0]:
            raise RuntimeError("the active FreeBuff document did not expose the exact pinned thread")
        self.require_foreground()
        self.audit.append("verification", step_id="active-session-id", exact_id=sessions[0])

    def read_app_structure(self, *options):
        hwnd = self.require_foreground()
        helper = Path(__file__).with_name("windows_freebuff_active_session.ps1")
        result = osal.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-File",
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
        result = osal.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-File",
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

    def send_draft(self):
        pointer = self.text == DISK_POINTER
        operation = "steer" if pointer else "send"
        marker = self.output.parent / f"harness-freebuff-{self.thread}-{operation}-20261122.json"
        if marker.exists():
            raise RuntimeError("the one-send marker already exists; inspect the prior outcome")
        frame = self.frame("lane1-before-send")
        if self.reestablish_if_reloaded("send"):
            frame = self.frame("lane1-before-send-recovered")
        observed_at = time.monotonic()
        self.verify_lane(frame)
        frame = self.verify_draft(frame)
        if self.scoped_input and not pointer and self.stop_visible(frame):
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
            # Identity, not the route alone: send never navigates, so a dead
            # accessibility tree must not become a dead-end here.
            self.verify_session_identity()
        if self.standing:
            fresh = self.frame("pre-send-readback")
            if (frame.crop(COMPOSER).tobytes() != fresh.crop(COMPOSER).tobytes()
                    or (not pointer and self.stop_visible(fresh))):
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
            self.frame("disk-steering-response")
            return
        for observation, delay in enumerate((1.2, 2.0, 3.0, 5.0), start=1):
            time.sleep(delay)
            frame = self.frame(f"platform-response-{observation}")
            if not self.stop_visible(frame):
                continue
            try:
                self.locate_exact_text("verify-queue-placeholder", frame,
                                       QUEUE_PLACEHOLDER, QUEUE_REGION)
            except RuntimeError:
                continue
            self.verify_lane(frame)
            self.audit.append("verification", step_id="platform-running",
                              target=self.thread, stop_cue=True)
            print("Platform state: running")
            return
        raise RuntimeError("one send dispatched; the Stop square and exact queue placeholder were not verified")

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

    def prepare_draft(self):
        if not getattr(self, "recovering", False):
            self.reestablish_if_reloaded("prepare")
        frame = self.settle_view("lane1-before-draft")
        self.verify_lane(frame)
        if self.scoped_input and self.stop_visible(frame):
            raise RuntimeError("the requested session is already running; no restart input")
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
            placeholder = "Ask Freebuff... Use / for commands, @ for files"
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
        sha256 = hashlib.sha256((self.output / "observed-stop.png").read_bytes()).hexdigest()
        self.audit.append("verification", step_id="bystander-stop", stop_cue=True,
                          thread=self.thread, sha256=sha256)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--phase", choices=("open", "search", "query", "select", "prepare",
                                           "send", "steer-prepare", "steer-send", "observe-running"),
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
    dispatch.allow_navigation = args.phase == "prepare"
    dispatch.phase = args.phase
    try:
        if args.phase == "open":
            if args.thread != THREAD:
                raise RuntimeError("use verified search for this session")
            dispatch.open_lane()
        elif args.phase == "observe-running":
            dispatch.observe_running()
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
            if args.thread == SCM_THREAD:
                raise RuntimeError("the session composer must be scoped before preparing a draft")
            dispatch.prepare_draft()
        else:
            if args.thread == SCM_THREAD:
                raise RuntimeError("the session composer must be scoped before sending")
            dispatch.send_draft()
    except (OSError, RuntimeError, KeyError, TypeError, ValueError) as error:
        dispatch.audit.append("escalation", step_id="dispatch", reason=str(error))
        print(f"BLOCKED: {error}")
        return 1
    print(json.dumps(dispatch.audit.verify().to_dict()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
