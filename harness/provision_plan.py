"""Provisioning vocabulary and the typed plan: the pure, side-effect-free seam.

This is the first slice of the ``#310`` split. ``harness/provision.py`` owned
seven concerns across different trust boundaries; the two with no side effects
at all move here, unchanged:

1. **vocabulary** -- the consent classes (``READ`` / ``MUTATING`` /
   ``IRREVERSIBLE``), the decision words, the run-outcome words, the event
   names, the limits, and the recipe ids. Constants only: importing this
   module runs no subprocess, reads no settings, and writes nothing.
2. **typed plan** (:class:`Step`, :class:`Plan`, the dict coercions and
   :func:`render_plan`) -- argv is data, never a command string; a plan's
   digest binds what would run to what may be approved.

:mod:`harness.provision` imports the names it needs from here, and so does
every other caller: this repository forbids re-export facades
(``tests/test_architecture.py``), so a module that renders a plan imports
``render_plan`` from its owner. The direction of the dependency is the point:
this module imports nothing from ``provision`` and must stay that way
(``tests/test_provision_split_310.py`` pins it).
"""
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

from . import osal
from .errors import HarnessError

# --------------------------------------------------------------------------
# vocabulary
# --------------------------------------------------------------------------

# Same values as ``driver_core.actions`` (a test pins the parity): the
# consent classes are one vocabulary, not two.
READ = "read_only"
MUTATING = "mutating"
IRREVERSIBLE = "irreversible"
CLASSES = (READ, MUTATING, IRREVERSIBLE)
_SEVERITY = {READ: 0, MUTATING: 1, IRREVERSIBLE: 2}

APPROVE = "approve"
DECLINE = "decline"
DEFER = "defer"
DECISIONS = (APPROVE, DECLINE, DEFER)

# Step / run outcome vocabulary.
COMPLETED = "completed"
FAILED = "failed"
DRY_RUN = "dry_run"
DECLINED = "declined"
DEFERRED = "deferred"
AWAITING_APPROVAL = "awaiting_approval"
SKIPPED = "skipped"
AUDIT_FAILED = "audit_failed"
ALREADY_DONE = "already_done"

PROVISION_EVENTS = ("offer", "provision_plan", "provision_approval",
                    "provision_step_start", "provision_step", "provision_end")

DEFAULT_STEP_TIMEOUT_S = 900
DEFAULT_MAX_STEPS = 24
DEFAULT_MAX_OUTPUT_CHARS = 8000
DEFAULT_MAX_ARGV = 64
DEFAULT_MAX_ARG_CHARS = 1024
DEFAULT_MAX_SPECS = 32
_PROBE_TIMEOUT_S = 10

PROBE_PACKAGE_MANAGERS = ("winget", "choco", "scoop", "apt", "brew", "pip", "npm")
_SYSTEM_MANAGERS = ("winget", "choco", "scoop", "apt", "brew")

# Recipes the planner can build; the ids are the Jev choice vocabulary.
RECIPE_VENV_PIP = "venv-pip"
RECIPE_NPM_PREFIX = "npm-prefix"
RECIPE_SYSTEM_PM = "system-pm"
RECIPE_INVENTORY = "inventory"
_RECIPE_DESCRIPTIONS = {
    RECIPE_VENV_PIP: ("private virtual environment inside the approved root; "
                      "wheels only; reversible by deleting the directory"),
    RECIPE_NPM_PREFIX: ("package install into a private prefix inside the "
                        "approved root with install scripts disabled; "
                        "reversible by deleting the directory"),
    RECIPE_SYSTEM_PM: ("system package-manager install; changes the host "
                       "outside the approved root"),
}


class ProvisionError(HarnessError):
    """A plan, step, or approval the provisioning core refuses.

    ``problems`` carries every defect found so a reviewer sees them all at
    once rather than fixing one per round trip.
    """
    kind = "provision_error"

    def __init__(self, message, problems=None):
        super().__init__(message)
        self.problems = list(problems or [])


# --------------------------------------------------------------------------
# typed plan
# --------------------------------------------------------------------------

_STEP_ID_RE = re.compile(r"[a-z0-9][a-z0-9_\-]{0,63}\Z")

# Characters that may repaint a terminal, forge a line, or reorder text.
_UNSAFE_CATEGORIES = frozenset(("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"))


def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode(osal.ENCODING)).hexdigest()


@dataclass(frozen=True)
class Step:
    """One argv-list action with its class, effect and way back.

    ``argv`` is data, never a command string: a string is refused at
    construction so a "shell waiting to happen" cannot even be represented.
    """

    id: str
    description: str
    argv: Tuple[str, ...]
    classification: str
    expected_effect: str
    rollback_hint: str = ""
    requires_network: bool = False
    cwd: Optional[str] = None

    def __post_init__(self):
        argv = self.argv
        if isinstance(argv, (str, bytes)):
            raise ProvisionError(
                f"step {self.id!r}: argv must be a list of arguments, not a "
                "shell string")
        if not isinstance(argv, (list, tuple)) or not argv:
            raise ProvisionError(f"step {self.id!r}: argv must be a non-empty list")
        for token in argv:
            if not isinstance(token, str) or not token:
                raise ProvisionError(
                    f"step {self.id!r}: every argv element must be a "
                    "non-empty string")
        object.__setattr__(self, "argv", tuple(argv))

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "description": self.description,
                "argv": list(self.argv), "classification": self.classification,
                "expected_effect": self.expected_effect,
                "rollback_hint": self.rollback_hint,
                "requires_network": self.requires_network, "cwd": self.cwd}

    def digest(self) -> str:
        return _sha256(_canon(self.to_dict()))


