"""Run the consent-bound Windows Notepad vision proof in Harness."""

import argparse
import csv
import hashlib
import os
import time
from pathlib import Path

from driver_core import osal, policy
from driver_core.actions import DEFAULT_VOCABULARY, MUTATING, Action, Vocabulary
from driver_core.audit import AuditLog
from driver_core.config import Settings
from driver_core.driver import Driver
from driver_core.executor import Consent
from driver_core.vision_verify import APP_VISIBILITY_THRESHOLD, LAUNCH_POLLS, VisionVerifier

from .windows_notepad_window import NotepadScreen, NotepadWindow

TEXT = "hello world"
FILE_NAME = "vision-test.txt"
GOAL = "Open Notepad, type exactly hello world, and save Desktop\\vision-test.txt."
SAVE = Action("save_notepad", MUTATING, "save_notepad", ("destination",),
              "Save the captured Notepad document to the approved Desktop file.", "gui")
VOCABULARY = Vocabulary("windows-notepad-proof", "1.0.0", [
    *(DEFAULT_VOCABULARY.resolve(name) for name in ("no_action", "launch_app", "type_text")),
    SAVE,
])


def require_new_document():
    processes = osal.run(["tasklist.exe", "/FI", "IMAGENAME eq Notepad.exe", "/FO", "CSV", "/NH"])
    if not processes.ok:
        raise RuntimeError("could not check for an existing Notepad process")
    if any(row and row[0].casefold() == "notepad.exe"
           for row in csv.reader(processes.stdout.splitlines())):
        raise RuntimeError("an existing Notepad process could contain user work")


def wait_for_document(window):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            window.bind_foreground()
        except RuntimeError:
            time.sleep(0.1)
        else:
            return
    raise RuntimeError("Notepad did not become the foreground window within 5s")


def save_document(window, destination, params):
    window.require_foreground()
    if params["destination"] != f"Desktop\\{FILE_NAME}" or destination.exists():
        raise RuntimeError("the requested destination is unavailable")
    result = osal.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-File",
         str(Path(__file__).with_name("windows_notepad_save.ps1")),
         "-Window", str(window.owner), "-Destination", str(destination)],
        timeout=15,
    )
    if not result.ok:
        raise RuntimeError(result.error or result.stderr.strip().splitlines()[0])
    for _ in range(30):
        if destination.exists():
            if destination.read_bytes() != TEXT.encode("utf-8"):
                raise RuntimeError("saved file bytes differ from the exact requested text")
            return
        time.sleep(0.1)
    raise RuntimeError("Notepad did not create the requested Desktop file")


def decide_and_act(driver, goal, step, action, params, observed):
    state = {"goal": goal, **observed}
    driver.audit.append("capture", step_id=step, source="windows-notepad-proof", state=state)
    decision = driver.jev.decide(
        state, VOCABULARY, step_id=step, performable=(action, "no_action"))
    gate = policy.check_decision(decision, threshold=driver.settings.confidence_threshold)
    if not gate.passed or decision.recommended_action != action:
        raise RuntimeError(f"{step}: Jev decision refused ({gate.detail})")
    consent = Consent(True, action, params, by="operator:notepad-proof")
    result = driver.executor.execute(action, params, consent=consent, step_id=step)
    if not result.ok:
        raise RuntimeError(f"{step}: {result.detail}")


def prove(goal, output, destination, key):
    settings = Settings(
        jev_api_key=key, allow_write=True, launch_app_enabled=True,
        screen_enabled=True, vision_verify_enabled=True,
        run_ceiling_usd=0.01, step_ceiling_usd=0.002,
    )
    window = NotepadWindow()
    original_foreground = window.foreground()
    screen = NotepadScreen(window)
    audit = AuditLog(output / "driver.jsonl")

    def send(kind, *, value=None, target=None):
        window.type_text(value)
        return True, "sent character messages to the bound foreground Notepad control"

    send.supported_kinds = ("type",)
    driver = Driver(settings=settings, audit=audit, vocabulary=VOCABULARY, input_backend=send)
    driver.register_executor(
        "save_notepad", lambda action, params: save_document(window, destination, params))
    vision = VisionVerifier(settings, budget=driver.budget, audit=audit, source=screen)
    step = "launch"
    saved = False
    try:
        with driver.budget.step_scope(step):
            decide_and_act(driver, goal, step, "launch_app", {"app_name": "notepad"},
                           {"notepad_running": False, "stage": "before launch"})
            wait_for_document(window)
            opened = vision._verify_visibility(
                "application", "Is Notepad visible with a single blank untitled document "
                "and no blocking dialog, ready for text entry?",
                APP_VISIBILITY_THRESHOLD, step_id=step, polls=LAUNCH_POLLS)
            if not opened.passed:
                raise RuntimeError(opened.reason)

        step = "type"
        with driver.budget.step_scope(step):
            decide_and_act(driver, goal, step, "type_text", {"text": TEXT},
                           {"stage": "before typing", "blank_editor_verified": True})
            visible = vision.verify_text(TEXT, step_id=step)
            if not visible.passed:
                raise RuntimeError(visible.reason)
            evidence = screen.last_png
            (output / "notepad.png").write_bytes(evidence)
            audit.append("capture", step_id=step, source="windows-notepad",
                         sha256=hashlib.sha256(evidence).hexdigest())

        step = "save"
        with driver.budget.step_scope(step):
            decide_and_act(driver, goal, step, "save_notepad",
                           {"destination": f"Desktop\\{FILE_NAME}"},
                           {"stage": "before saving", "notepad_text_verified": TEXT})
            audit.append("verification", step_id=step, passed=True,
                         sha256=hashlib.sha256(TEXT.encode("utf-8")).hexdigest())
            saved = True
    except (OSError, RuntimeError) as error:
        audit.append("escalation", step_id=step, reason=str(error))
        print(f"FAIL {step}: {error}", flush=True)
    finally:
        window.release_foreground()
        restored = window.foreground() == original_foreground
        audit.append("verification", step_id="restore", passed=restored)
    chain = audit.verify()
    print(f"Audit: {chain.records} records, valid={chain.ok}, head={chain.head}")
    if not restored:
        print("FAIL restore: previous foreground window did not return")
    if saved and restored and chain.ok:
        print("PASS: exact Desktop file verified")
        return 0
    return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goal", required=True, choices=[GOAL])
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--desktop", required=True, type=Path)
    args = parser.parse_args()
    if osal.platform_name() != "windows":
        parser.error("the proof requires Windows")
    key = os.environ.pop("TYPESAFE_API_KEY", "")
    if not key:
        parser.error("the trusted child needs TYPESAFE_API_KEY")
    destination = args.desktop / FILE_NAME
    if not args.desktop.is_dir() or destination.exists():
        parser.error("the Desktop is unavailable or vision-test.txt already exists")
    try:
        require_new_document()
        args.evidence.mkdir()
    except (OSError, RuntimeError) as error:
        parser.error(str(error))
    return prove(args.goal, args.evidence, destination, key)


if __name__ == "__main__":
    raise SystemExit(main())
