"""PRJ-2 project intake: one folder and one prompt become a set-up, run, judged project.

The GUI's intake pane posts here (``POST /api/intake``). Routing is the mode the
operator picked, never a keyword classifier: Build creates or targets the
folder, sets the project up (its own venv, its declared dependencies), runs its
own test gate under one workspace grant, and returns a verdict; Chat stays
conversation and executes nothing.

The setup plan is executed by :mod:`harness.project_run`, so the intake inherits
the governed envelope -- allowlisted argv, scrubbed environment, process-tree
timeouts, a JSONL register of every command -- instead of inventing a second
execution path.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .errors import HarnessError
from .osal import python_exe, venv_python
from .project_run import (
    ProjectRunEnvelope, ProjectRunRefused, ProjectStep, WorkspaceGrant,
    discover_test_command, plan_digest, run_project,
)

MODE_BUILD = "build"
MODE_CHAT = "chat"
MODES = (MODE_BUILD, MODE_CHAT)

#: A prompt is a build instruction, not a document dump; the cap is stated so
#: the refusal is actionable rather than mysterious.
MAX_PROMPT_CHARS = 20_000

#: Declared dependency files, in the order pip should read them.
REQUIREMENTS_FILES = ("requirements.txt", "requirements-dev.txt")


class IntakeRefused(HarnessError):
    """An intake request that cannot be admitted, with a stable reason code."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def _refuse(reason: str, message: str) -> IntakeRefused:
    return IntakeRefused(reason, message)


@dataclass(frozen=True)
class IntakeRequest:
    """One intake: a target folder, a prompt, and the operator's chosen mode."""

    root: str
    prompt: str
    mode: str = MODE_BUILD
    create: bool = False
    test_command: Tuple[str, ...] = ()
    offline_wheels: Optional[str] = None

    def __post_init__(self):
        mode = str(self.mode or MODE_BUILD).strip().lower()
        if mode not in MODES:
            raise _refuse(
                "bad_mode",
                f"intake mode must be one of {', '.join(MODES)}, not {mode!r}")
        object.__setattr__(self, "mode", mode)

        prompt = str(self.prompt or "").strip()
        if not prompt:
            raise _refuse(
                "empty_prompt",
                "an intake needs a prompt; that prompt is the build instruction")
        if len(prompt) > MAX_PROMPT_CHARS:
            raise _refuse(
                "prompt_too_long",
                f"the prompt is {len(prompt)} characters; the intake takes at "
                f"most {MAX_PROMPT_CHARS}")
        object.__setattr__(self, "prompt", prompt)

        raw_root = str(self.root or "").strip()
        if not raw_root:
            raise _refuse("root_required",
                          "an intake needs the folder it works in")
        candidate = Path(raw_root)
        if not candidate.is_absolute():
            raise _refuse(
                "root_must_be_absolute",
                f"{raw_root!r} is not an absolute path; intake never guesses a "
                "project folder from the process directory")
        object.__setattr__(self, "root", str(candidate))
        object.__setattr__(self, "test_command",
                           tuple(self.test_command or ()))


def prepare_project(request: IntakeRequest) -> Path:
    """Resolve the intake's folder, creating it only when it was authorized."""
    path = Path(request.root)
    if path.exists():
        if not path.is_dir():
            raise _refuse("not_a_directory",
                          f"{path} exists and is not a directory")
        return path.resolve()
    if not request.create:
        raise _refuse(
            "folder_missing",
            f"{path} does not exist; ask for it to be created or pick another "
            "folder")
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def build_plan(root: Any, *, request: IntakeRequest,
               python: Optional[str] = None) -> List[ProjectStep]:
    """The project's setup plan: venv, declared dependencies, its test gate."""
    workspace = Path(root).resolve()
    python = python or python_exe()
    steps = [ProjectStep((python, "-m", "venv", ".venv"),
                         label="create the project venv")]
    interpreter = venv_python(workspace)
    for name in REQUIREMENTS_FILES:
        if not (workspace / name).is_file():
            continue
        argv = [interpreter, "-m", "pip", "install", "-r", name]
        if request.offline_wheels:
            argv += ["--no-index", "--find-links", request.offline_wheels]
        steps.append(ProjectStep(tuple(argv),
                                 label=f"install {name} into the project venv",
                                 timeout_s=900))
    gate = discover_test_command(workspace,
                                declared=request.test_command or None)
    argv = list(gate["argv"])
    if argv and os.path.basename(argv[0]).lower() in ("python", "python3"):
        argv[0] = interpreter
    steps.append(ProjectStep(tuple(argv),
                             label=f"run the project test gate ({gate['source']})",
                             timeout_s=900))
    return steps


def run_intake(request: IntakeRequest, *, python: Optional[str] = None,
               envelope: Optional[ProjectRunEnvelope] = None,
               register_path: Optional[Any] = None) -> Dict[str, Any]:
    """Admit one intake and, in Build mode, run it to a verdict.

    Chat mode routes to conversation and executes nothing -- not even a folder
    creation -- so the mode selector, not a keyword classifier, owns routing.
    """
    if request.mode == MODE_CHAT:
        return {"mode": MODE_CHAT, "routed": "chat", "executed": False,
                "root": request.root, "prompt": request.prompt,
                "verdict": "chat", "plan": [], "register_path": None}

    workspace = prepare_project(request)
    steps = build_plan(workspace, request=request, python=python)
    gate = discover_test_command(workspace,
                                 declared=request.test_command or None)
    grant = WorkspaceGrant(str(workspace), plan_digest(steps))
    try:
        result = run_project(steps, grant=grant,
                             envelope=envelope,
                             register_path=register_path)
    except ProjectRunRefused as exc:
        raise IntakeRefused(
            getattr(exc, "reason", "run_refused"),
            f"the project run was refused: {exc}") from None
    return {
        "mode": MODE_BUILD,
        "routed": "build",
        "executed": True,
        "root": str(workspace),
        "prompt": request.prompt,
        "verdict": "passed" if result.status == "ok" else "failed",
        "exit_code": result.exit_code,
        "steps_run": result.steps_run,
        "register_path": result.register_path,
        "gate": gate,
        "plan": [{"label": step.label, "argv": list(step.argv),
                  "kind": step.kind} for step in steps],
    }
