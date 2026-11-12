"""Governed project execution envelope (#458).

Harness can edit files and it can run one consented script, but it had no
governed way to *run a project* -- create a venv, install dependencies, run the
project's own test suite, iterate -- unattended in a user folder. Every existing
execution surface is scoped to something narrower and asks once per step, which
makes an unattended multi-command run impossible by construction.

This module is that one surface, and like the script lane its safety lives in
the runner rather than in a prompt:

* **One grant, scoped to a folder and a plan digest.** :class:`WorkspaceGrant`
  is taken at intake ("mutating actions inside this folder under this approved
  plan"), so file writes, provision steps and argv runs inside the folder need
  no second question. Anything resolved outside the folder still refuses, a
  plan that changed after approval has no matching digest and runs nothing, and
  an IRREVERSIBLE step keeps its own single-use approval.
* **An allowlisted argv executor.** :func:`governed_argv` admits only a
  declared set of interpreters and tools, refuses shell strings and shell
  metacharacters, and every command runs with ``cwd`` bound to the workspace
  through :func:`harness.osal.run_tree`, which gives the child its own process
  group and kills the whole tree on timeout.
* **A scrubbed environment.** The same allowlist the script lane uses -- PATH,
  HOME/TMP/locale and the Windows profile roots -- with provider keys and every
  other inherited variable dropped rather than filtered.
* **A run register.** Every command's argv, cwd, exit code and bounded output
  is appended to one JSONL register, so the evidence of an unattended run is
  the run itself, not a summary of it.
* **An envelope distinct from the per-edit caps.** Rounds, LLM budget and wall
  clock for a project run are their own settings; ``HARD_TASK_MAX_COST`` and
  ``MAX_APPLY_ROUNDS`` describe edits and are deliberately *not* reused here.
* **The project's own test gate.** :func:`discover_test_command` reads the
  declared command from the plan, then ``pyproject.toml`` / ``package.json`` /
  ``setup.cfg``; ``py_compile`` stays only as the last-resort fallback.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from . import osal
from .errors import HarnessError
from .script import scrubbed_child_env

#: Envelope defaults and hard caps. A project run is bigger than an edit but
#: still bounded: the caps are absolute, and a settings file or env var can
#: only move a value *inside* them, never past.
DEFAULT_PROJECT_ROUNDS = 12
DEFAULT_PROJECT_BUDGET_USD = 2.00
DEFAULT_PROJECT_WALL_CLOCK_S = 3600
HARD_PROJECT_ROUNDS = 40
HARD_PROJECT_BUDGET_USD = 25.00
HARD_PROJECT_WALL_CLOCK_S = 8 * 3600

#: Command output kept in the register (and shown to a caller) per stream.
DEFAULT_MAX_COMMAND_OUTPUT_BYTES = 65_536
MAX_COMMAND_OUTPUT_BYTES = 1_048_576

#: Interpreters and tools a project run may use. Names are compared on the
#: basename, so a venv's own ``python`` qualifies while an arbitrary program
#: does not. There is no wildcard and no escape hatch.
ALLOWED_PROGRAMS = frozenset({
    "python", "python3", "python3.9", "python3.10", "python3.11",
    "python3.12", "python3.13", "python3.14", "py",
    "pip", "pip3", "uv", "pytest", "tox", "nox",
    "node", "npm", "npx", "yarn", "pnpm",
    "cargo", "go", "make", "cmake",
})

#: Characters that only mean something to a shell. Refusing them keeps a step
#: from being a shell string in disguise; nothing here runs through a shell.
SHELL_METACHARACTERS = (";", "|", "&", ">", "<", "`", "$(", "\n", "\r")

READ = "read"
MUTATING = "mutating"
IRREVERSIBLE = "irreversible"
STEP_KINDS = (READ, MUTATING, IRREVERSIBLE)


class ProjectRunRefused(HarnessError):
    """A typed refusal from the one project-run owner.

    ``reason`` is machine-readable so the CLI, MCP and server never have to
    match prose to know why a step or a run was refused.
    """

    kind = "project_run_refused"

    def __init__(self, reason: str, message: str):
        super().__init__(f"project run refused: {message}")
        self.reason = str(reason)
        self.message = str(message)


def _refuse(reason: str, message: str) -> ProjectRunRefused:
    return ProjectRunRefused(reason, message)


def _bounded_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, parsed))


def _bounded_float(value: Any, default: float, low: float, high: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, parsed))


@dataclass(frozen=True)
class ProjectRunEnvelope:
    """Rounds, LLM budget and wall clock for one project run.

    Deliberately a different owner from the per-edit caps: a project run may
    legitimately take more rounds than ``MAX_APPLY_ROUNDS`` and spend more than
    ``HARD_TASK_MAX_COST``, while an edit task keeps its tighter ceiling. The
    hard caps here are absolute; a settings value can only trim them.
    """

    rounds: int = DEFAULT_PROJECT_ROUNDS
    budget_usd: float = DEFAULT_PROJECT_BUDGET_USD
    wall_clock_s: int = DEFAULT_PROJECT_WALL_CLOCK_S
    max_output_bytes: int = DEFAULT_MAX_COMMAND_OUTPUT_BYTES

    def __post_init__(self):
        # The hard caps are absolute, so a directly constructed envelope is
        # clamped exactly like a settings value: no caller can widen it.
        object.__setattr__(self, "rounds", _bounded_int(
            self.rounds, DEFAULT_PROJECT_ROUNDS, 1, HARD_PROJECT_ROUNDS))
        object.__setattr__(self, "budget_usd", _bounded_float(
            self.budget_usd, DEFAULT_PROJECT_BUDGET_USD, 0.0,
            HARD_PROJECT_BUDGET_USD))
        object.__setattr__(self, "wall_clock_s", _bounded_int(
            self.wall_clock_s, DEFAULT_PROJECT_WALL_CLOCK_S, 1,
            HARD_PROJECT_WALL_CLOCK_S))
        object.__setattr__(self, "max_output_bytes", _bounded_int(
            self.max_output_bytes, DEFAULT_MAX_COMMAND_OUTPUT_BYTES, 1_000,
            MAX_COMMAND_OUTPUT_BYTES))

    @classmethod
    def from_settings(cls, settings=None, environ: Optional[Dict[str, str]] = None,
                      ) -> "ProjectRunEnvelope":
        env = os.environ if environ is None else environ

        def pick(attr: str, var: str):
            value = getattr(settings, attr, None) if settings is not None else None
            return value if value is not None else env.get(var)

        return cls(
            rounds=_bounded_int(pick("project_rounds", "HARNESS_PROJECT_ROUNDS"),
                                DEFAULT_PROJECT_ROUNDS, 1, HARD_PROJECT_ROUNDS),
            budget_usd=_bounded_float(
                pick("project_budget_usd", "HARNESS_PROJECT_BUDGET_USD"),
                DEFAULT_PROJECT_BUDGET_USD, 0.0, HARD_PROJECT_BUDGET_USD),
            wall_clock_s=_bounded_int(
                pick("project_wall_clock_s", "HARNESS_PROJECT_WALL_CLOCK_S"),
                DEFAULT_PROJECT_WALL_CLOCK_S, 1, HARD_PROJECT_WALL_CLOCK_S),
            max_output_bytes=_bounded_int(
                pick("project_max_output_bytes",
                     "HARNESS_PROJECT_MAX_OUTPUT_BYTES"),
                DEFAULT_MAX_COMMAND_OUTPUT_BYTES, 1_000,
                MAX_COMMAND_OUTPUT_BYTES),
        )

    def as_dict(self) -> Dict[str, Any]:
        return {"rounds": self.rounds, "budget_usd": self.budget_usd,
                "wall_clock_s": self.wall_clock_s,
                "max_output_bytes": self.max_output_bytes}


class ProjectRunMeter:
    """The live counters an envelope is enforced through.

    Rounds, LLM spend and wall clock are checked here so a caller cannot run
    past the envelope by forgetting to ask. Command execution itself costs no
    LLM money; ``spend_usd`` is the project's model budget, kept separate from
    the per-edit task ceiling on purpose.
    """

    def __init__(self, envelope: ProjectRunEnvelope, clock: Callable[[], float] = None):
        self.envelope = envelope
        self.spend_usd = 0.0
        self.rounds_used = 0
        self._clock = clock or time.monotonic
        self._started = self._clock()

    @property
    def elapsed_s(self) -> float:
        return self._clock() - self._started

    def charge_llm(self, amount: float, *, label: str = "project") -> float:
        amount = max(0.0, float(amount or 0.0))
        if self.spend_usd + amount > self.envelope.budget_usd + 1e-12:
            raise _refuse(
                "budget_exhausted",
                f"charging ${amount:.6f} to {label} would take project spend to "
                f"${self.spend_usd + amount:.6f}, past the ${self.envelope.budget_usd:.6f} "
                "project budget")
        self.spend_usd += amount
        return self.spend_usd

    def next_round(self) -> int:
        if self.rounds_used + 1 > self.envelope.rounds:
            raise _refuse(
                "rounds_exhausted",
                f"this run already used {self.rounds_used} of "
                f"{self.envelope.rounds} rounds")
        self.rounds_used += 1
        return self.rounds_used

    def remaining_s(self) -> float:
        return max(0.0, self.envelope.wall_clock_s - self.elapsed_s)

    def check_wall_clock(self) -> float:
        remaining = self.remaining_s()
        if remaining <= 0:
            raise _refuse(
                "wall_clock_exhausted",
                f"the run used its {self.envelope.wall_clock_s}s wall clock")
        return remaining


def plan_digest(steps: Iterable["ProjectStep"]) -> str:
    """The consent handle for a project plan: sha256 over its canonical form."""
    body = json.dumps([step.canonical() for step in steps],
                      sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def step_digest(argv: Sequence[str]) -> str:
    body = json.dumps([str(a) for a in argv], separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ProjectStep:
    """One argv in a project run."""

    argv: Tuple[str, ...]
    kind: str = MUTATING
    timeout_s: int = 300
    label: str = ""

    def __post_init__(self):
        if self.kind not in STEP_KINDS:
            raise _refuse(
                "bad_step_kind",
                f"step kind must be one of {', '.join(STEP_KINDS)}, not {self.kind!r}")
        if not self.argv:
            raise _refuse("empty_argv", "a step needs at least one argument")

    def canonical(self) -> Dict[str, Any]:
        return {"argv": [str(a) for a in self.argv], "kind": self.kind,
                "timeout_s": int(self.timeout_s), "label": self.label}

    @property
    def digest(self) -> str:
        return step_digest(self.argv)


def governed_argv(argv: Sequence[str], *, root: Any) -> List[str]:
    """Admit one argv for ``root`` or refuse.

    The allowlist is the gate: a program outside :data:`ALLOWED_PROGRAMS` never
    runs, a shell string is refused (a string is a shell waiting to happen),
    shell metacharacters are refused, and every argument resolves against the
    workspace, so neither an absolute path nor a relative traversal can reach
    outside it.
    """
    if isinstance(argv, (str, bytes)):
        raise _refuse("shell_string",
                      "argv must be a list of arguments, not a command string")
    if not isinstance(argv, (list, tuple)) or not argv:
        raise _refuse("empty_argv", "argv must be a non-empty list")
    tokens = [str(a) for a in argv]
    for token in tokens:
        if any(char in token for char in SHELL_METACHARACTERS):
            raise _refuse(
                "shell_metacharacter",
                f"argument {token!r} carries a shell metacharacter; nothing here "
                "runs through a shell")
    program = os.path.basename(tokens[0]).lower()
    if program.endswith(".exe"):
        program = program[:-4]
    if program not in ALLOWED_PROGRAMS:
        raise _refuse(
            "program_not_allowed",
            f"{tokens[0]!r} is not an allowlisted interpreter or tool")
    workspace = Path(root).resolve()
    # Token 0 is the program, found on PATH or given as an absolute interpreter
    # (that is how a run bootstraps its own venv: ``<host python> -m venv
    # .venv``). Every other token is resolved against the workspace -- relative
    # tokens included, so ``../elsewhere`` cannot escape -- and refused when it
    # lands outside.
    for token in tokens[1:]:
        candidate = Path(token)
        if not candidate.is_absolute():
            candidate = workspace / candidate
        try:
            candidate.resolve().relative_to(workspace)
        except (ValueError, OSError):
            raise _refuse(
                "outside_workspace",
                f"{token!r} resolves outside the workspace {workspace}") from None
    return tokens


def command_env(root: Any) -> Dict[str, str]:
    """The scrubbed environment a project command runs with."""
    env = scrubbed_child_env()
    env["HARNESS_PROJECT_ROOT"] = str(Path(root).resolve())
    # Commands run from the workspace's own directory, so the workspace is what
    # a bare interpreter imports; the product is still importable from the
    # script lane's pinned path.
    env["PYTHONPATH"] = str(Path(root).resolve())
    # A bare host interpreter still honours this; without it it could import or
    # shadow dependencies from the operator's HOME instead of the workspace's
    # own venv, and the test gate would stop being deterministic.
    env["PYTHONNOUSERSITE"] = "1"
    return env


@dataclass
class WorkspaceGrant:
    """One intake approval, scoped to a folder and a plan digest.

    Inside the folder and on the digest, mutating steps and argv runs need no
    second question -- that is what makes an unattended run possible. Outside
    the folder, off the digest, or IRREVERSIBLE without its own approval, the
    grant covers nothing.
    """

    root: str
    digest: str
    approver: str = "operator"
    approved_irreversible: Tuple[str, ...] = ()

    def __post_init__(self):
        path = Path(self.root).resolve()
        if not path.is_dir():
            raise _refuse(
                "workspace_missing",
                f"the grant's workspace {path} is not an existing directory")
        self.root = str(path)
        self.digest = str(self.digest or "")
        self.approved_irreversible = tuple(self.approved_irreversible)

    def check_inside(self, path: Any) -> Path:
        """Resolve ``path`` (relative paths are workspace-relative) or refuse."""
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = Path(self.root) / candidate
        try:
            resolved = candidate.resolve()
            resolved.relative_to(Path(self.root))
        except (ValueError, OSError):
            raise _refuse(
                "outside_workspace",
                f"{path!r} resolves outside the granted workspace {self.root}") from None
        return resolved

    def require_digest(self, current: str) -> None:
        if not self.digest or str(current) != self.digest:
            raise _refuse(
                "digest_mismatch",
                "the plan changed after it was approved, so this grant covers "
                "nothing; approve the new plan digest")

    def authorize_step(self, step: ProjectStep) -> None:
        if step.kind == IRREVERSIBLE and step.digest not in self.approved_irreversible:
            raise _refuse(
                "irreversible_needs_approval",
                f"IRREVERSIBLE step {step.label or step.argv[0]!r} needs its own "
                "approval; a plan-level grant never covers it")

    def authorize_plan(self, steps: Iterable[ProjectStep]) -> None:
        """Check the whole plan before anything runs.

        An IRREVERSIBLE approval is single-use, so a plan that repeats the same
        irreversible argv needs one approval per occurrence; checking the
        quantities here refuses a plan that could only fail halfway.
        """
        needed: Dict[str, int] = {}
        for step in steps:
            if step.kind != IRREVERSIBLE:
                continue
            if step.digest not in self.approved_irreversible:
                raise _refuse(
                    "irreversible_needs_approval",
                    f"IRREVERSIBLE step {step.label or step.argv[0]!r} needs its "
                    "own approval; a plan-level grant never covers it")
            needed[step.digest] = needed.get(step.digest, 0) + 1
        for digest, count in needed.items():
            have = self.approved_irreversible.count(digest)
            if have < count:
                raise _refuse(
                    "irreversible_needs_approval",
                    "this plan runs one IRREVERSIBLE command "
                    f"{count} time(s) but only {have} single-use approval(s) exist")

    def consume_irreversible(self, step: ProjectStep) -> None:
        """Spend this step's single-use approval, or refuse."""
        if step.kind != IRREVERSIBLE:
            return
        try:
            index = self.approved_irreversible.index(step.digest)
        except ValueError:
            raise _refuse(
                "irreversible_needs_approval",
                f"the single-use approval for {step.label or step.argv[0]!r} was "
                "already spent") from None
        self.approved_irreversible = (self.approved_irreversible[:index]
                                      + self.approved_irreversible[index + 1:])

    def approve_irreversible(self, step: ProjectStep) -> "WorkspaceGrant":
        """Record the single-use approval for exactly this step's argv."""
        return WorkspaceGrant(self.root, self.digest, self.approver,
                              self.approved_irreversible + (step.digest,))


