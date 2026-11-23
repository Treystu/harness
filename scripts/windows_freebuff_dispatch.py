"""Run the operator-approved FreeBuff Lane 1 dispatch with Harness vision."""

import argparse
import base64
import ctypes
import io
import json
import os
import time
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
from .windows_notepad_window import WindowsWindowScreen

GOAL = "Restart the existing Harness Lane 1 local FreeBuff session (315608d2) once in place."
LANE = "Lane 1 navigation row directly below the Harness project heading"
FOCUS = Action("focus_freebuff", MUTATING, "focus_freebuff", ("title",),
               "Bring the existing FreeBuff window forward.", "gui")
CLICK = Action("click_freebuff", MUTATING, "click_freebuff", ("control", "point", "size"),
               "Click the vision-verified FreeBuff control.", "gui")
TYPE = Action("type_freebuff", MUTATING, "type_freebuff", ("text",),
              "Type the exact approved continuation into the empty Lane 1 composer.", "gui")
SEND = Action("send_freebuff", MUTATING, "send_freebuff",
              ("thread", "text", "control", "point", "size"),
              "Send the exact authorized draft in the verified Lane 1 session once.", "gui")
QUERY = Action("query_freebuff", MUTATING, "query_freebuff", ("thread", "text", "control"),
               "Search FreeBuff for the exact existing session title.", "gui")
VOCABULARY = Vocabulary("windows-freebuff-dispatch", "1.2.0", [FOCUS, CLICK, TYPE, SEND, QUERY])
THREAD = "315608d2"
CONTINUATION = "continue in full"
DISK_THREAD = "f90f01e9"
SCM_THREAD = "2ae32937"
DISK_POINTER = ("Run D-007 from Treystu/slow-lane-ledger. Read "
                "DISK-AUDIT-MISSION-V3-2026-11-22.md in oversight/disk-audit-2026-11-19.")
SESSIONS = {
    THREAD: ("Lane 1", CONTINUATION),
    DISK_THREAD: ("Disk Audit", CONTINUATION),
    SCM_THREAD: ("SCMessenger", CONTINUATION),
}
COMPOSER = (630, 918, 1550, 1110)
LANE_NAV = (80, 590, 390, 750)
SEND_CONTROL = (1480, 1043, 1535, 1100)


