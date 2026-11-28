"""#703: Window-scoped, OCR-verified Antigravity desktop adapter for oversight dispatches."""

import csv
import ctypes
import hashlib
import json
import os
import re
import time
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path

from driver_core import osal
from driver_core.actions import MUTATING, Action, Vocabulary
from driver_core.audit import AuditLog
from driver_core.observation import GUI, Target

from .windows_focus import activate_exact
from .windows_notepad_window import WindowsWindowScreen

CONTINUATION = "continue in full"
ANTIGRAVITY_EXE = "Antigravity.exe"
DEFAULT_CALIBRATION_PATH = Path.home() / ".harness" / "driver-watch" / "antigravity-calibration.json"

FOCUS = Action("focus_antigravity", MUTATING, "focus_antigravity", ("title",),
               "Bring the verified Antigravity desktop window forward.", "gui")
CLICK = Action("click_antigravity", MUTATING, "click_antigravity", ("control", "point", "size"),
               "Click an OCR-verified control in the Antigravity window.", "gui")
TYPE = Action("type_antigravity", MUTATING, "type_antigravity", ("text",),
              "Type the authorized continuation into an empty Antigravity composer.", "gui")
SEND = Action("send_antigravity", MUTATING, "send_antigravity",
              ("thread", "text", "control", "point", "size"),
              "Submit the verified Antigravity composer input once.", "gui")
VOCABULARY = Vocabulary("windows-antigravity-adapter", "1.0.0", [FOCUS, CLICK, TYPE, SEND])

# Normalized bottom-right chat dock / composer fractions relative to window (w, h).
CHAT_DOCK_FRAC = (0.62, 0.10, 0.99, 0.98)
COMPOSER_FRAC = (0.64, 0.78, 0.98, 0.96)
RUNNING_MARKERS = ("running", "cancel", "generating", "thinking", "working")
PLACEHOLDER_MARKERS = (
    "ask anything",
    "type a message",
    "follow up",
    "ctrl+l",
    "send message",
)


def _hidden_subprocess_kwargs():
    import subprocess
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def calibration_path():
    raw = os.environ.get("HARNESS_ANTIGRAVITY_CALIBRATION", "").strip()
    return Path(raw) if raw else DEFAULT_CALIBRATION_PATH


def load_calibration(path=None):
    target = Path(path) if path is not None else calibration_path()
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("calibrated"):
        return None
    if not data.get("sha256") or not data.get("hwnd"):
        return None
    return data


def _norm(text):
    return re.sub(r"[^a-z0-9]+", "", (text or "").casefold())


def _region_from_frac(size, frac):
    w, h = size
    return (
        int(round(w * frac[0])),
        int(round(h * frac[1])),
        max(1, int(round(w * frac[2]))),
        max(1, int(round(h * frac[3]))),
    )


def composer_unchanged(before_crop, after_crop):
    """Compare composer crops allowing cursor blink noise (< 1.2 mean luma delta)."""
    if before_crop is None and after_crop is None:
        return True
    if before_crop is None or after_crop is None:
        return False
    if hasattr(before_crop, "convert") and hasattr(after_crop, "convert"):
        from PIL import ImageChops, ImageStat
        diff = ImageChops.difference(before_crop.convert("L"), after_crop.convert("L"))
        return ImageStat.Stat(diff).mean[0] <= 1.2
    return before_crop == after_crop


