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
from driver_core.locate import parse_box
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
VOCABULARY = Vocabulary("windows-freebuff-dispatch", "1.0.0", [FOCUS, CLICK, TYPE])
CONTINUATION = "continue in full"
COMPOSER = (630, 918, 1550, 1110)
LANE_NAV = (80, 590, 390, 750)


class Dispatch:
    def __init__(self, output, key):
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
        self.composer_renderer = None
        self.audit = AuditLog(output / "driver.jsonl")
        self.screen = WindowsWindowScreen(self.window, source="windows-freebuff")
        self.driver = Driver(settings=Settings(jev_api_key=key, allow_write=True),
                             vocabulary=VOCABULARY, audit=self.audit)
        self.driver.register_executor(FOCUS.name, self.focus)
        self.driver.register_executor(CLICK.name, self.click)
        self.driver.register_executor(TYPE.name, self.type_text)

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
        if params["control"] == "Lane 1 composer":
            self.composer_renderer = hit

    def type_text(self, action, params):
        if params["text"] != CONTINUATION:
            raise RuntimeError("the text differs from the approved continuation")
        hit = self.composer_renderer
        for character in CONTINUATION:
            if not hit or self.user.GetAncestor(hit, 2) != self.require_foreground():
                raise RuntimeError("the verified composer renderer is no longer available")
            if not self.user.PostMessageW(hit, 0x0102, ord(character), 1):
                raise RuntimeError(f"renderer rejected a character (Win32 {ctypes.get_last_error()})")

    def act(self, step, action, params):
        grant = Consent(True, action.name, params, by="operator:freebuff-lane1")
        result = self.driver.executor.execute(action.name, params, consent=grant, step_id=step)
        if not result.ok:
            raise RuntimeError(f"{step}: {result.detail}")

    def frame(self, step):
        capture = self.screen.capture(Target("existing FreeBuff desktop", GUI))
        if self.screen.capture_seconds > 2:
            raise RuntimeError(f"{step}: capture exceeded 2s")
        (self.output / f"{step}.png").write_bytes(capture.payload)
        self.audit.append("capture", step_id=step, **capture.summary(),
                          foreground=self.window.api.foreground() == self.window.handle,
                          capture_seconds=self.screen.capture_seconds)
        return self.image.open(io.BytesIO(capture.payload)).convert("RGB")

    def ask(self, step, frame, questions, *, region=None):
        image = frame.crop(region) if region else frame
        data = io.BytesIO()
        image.save(data, format="PNG")
        fitted, why = osal.prepare_image_bytes(data.getvalue())
        if fitted is None:
            raise RuntimeError(f"{step}: {why}")
        assets = {"frame": {"type": "image", "format": "png",
                            "data_base64": base64.b64encode(fitted).decode("ascii")}}
        response = transport.call_service(
            SYSTEM_ONE_URL, questions, headers={"Authorization": f"Bearer {self.key}"},
            timeout=10, body_extra={"state": {"goal": GOAL, "screen": "frame"},
                                    "model": "jev-1.14.0"},
            assets=assets, images_enabled=True)
        if not response.ok:
            raise RuntimeError(f"{step}: {response.outcome}: {response.detail}")
        answers = response.payload["answers"]
        self.audit.append("decision", step_id=step, goal=GOAL, model=response.payload.get("model"),
                          answers=answers)
        canvas = osal.fit_target(*image.size)
        drawing = osal.fit_size(*image.size, *canvas)
        return answers, osal.ImageGeometry(*image.size, *canvas, *drawing)

    def yes(self, step, frame, question, *, region=None):
        answers, _ = self.ask(step, frame, {"yes": transport.noul(question)}, region=region)
        probability = answers.get("yes", {}).get("noul", 0)
        if not isinstance(probability, (int, float)) or not 0.9 <= probability <= 1:
            raise RuntimeError(f"{step}: Jev target confidence was {probability}, requires 0.90")

    def choose(self, step, frame, question, choices, *, region, threshold=0.9):
        answers, _ = self.ask(step, frame, {"choice": transport.choice(question, choices)},
                              region=region)
        choice = answers.get("choice", {})
        selected = choice.get("choice")
        probability = choice.get("probabilities", {}).get(selected, 0)
        if selected not in choices or not isinstance(probability, (int, float)):
            raise RuntimeError(f"{step}: malformed Jev choice")
        if not threshold <= probability <= 1:
            raise RuntimeError(f"{step}: Jev choice {selected!r} confidence was {probability}")
        return selected

    def locate(self, step, frame, label, region):
        answers, geometry = self.ask(step, frame, {
            "present": transport.noul(f"Is the exact {label} visible in the screenshot?"),
            "location": transport.box(f"Tight box around the exact {label} in `frame`."),
        }, region=region)
        present = answers.get("present", {}).get("noul", 0)
        raw, confidence = parse_box(answers.get("location"))
        if present < 0.9 or confidence is None or confidence < 0.6:
            raise RuntimeError(f"{step}: no confident {label} target")
        box = geometry.source_box(raw)
        if box is None:
            raise RuntimeError(f"{step}: Jev target was outside the captured region")
        left, top, right, bottom = region
        x = left + round((right - left) * (box["left"] + box["right"]) / 2)
        y = top + round((bottom - top) * (box["top"] + box["bottom"]) / 2)
        return [x, y]

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

    def verify_lane(self, frame):
        self.require_foreground()
        self.yes("verify-lane1", frame,
                 "Is the navigation row labeled exactly Lane 1 visibly selected or highlighted "
                 "under the Harness heading? Reject if a different row is selected.",
                 region=LANE_NAV)

    def verify_draft(self, frame):
        self.yes("verify-staged-text", frame,
                 "Is the only actual user-entered composer text exactly 'continue in full' "
                 "in lowercase, with no extra text, and is an enabled send button visible? "
                 "A gray Tab suggestion or placeholder does not count.",
                 region=COMPOSER)

    def prepare_draft(self):
        frame = self.frame("lane1-before-draft")
        self.verify_lane(frame)
        route = self.choose("composer-route", frame,
                            "Which exact state is visible in the existing Lane 1 pane?", {
                                "staged": "The composer already contains exactly the user-entered"
                                          " text 'continue in full' and an enabled send button.",
                                "empty": "The editor is empty with only a dim Tab suggestion"
                                         " and a microphone button. Resume mission is absent.",
                                "resume": "There is a Resume mission control.",
                                "stop": "A turn is active, there is other user-entered text,"
                                        " or the composer is unclear.",
                            }, region=(626, 633, 1550, 1110))
        if route == "staged":
            self.verify_draft(frame)
            return
        if route != "empty":
            raise RuntimeError(f"composer-route: stopped on {route!r} without typing")
        self.yes("verify-empty-editor", frame,
                 "Does this image show the text entry area of a message composer, "
                 "with a dim Tab suggestion and a white voice waveform button?",
                 region=COMPOSER)
        point = self.locate_exact_text("locate-tab-hint", frame, "Tab", (646, 1007, 707, 1051))
        point[1] -= 32
        self.act("focus-lane1-composer", CLICK,
                 {"control": "Lane 1 composer", "point": point, "size": list(frame.size)})
        self.act("type-continuation", TYPE, {"text": CONTINUATION})
        time.sleep(0.4)
        frame = self.frame("lane1-draft-ready")
        self.verify_draft(frame)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--phase", choices=("open", "prepare"), default="open")
    args = parser.parse_args()
    key = os.environ.pop("TYPESAFE_API_KEY", "")
    if not key:
        parser.error("the trusted child needs the existing TypeSafe key")
    args.evidence.mkdir()
    dispatch = Dispatch(args.evidence, key)
    try:
        if args.phase == "open":
            dispatch.open_lane()
        else:
            dispatch.prepare_draft()
    except (OSError, RuntimeError, KeyError, TypeError, ValueError) as error:
        dispatch.audit.append("escalation", step_id="dispatch", reason=str(error))
        print(f"BLOCKED: {error}")
        return 1
    print(json.dumps(dispatch.audit.verify().to_dict()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