class Dispatch:
    def __init__(self, output, key, *, thread=THREAD):
        from PIL import Image, ImageOps

        self.image = Image
        self.image_ops = ImageOps
        self.window = FreeBuffWindow()
        self.user = self.window.user
        self.user.SetThreadDpiAwarenessContext.argtypes = (ctypes.c_void_p,)
        self.user.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        self.user.SetThreadDpiAwarenessContext(-4)
        self.user.SwitchToThisWindow.argtypes = (wintypes.HWND, wintypes.BOOL)
        self.user.SwitchToThisWindow.restype = None
        self.user.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
        self.user.BringWindowToTop.argtypes = (wintypes.HWND,)
        self.user.SetForegroundWindow.argtypes = (wintypes.HWND,)
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
        self.label, self.text = SESSIONS[thread]
        self.goal = (GOAL if thread == THREAD else
                     f"Restart the existing {self.label} FreeBuff session ({thread}) once in place.")
        self.composer_renderer = None
        self.search_renderer = None
        self.audit = AuditLog(output / "driver.jsonl")
        self.screen = WindowsWindowScreen(self.window, source="windows-freebuff")
        self.driver = Driver(settings=Settings(jev_api_key=key, allow_write=True),
                             vocabulary=VOCABULARY, audit=self.audit)
        self.driver.register_executor(FOCUS.name, self.focus)
        self.driver.register_executor(CLICK.name, self.click)
        self.driver.register_executor(TYPE.name, self.type_text)
        self.driver.register_executor(SEND.name, self.send)
        self.driver.register_executor(QUERY.name, self.query)

    def require_foreground(self):
        hwnd = self.window.require_window()
        if self.window.api.foreground() != hwnd:
            raise RuntimeError("FreeBuff is not the foreground window")
        return hwnd

    def focus(self, action, params):
        hwnd = self.window.require_window()
        if params["title"] != TITLE:
            raise RuntimeError("the requested window title differs")
        if self.window.api.foreground() != hwnd:
            if not self.window.api.focus(hwnd, TITLE):
                self.user.SwitchToThisWindow(hwnd, True)
        previous = self.window.api.foreground()
        if previous and previous != hwnd:
            caller = ctypes.windll.kernel32.GetCurrentThreadId()
            current = self.user.GetWindowThreadProcessId(previous, None)
            attached = caller != current and self.user.AttachThreadInput(caller, current, True)
            try:
                self.user.BringWindowToTop(hwnd)
                self.user.SetForegroundWindow(hwnd)
            finally:
                if attached:
                    self.user.AttachThreadInput(caller, current, False)
            time.sleep(0.15)
        self.require_foreground()

    def click(self, action, params):
        hwnd = self.require_foreground()
        rect = wintypes.RECT()
        if self.dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)):
            raise RuntimeError("could not read FreeBuff compositor bounds")
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
            keyboard.type_text(character)

    def send(self, action, params):
        if params["thread"] != self.thread or params["text"] != self.text:
            raise RuntimeError("the thread or text differs from the approved continuation")
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

    def locate_exact_text(self, step, frame, label, region):
        left, top, right, bottom = region
        crop = frame.crop(region).resize(((right - left) * 3, (bottom - top) * 3))
        path = self.output / f"{step}-ocr.png"
        self.image_ops.invert(self.image_ops.grayscale(crop)).save(path)
        result = osal.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-File",
             str(Path(__file__).with_name("windows_ocr_exact.ps1")),
             "-Path", str(path), "-Label", label], timeout=8)
        if not result.ok:
            raise RuntimeError(f"{step}: exact OCR label {label!r} was not verified")
        point = json.loads(result.stdout)
        xy = [left + round(point["x"] / 3), top + round(point["y"] / 3)]
        self.audit.append("extraction", step_id=step, source="windows-ocr",
                          exact_label=label, point=xy)
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

    def open_search(self):
        frame = self.frame("freebuff-before-search")
        self.require_foreground()
        region = (296, 75, 333, 104)
        self.yes("identify-search-control", frame,
                 "Does this crop show a magnifying glass search icon?",
                 region=region)
        left, top, _, _ = region
        pixels = frame.crop(region).convert("L")
        box = pixels.point(lambda level: 255 if level >= 140 else 0).getbbox()
        if box is None or not (8 <= box[2] - box[0] <= 25 and 8 <= box[3] - box[1] <= 25):
            raise RuntimeError("the verified Search icon outline could not be located")
        point = [left + (box[0] + box[2]) // 2, top + (box[1] + box[3]) // 2]
        self.act("open-session-search", CLICK,
                 {"control": "FreeBuff session search", "point": point, "size": list(frame.size)})
        time.sleep(0.6)
        self.frame("freebuff-search-open")

    def search_for_session(self):
        frame = self.frame("freebuff-before-query")
        self.require_foreground()
        region = (527, 168, 774, 228)
        self.yes("verify-search-field", frame,
                 "Are the literal words 'Search chats' visible in the empty search field?",
                 region=region)
        point = self.locate_exact_text("locate-search-field", frame, "Search chats", region)
        self.act("focus-search-field", CLICK,
                 {"control": "Search chats field", "point": point, "size": list(frame.size)})
        self.act("query-session", QUERY, {"thread": self.thread, "text": self.label,
                                          "control": "Search chats field"})
        time.sleep(1.4)
        self.frame("freebuff-search-results")

    def verify_lane(self, frame):
        self.require_foreground()
        self.yes("verify-lane1", frame,
                 "Is the navigation row labeled exactly Lane 1 visibly selected or highlighted "
                 "under the Harness heading? Reject if a different row is selected.",
                 region=LANE_NAV)

    def verify_draft(self, frame):
        region = (644, 949, 1040, 1010)
        try:
            self.locate_exact_text("read-exact-draft", frame, CONTINUATION, region)
        except RuntimeError as error:
            self.audit.append("extraction", step_id="read-exact-draft", ok=False, reason=str(error))
            time.sleep(0.4)  # A blinking caret can obscure the last OCR glyph.
            frame = self.frame("draft-ocr-retry")
            self.verify_lane(frame)
            self.locate_exact_text("read-exact-draft-retry", frame, CONTINUATION, region)
        self.yes("verify-staged-text", frame,
                 "Does the visible text read exactly 'continue in full'?",
                 region=region)
        return frame

    def send_draft(self):
        marker = self.output.parent / f"harness-freebuff-{THREAD}-send-20261122.json"
        if marker.exists():
            raise RuntimeError("the one-send marker already exists; inspect the prior outcome")
        frame = self.frame("lane1-before-send")
        self.verify_lane(frame)
        frame = self.verify_draft(frame)
        self.yes("verify-send-arrow", frame,
                 "Does this image show a white button containing a black upward arrow?",
                 region=SEND_CONTROL)
        left, top, _, _ = SEND_CONTROL
        crop = frame.crop(SEND_CONTROL).convert("L")
        box = crop.point(lambda level: 255 if level >= 205 else 0).getbbox()
        if box is None or not (26 <= box[2] - box[0] <= 47 and 26 <= box[3] - box[1] <= 47):
            raise RuntimeError("the verified Send button outline could not be located")
        point = [left + (box[0] + box[2]) // 2, top + (box[1] + box[3]) // 2]
        params = {"thread": THREAD, "text": CONTINUATION,
                  "control": "Lane 1 Send (up arrow)", "point": point, "size": list(frame.size)}
        with marker.open("x", encoding="utf-8") as handle:
            json.dump({"thread": THREAD, "step": "send-once", "text": CONTINUATION,
                       "evidence": self.output.name}, handle)
        self.act("send-once", SEND, params)
        options = {
            "running": "A stop square, Cancel, or active response/progress for the latest turn.",
            "refused": "An explicit platform error or usage-limit notice for the attempted send.",
            "idle": "An idle composer with no active response and no explicit error.",
            "unclear": "The response state is unclear.",
        }
        for observation, delay in enumerate((1.2, 2.0, 3.0), start=1):
            time.sleep(delay)
            frame = self.frame(f"platform-response-{observation}")
            try:
                state = self.choose(f"platform-state-{observation}", frame,
                                    "What does the visible FreeBuff pane show after the send?",
                                    options, region=(630, 520, 1550, 1115), threshold=0.8)
            except RuntimeError:
                continue
            if state in ("running", "refused"):
                print(f"Platform state: {state}")
                return
        raise RuntimeError("one send dispatched; the bounded observations did not prove running or refusal")

    def prepare_draft(self):
        frame = self.frame("lane1-before-draft")
        self.verify_lane(frame)
        route = self.choose("composer-route", frame,
                            "Read the controls in this composer screenshot. Which is visible?", {
                                "staged": "Solid lowercase text 'continue in full' with"
                                          " an up-arrow send button.",
                                "empty": "Dim suggestion text with a small visible Tab badge"
                                         " below it and a waveform icon at lower right.",
                                "resume": "A button labeled Resume mission.",
                                "stop": "A stop square, an unrelated draft, or no recognizable state.",
                            }, region=COMPOSER)
        if route == "staged":
            self.verify_draft(frame)
            return
        if route != "empty":
            raise RuntimeError(f"composer-route: stopped on {route!r} without typing")
        self.yes("verify-empty-editor", frame,
                 "Is there a small button or badge labeled Tab below the gray text?",
                 region=(642, 937, 1195, 1048))
        point = self.locate_exact_text("locate-tab-hint", frame, "Tab", (646, 1007, 707, 1051))
        point[1] -= 68
        self.act("focus-lane1-composer", CLICK,
                 {"control": "Lane 1 composer", "point": point, "size": list(frame.size)})
        self.act("type-continuation", TYPE, {"text": CONTINUATION})
        time.sleep(0.4)
        frame = self.frame("lane1-draft-ready")
        self.verify_draft(frame)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--phase", choices=("open", "search", "query", "prepare", "send"),
                        default="open")
    parser.add_argument("--thread", choices=tuple(SESSIONS), default=THREAD)
    args = parser.parse_args()
    key = os.environ.pop("TYPESAFE_API_KEY", "")
    if not key:
        parser.error("the trusted child needs the existing TypeSafe key")
    args.evidence.mkdir()
    dispatch = Dispatch(args.evidence, key, thread=args.thread)
    try:
        if args.phase == "open":
            if args.thread != THREAD:
                raise RuntimeError("use verified search for this session")
            dispatch.open_lane()
        elif args.phase == "search":
            dispatch.open_search()
        elif args.phase == "query":
            dispatch.search_for_session()
        elif args.phase == "prepare":
            if args.thread != THREAD:
                raise RuntimeError("the session composer must be scoped before preparing a draft")
            dispatch.prepare_draft()
        else:
            if args.thread != THREAD:
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