def step_from_dict(data: Any) -> Step:
    """Strict coercion of a proposed step (e.g. from JSON); refuses shape drift."""
    if not isinstance(data, Mapping):
        raise ProvisionError("a step must be an object")
    allowed = {"id", "description", "argv", "classification", "expected_effect",
               "rollback_hint", "requires_network", "cwd"}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ProvisionError(f"step has undeclared field(s): {unknown}")
    for required in ("id", "description", "argv", "classification",
                     "expected_effect"):
        if required not in data:
            raise ProvisionError(f"step is missing {required!r}")
    for text_field in ("id", "description", "classification", "expected_effect"):
        if not isinstance(data[text_field], str):
            raise ProvisionError(f"step {text_field!r} must be a string")
    rollback = data.get("rollback_hint", "")
    if not isinstance(rollback, str):
        raise ProvisionError("step 'rollback_hint' must be a string")
    network = data.get("requires_network", False)
    if not isinstance(network, bool):
        raise ProvisionError("step 'requires_network' must be a boolean")
    cwd = data.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        raise ProvisionError("step 'cwd' must be a string")
    return Step(data["id"], data["description"], data["argv"],
                data["classification"], data["expected_effect"], rollback,
                network, cwd)


@dataclass(frozen=True)
class Plan:
    """An ordered, reviewable setup plan. Approval binds to :attr:`digest`."""

    goal: str
    steps: Tuple[Step, ...]
    root: str
    recipe: str
    source: str
    is_fallback: bool
    notes: Tuple[str, ...] = ()
    review: Mapping[str, Any] = field(default_factory=dict)
    review_required: bool = False

    def __post_init__(self):
        object.__setattr__(self, "steps", tuple(self.steps))
        object.__setattr__(self, "notes", tuple(self.notes))

    @property
    def digest(self) -> str:
        """Content hash of what would run and how it may be approved.

        ``review_required`` is part of it: a plan flagged for per-step
        approval must not hash like its unflagged twin, or the flag could be
        dropped and the same approvals replayed. Who proposed the plan
        (``source``, notes) is provenance, not content.
        """
        return _sha256(_canon({
            "goal": self.goal, "root": self.root,
            "review_required": bool(self.review_required),
            "steps": [step.to_dict() for step in self.steps]}))

    def step(self, step_id: str) -> Step:
        for candidate in self.steps:
            if candidate.id == step_id:
                return candidate
        raise ProvisionError(f"plan has no step {step_id!r}")

    def to_dict(self) -> Dict[str, Any]:
        return {"goal": self.goal, "root": self.root, "recipe": self.recipe,
                "source": self.source, "is_fallback": self.is_fallback,
                "digest": self.digest, "notes": list(self.notes),
                "review": dict(self.review),
                "review_required": self.review_required,
                "steps": [step.to_dict() for step in self.steps]}


def plan_from_dict(data: Any) -> Plan:
    """Rebuild a plan from JSON; the digest is recomputed, never trusted."""
    if not isinstance(data, Mapping):
        raise ProvisionError("a plan must be an object")
    steps = data.get("steps")
    if not isinstance(steps, (list, tuple)):
        raise ProvisionError("a plan requires a steps list")
    goal, root = data.get("goal"), data.get("root")
    if not isinstance(goal, str) or not isinstance(root, str):
        raise ProvisionError("a plan requires string goal and root")
    return Plan(goal, tuple(step_from_dict(s) for s in steps), root,
                str(data.get("recipe") or "external"),
                str(data.get("source") or "external"),
                bool(data.get("is_fallback", True)),
                tuple(str(n) for n in (data.get("notes") or ())),
                dict(data.get("review") or {}),
                # A missing or malformed flag is treated as "flagged": the
                # safe default forces per-step approval; only an explicit
                # boolean False clears it.
                True if not isinstance(data.get("review_required", True), bool)
                else data.get("review_required", True))


def _safe_text(value: Any) -> str:
    """Escape control, format, bidi, zero-width and line-break characters.

    A plan is shown to a human who approves it, so no field may be able to
    repaint the screen, forge a fake step, or visually reorder text.
    """
    out = []
    for ch in str(value):
        if unicodedata.category(ch) in _UNSAFE_CATEGORIES:
            out.append(ch.encode("unicode_escape").decode("ascii"))
        else:
            out.append(ch)
    return "".join(out)


def render_plan(plan: Plan) -> str:
    """The reviewable, human-readable form (what an approval card would show).

    Every field is escaped (:func:`_safe_text`) and each argv is shown as a
    JSON list, verbatim and unambiguous -- never re-joined into a string that
    could be read as a shell line.
    """
    lines = [f"Goal: {_safe_text(plan.goal)}",
             f"Recipe: {_safe_text(plan.recipe)} ({_safe_text(plan.source)}"
             + (", fallback" if plan.is_fallback else "") + ")",
             f"Root: {_safe_text(plan.root)}",
             "Review required: " + ("yes" if plan.review_required else "no"),
             f"Digest: {plan.digest}"]
    for index, step in enumerate(plan.steps, 1):
        net = " [network]" if step.requires_network else ""
        lines.append(f"{index}. [{_safe_text(step.classification)}]{net} "
                     f"{_safe_text(step.id)}: {_safe_text(step.description)}")
        lines.append("   argv: " + json.dumps(list(step.argv), ensure_ascii=True))
        lines.append(f"   effect: {_safe_text(step.expected_effect)}")
        if step.rollback_hint:
            lines.append(f"   rollback: {_safe_text(step.rollback_hint)}")
    for note in plan.notes:
        lines.append(f"note: {_safe_text(note)}")
    return "\n".join(lines)