class RunRegister:
    """Append-only JSONL evidence for the commands a project run executed."""

    def __init__(self, path: Any):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, **entry: Any) -> Dict[str, Any]:
        row = dict(entry)
        row.setdefault("at", round(time.time(), 6))
        with open(self.path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        return row

    def entries(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        rows = []
        with open(self.path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows


@dataclass
class RunResult:
    """What one project run did."""

    status: str
    exit_code: int
    steps_run: int
    register_path: str
    elapsed_s: float
    failed_argv: Optional[List[str]] = None

    def as_dict(self) -> Dict[str, Any]:
        return {"status": self.status, "exit_code": self.exit_code,
                "steps_run": self.steps_run,
                "register_path": self.register_path,
                "elapsed_s": round(self.elapsed_s, 3),
                "failed_argv": self.failed_argv}


def _capped(text: Any, limit: int) -> str:
    value = "" if text is None else str(text)
    encoded = value.encode("utf-8", "replace")
    if len(encoded) <= limit:
        return value
    return encoded[:limit].decode("utf-8", "replace")


def run_project(steps: Sequence[ProjectStep], *, grant: WorkspaceGrant,
                envelope: Optional[ProjectRunEnvelope] = None,
                register_path: Optional[Any] = None,
                runner: Optional[Callable] = None,
                meter: Optional[ProjectRunMeter] = None,
                clock: Optional[Callable[[], float]] = None,
                ) -> RunResult:
    """Run an approved plan inside the granted workspace, unattended.

    Every command is admitted, executed with the workspace as cwd and the
    scrubbed environment, and recorded before the next one starts. A non-zero
    exit stops the run (the remaining steps are not executed) and is returned
    as a result, not raised: a failed test suite is evidence, not an exception.
    Refusals -- off-digest, outside the workspace, not allowlisted, past the
    envelope -- raise :class:`ProjectRunRefused` before anything runs.
    """
    steps = tuple(steps)
    clock = clock or time.monotonic
    runner = runner or osal.run_tree
    envelope = envelope or ProjectRunEnvelope.from_settings()
    meter = meter or ProjectRunMeter(envelope, clock=clock)

    grant.require_digest(plan_digest(steps))
    if len(steps) > envelope.rounds:
        raise _refuse(
            "rounds_exhausted",
            f"the plan has {len(steps)} steps and the envelope allows "
            f"{envelope.rounds} rounds")
    # Admission belongs to the whole plan, not to the first step: a plan that
    # cannot finish is refused before any command runs, never halfway through.
    admitted = [governed_argv(step.argv, root=grant.root) for step in steps]
    grant.authorize_plan(steps)

    target = (grant.check_inside(register_path) if register_path is not None
              else Path(grant.root) / ".harness" / "project-runs"
              / f"{uuid.uuid4().hex}.jsonl")
    register = RunRegister(target)
    register.record(kind="run_start", workspace=grant.root,
                    approver=grant.approver, digest=grant.digest,
                    envelope=envelope.as_dict(), steps=len(steps))

    started = clock()
    for index, (step, argv) in enumerate(zip(steps, admitted)):
        remaining = meter.check_wall_clock()
        meter.next_round()
        grant.consume_irreversible(step)
        timeout = float(min(int(step.timeout_s), max(1.0, remaining)))
        began = clock()
        outcome = runner(argv, cwd=grant.root, timeout=timeout,
                         env=command_env(grant.root))
        # osal.run_tree returns a CommandResult record; accept a plain
        # (code, stdout, stderr) triple too, so a caller can inject a runner.
        status = getattr(outcome, "returncode", None)
        if status is None:
            status, out, err = outcome
        else:
            out, err = outcome.stdout, outcome.stderr
        elapsed = round(clock() - began, 3)
        register.record(kind="step", label=step.label, argv=argv,
                        kind_of_step=step.kind, cwd=grant.root,
                        exit_code=int(status), timeout_s=timeout,
                        elapsed_s=elapsed,
                        stdout=_capped(out, envelope.max_output_bytes),
                        stderr=_capped(err, envelope.max_output_bytes))
        if int(status) != 0:
            register.record(kind="run_end", status="failed",
                            exit_code=int(status), argv=argv)
            return RunResult("failed", int(status), index + 1,
                             str(register.path), clock() - started, argv)

    register.record(kind="run_end", status="ok", exit_code=0)
    return RunResult("ok", 0, len(steps), str(register.path), clock() - started)


PYCOMPILE_FALLBACK_LIMIT = 20


def discover_test_command(root: Any, *, declared: Optional[Sequence[str]] = None,
                          ) -> Dict[str, Any]:
    """Find the gate a project run should end on.

    Order: the plan's own declared command, then the project's manifest
    (``pyproject.toml`` pytest options, ``setup.cfg`` pytest section,
    ``package.json`` test script), then ``py_compile`` over the discovered
    Python files as an honest last resort. ``fallback`` says which one answered.
    """
    workspace = Path(root).resolve()
    if declared:
        argv = governed_argv(declared, root=workspace)
        return {"argv": argv, "source": "declared", "fallback": False}

    pyproject = workspace / "pyproject.toml"
    if pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8", errors="replace")
        if "[tool.pytest.ini_options]" in text:
            return {"argv": ["python", "-m", "pytest", "-q"],
                    "source": "pyproject-pytest", "fallback": False}

    package_json = workspace / "package.json"
    if package_json.is_file():
        try:
            manifest = json.loads(package_json.read_text(
                encoding="utf-8", errors="replace"))
        except ValueError:
            manifest = {}
        scripts = manifest.get("scripts") if isinstance(manifest, dict) else None
        if isinstance(scripts, dict) and isinstance(scripts.get("test"), str):
            return {"argv": ["npm", "test"], "source": "package.json",
                    "fallback": False}

    setup_cfg = workspace / "setup.cfg"
    if setup_cfg.is_file():
        text = setup_cfg.read_text(encoding="utf-8", errors="replace")
        if "[tool:pytest]" in text:
            return {"argv": ["python", "-m", "pytest", "-q"],
                    "source": "setup.cfg", "fallback": False}

    python_files = sorted(
        path.name for path in workspace.glob("*.py"))[:PYCOMPILE_FALLBACK_LIMIT]
    if not python_files:
        raise _refuse(
            "no_test_gate",
            f"no declared command, no test manifest and no Python files under "
            f"{workspace}; a project run needs a gate to end on")
    return {"argv": ["python", "-m", "py_compile"] + python_files,
            "source": "py_compile", "fallback": True}