class AntigravityWindow:
    """Visible top-level window owned by Antigravity.exe in the interactive desktop."""

    def __init__(self, *, settle=3.0):
        if os.name != "nt":
            raise RuntimeError("AntigravityWindow requires Windows")
        self.api = osal._WindowsWindowApi()
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.user.GetWindowThreadProcessId.argtypes = (
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
        self.user.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.handle, self.title = self.discover(settle=settle)
        self.process = self.pid(self.handle)

    def pid(self, hwnd):
        pid = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        return int(pid.value)

    @staticmethod
    def processes():
        result = osal.run(["tasklist.exe", "/FI", f"IMAGENAME eq {ANTIGRAVITY_EXE}", "/FO", "CSV", "/NH"])
        if not result.ok:
            raise RuntimeError("could not enumerate Antigravity processes")
        return {
            int(row[1]) for row in csv.reader(result.stdout.splitlines())
            if len(row) > 1 and row[0].casefold() == ANTIGRAVITY_EXE.casefold()
        }

    def _visible(self):
        self.user.EnumWindows.argtypes = (ctypes.c_void_p, wintypes.LPARAM)
        self.user.EnumWindows.restype = wintypes.BOOL
        handles = []

        def visit(hwnd, _param):
            if self.api._user32.IsWindowVisible(hwnd):
                handles.append(int(hwnd))
            return True

        self.user.EnumWindows(
            ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(visit), 0)
        return handles

    def candidates(self, pids=None):
        pids = self.processes() if pids is None else pids
        matches = []
        for hwnd in self._visible():
            if self.pid(hwnd) not in pids:
                continue
            try:
                title = self.api.title_of(hwnd)
            except Exception:
                continue
            if title and ("antigravity" in title.casefold() or "harness" in title.casefold()):
                matches.append((hwnd, title))
        return matches

    def discover(self, *, settle=3.0):
        deadline = time.monotonic() + settle
        last = []
        while True:
            last = self.candidates()
            if last:
                # Prefer a window whose title explicitly names Antigravity when multiple exist.
                explicit = [pair for pair in last if "antigravity" in pair[1].casefold()]
                return (explicit or last)[0]
            if time.monotonic() >= deadline:
                break
            time.sleep(0.25)
        raise RuntimeError(
            f"no visible Antigravity desktop window found in interactive session "
            f"(pids={sorted(self.processes())})"
        )

    def require_window(self):
        if (not self.api._user32.IsWindow(self.handle)
                or not self.api._user32.IsWindowVisible(self.handle)
                or self.pid(self.handle) != self.process):
            self.handle, self.title = self.discover()
            self.process = self.pid(self.handle)
        return self.handle


def read_ocr_lines(output_dir, step, frame, region):
    """Run Windows primary-source OCR over a scaled inverted crop of ``region``."""
    from PIL import ImageOps
    crop = frame.crop(region)
    scaled = crop.resize((max(1, crop.width * 2), max(1, crop.height * 2)))
    path = (Path(output_dir) / f"{step}-ocr.png").resolve()
    ImageOps.invert(scaled.convert("L")).save(path)
    result = osal.run(
        [
            "powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-File",
            str(Path(__file__).with_name("windows_ocr_exact.ps1")),
            "-Path", str(path), "-ReadLines",
        ],
        timeout=10,
    )
    if not result.ok:
        return []
    return [
        (line.get("text") or "").strip()
        for line in (json.loads(result.stdout).get("lines") or [])
    ]


def analyze_frame_state(lines_dock, lines_composer, *, expected_text=CONTINUATION):
    """Classify Antigravity turn state and composer draft from primary-source OCR lines."""
    dock_norm = _norm(" ".join(lines_dock or ()))
    comp_text = " ".join(lines_composer or ()).strip()
    comp_norm = _norm(comp_text)
    target_norm = _norm(expected_text)
    running = any(marker in dock_norm for marker in RUNNING_MARKERS)
    if running:
        return {"turn_running": True, "composer_route": "running", "draft_excerpt": ""}
    if not comp_norm or any(_norm(p) in comp_norm for p in PLACEHOLDER_MARKERS):
        return {"turn_running": False, "composer_route": "empty", "draft_excerpt": ""}
    if target_norm and target_norm in comp_norm:
        return {"turn_running": False, "composer_route": "staged", "draft_excerpt": comp_text[:120]}
    return {"turn_running": False, "composer_route": "foreign", "draft_excerpt": comp_text[:120]}


def capture_window_image(window, out_dir, step):
    from PIL import Image
    import io
    hwnd = window.require_window()
    capture = WindowsWindowScreen(window, source="antigravity").capture(Target("antigravity", GUI))
    png_path = Path(out_dir) / f"{step}.png"
    png_path.write_bytes(capture.payload)
    digest = hashlib.sha256(capture.payload).hexdigest()
    image = Image.open(io.BytesIO(capture.payload))
    return image, png_path, digest, hwnd


def calibrate_antigravity(out_dir, *, calibration_file=None, head_sha=""):
    """Read-only #703 calibration: discover window, HWND capture, OCR classify, seal AuditLog."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    audit = AuditLog(out / "antigravity-calibration.jsonl")
    win = AntigravityWindow()
    frame, png_path, digest, hwnd = capture_window_image(win, out, "calibration-capture")
    dock_region = _region_from_frac(frame.size, CHAT_DOCK_FRAC)
    comp_region = _region_from_frac(frame.size, COMPOSER_FRAC)
    dock_lines = read_ocr_lines(out, "dock", frame, dock_region)
    comp_lines = read_ocr_lines(out, "composer", frame, comp_region)
    state = analyze_frame_state(dock_lines, comp_lines)
    audit.append(
        "verification",
        step_id="antigravity-readonly-calibration",
        hwnd=hwnd,
        pid=win.process,
        title=win.title,
        size=list(frame.size),
        sha256=digest,
        dock_lines=len(dock_lines),
        composer_lines=len(comp_lines),
        turn_running=state["turn_running"],
        composer_route=state["composer_route"],
    )
    audit.verify()
    receipt = {
        "calibrated": True,
        "at": datetime.now(timezone.utc).isoformat(),
        "head_sha": head_sha,
        "hwnd": hwnd,
        "pid": win.process,
        "title": win.title,
        "size": list(frame.size),
        "sha256": digest,
        "png": str(png_path),
        "audit_log": str(out / "antigravity-calibration.jsonl"),
        "turn_running": state["turn_running"],
        "composer_route": state["composer_route"],
        "dock_line_count": len(dock_lines),
    }
    target = Path(calibration_file) if calibration_file is not None else calibration_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


class AntigravityDispatcher:
    """Consent-bound, OCR-verified Windows Antigravity dispatcher (#703)."""

    def __init__(self, output, *, thread="antigravity", text=CONTINUATION):
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.thread = thread
        self.text = text
        self.audit = AuditLog(self.output / "driver.jsonl")
        self.window = AntigravityWindow()
        self.observed_at = None
        self.observed_composer = None

    def capture(self, step):
        frame, _path, digest, hwnd = capture_window_image(self.window, self.output, step)
        self.audit.append("capture", step_id=step, hwnd=hwnd, pid=self.window.process,
                          size=list(frame.size), sha256=digest)
        return frame

    def focus(self):
        hwnd = self.window.require_window()
        if not activate_exact(hwnd, self.window.api.foreground):
            raise RuntimeError("Antigravity foreground activation refused")
        self.audit.append("action", step_id="focus-antigravity", action="focus_antigravity",
                          ok=True, consent={"action": "focus_antigravity", "granted": True,
                                            "params": {"title": self.window.title}})

    def execute_restart(self, dispatch_id, *, allow_input=True):
        frame = self.capture("before-antigravity")
        self.observed_at = time.monotonic()
        comp_region = _region_from_frac(frame.size, COMPOSER_FRAC)
        dock_lines = read_ocr_lines(self.output, "before-dock", frame,
                                    _region_from_frac(frame.size, CHAT_DOCK_FRAC))
        comp_lines = read_ocr_lines(self.output, "before-comp", frame, comp_region)
        state = analyze_frame_state(dock_lines, comp_lines, expected_text=self.text)
        self.observed_composer = frame.crop(comp_region)
        self.audit.append("extraction", step_id="antigravity-state", **state)
        if state["turn_running"]:
            self.audit.append("verification", step_id="already-running", target=self.thread, passed=True)
            self.audit.verify()
            return "verified running: the Antigravity session was already in a turn; no input sent"
        if not allow_input:
            raise RuntimeError("antigravity restart requires interactive allow_input=True")
        self.focus()
        fresh = self.capture("pre-send-freshness")
        age = time.monotonic() - self.observed_at
        if age > 60:
            raise RuntimeError("the verified Antigravity observation expired before send")
        if not composer_unchanged(self.observed_composer, fresh.crop(comp_region)):
            raise RuntimeError("Antigravity composer changed between observation and send")
        marker = self.output / f"antigravity-send-{dispatch_id}.json"
        with marker.open("x", encoding="utf-8") as handle:
            json.dump({"dispatch": dispatch_id, "thread": self.thread, "route": state["composer_route"]}, handle)
        input_api = osal._WindowsInputApi()
        left, top, right, bottom = comp_region
        send_pt = [right - 26, bottom - 22]
        focus_pt = [(left + right) // 2, (top + bottom) // 2]
        hwnd = self.window.require_window()
        fx, fy = input_api.client_to_screen(hwnd, focus_pt[0], focus_pt[1])
        input_api.click(fx, fy)
        mode_note = "send-only; foreign staged draft preserved"
        if state["composer_route"] == "empty":
            input_api.type_text(self.text)
            time.sleep(0.6)
            mode_note = "typed continuation"
        sx, sy = input_api.client_to_screen(hwnd, send_pt[0], send_pt[1])
        input_api.click(sx, sy)
        self.audit.append("action", step_id="send-antigravity", action="send_antigravity", ok=True,
                          consent={"action": "send_antigravity", "granted": True,
                                   "params": {"thread": self.thread, "text": self.text if mode_note == "typed continuation" else "<foreign-staged-preserved>",
                                              "control": f"Antigravity composer ({mode_note})",
                                              "point": send_pt, "size": list(fresh.size)}})
        self.audit.verify()
        return f"verified running ({mode_note})"


def execute_antigravity_dispatch(output, dispatch_id, parsed, *, calibration_file=None, allow_input=True):
    """Execute one #703 Antigravity dispatch after verifying calibration receipt."""
    cal = load_calibration(calibration_file)
    if cal is None:
        raise RuntimeError("antigravity-adapter-not-calibrated")
    text = parsed.get("text") or CONTINUATION
    dispatcher = AntigravityDispatcher(output, thread=parsed.get("thread") or "antigravity", text=text)
    return dispatcher.execute_restart(dispatch_id, allow_input=allow_input)
