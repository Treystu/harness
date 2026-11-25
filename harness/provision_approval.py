"""Provisioning approval gate: the consent record for a typed plan.

This is the second slice of the ``#310`` split. ``harness/provision.py`` owned
seven concerns across different trust boundaries; the approval gate (S5) is the
one that *persists* consent: it appends one ``provision_approval`` entry to the
ledger per decision and never executes anything. It moves here unchanged:

* :func:`_now` -- the single timestamp helper for a decision record.
* :class:`ApprovalRecord` -- one recorded decision, bound to the exact content
  it covers.
* :class:`ApprovalGate` -- who said yes, no, or not-now to what; approvals are
  bound to the plan's content digest (and, per step, the step's digest).

This module imports only from :mod:`harness.provision_plan` (the vocabulary and
typed plan) and the standard library. It does **not** import
:mod:`harness.provision`, must not import :mod:`harness.osal`, and never opens a
ledger of its own -- the ledger is always injected by the caller. The direction
of the dependency is the point: :mod:`harness.provision` imports
:class:`ApprovalGate` from here for its type hints, and every other caller
(``cli``, ``mcp``, tests) imports it from the owner. This repository forbids
re-export facades (``tests/test_architecture.py``), so a module that needs an
approval gate imports it from its owner.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from .provision_plan import (APPROVE, DECLINE, DECISIONS, DEFER, IRREVERSIBLE,
                            Plan, ProvisionError, Step)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class ApprovalRecord:
    """One recorded decision, bound to the exact content it covers."""

    decision: str
    scope: str
    plan_digest: str
    step_id: Optional[str]
    step_digest: Optional[str]
    approver: str
    reason: str
    ts: str

    def to_dict(self) -> Dict[str, Any]:
        return {"decision": self.decision, "scope": self.scope,
                "plan_digest": self.plan_digest, "step_id": self.step_id,
                "step_digest": self.step_digest, "approver": self.approver,
                "reason": self.reason, "ts": self.ts}


class ApprovalGate:
    """The record of who said yes, no, or not-now to what.

    Approvals are bound to the plan's content digest (and, per step, the
    step's digest), so a plan edited after approval simply has no matching
    record and nothing runs. A plan-level approve covers READ and MUTATING
    steps; an IRREVERSIBLE step needs its own step-level approve. Plan-level
    decline / defer is terminal until a later plan-level record replaces it.

    ``ask`` is the optional interactive path: ``ask(plan, step)`` returns
    ``(decision, reason)`` or ``None``. Anything malformed, or an exception,
    is recorded as a DEFER -- ambiguity never becomes consent.
    """

    def __init__(self, ledger=None, task_id: Optional[str] = None,
                 ask: Optional[Callable] = None, ask_approver: str = "interactive"):
        self.ledger = ledger
        self.task_id = task_id
        self.ask = ask
        self.ask_approver = ask_approver
        self._records: List[ApprovalRecord] = []

    @property
    def records(self) -> Tuple[ApprovalRecord, ...]:
        """Read-only view: callers add decisions only through :meth:`record`."""
        return tuple(self._records)

    def record(self, plan: Plan, decision: str, *, approver: str,
               step_id: Optional[str] = None, reason: str = "") -> ApprovalRecord:
        if decision not in DECISIONS:
            raise ProvisionError(
                f"decision {decision!r} is not one of {list(DECISIONS)}")
        if not isinstance(approver, str) or not approver.strip():
            raise ProvisionError("an approval needs a named approver")
        step = plan.step(step_id) if step_id is not None else None
        if (step is None and decision == APPROVE and plan.review_required):
            raise ProvisionError(
                "this plan was flagged by review: approve its steps one at a "
                "time instead of the whole plan")
        entry = ApprovalRecord(
            decision, "step" if step is not None else "plan", plan.digest,
            step.id if step is not None else None,
            step.digest() if step is not None else None,
            approver.strip(), str(reason or ""), _now())
        if self.ledger is not None:
            fields = entry.to_dict()
            # The ledger stamps its own ``ts``; keep the decision time apart.
            fields["decided_at"] = fields.pop("ts")
            # Ledger FIRST: if the evidence cannot be written, no approval
            # exists. A consent that was never recorded must not be usable.
            self.ledger.append("provision_approval", task_id=self.task_id,
                               **fields)
        self._records.append(entry)
        return entry

    def approve_plan(self, plan, approver, reason=""):
        return self.record(plan, APPROVE, approver=approver, reason=reason)

    def decline_plan(self, plan, approver, reason=""):
        return self.record(plan, DECLINE, approver=approver, reason=reason)

    def defer_plan(self, plan, approver, reason=""):
        return self.record(plan, DEFER, approver=approver, reason=reason)

    def approve_step(self, plan, step_id, approver, reason=""):
        return self.record(plan, APPROVE, approver=approver,
                           step_id=step_id, reason=reason)

    def decline_step(self, plan, step_id, approver, reason=""):
        return self.record(plan, DECLINE, approver=approver,
                           step_id=step_id, reason=reason)

    def defer_step(self, plan, step_id, approver, reason=""):
        return self.record(plan, DEFER, approver=approver,
                           step_id=step_id, reason=reason)

    def resolve(self, plan: Plan, step: Step) -> Optional[ApprovalRecord]:
        """The decision that governs ``step`` now, or ``None`` (no consent)."""
        digest = plan.digest
        plan_level = None
        step_level = None
        for entry in self._records:
            if entry.plan_digest != digest:
                continue
            if entry.scope == "plan":
                plan_level = entry
            elif entry.step_id == step.id and entry.step_digest == step.digest():
                step_level = entry
        if plan_level is not None and plan_level.decision != APPROVE:
            return plan_level
        if step_level is not None:
            return step_level
        if plan_level is not None and step.classification != IRREVERSIBLE:
            return plan_level
        return None

    def resolve_or_ask(self, plan: Plan, step: Step) -> Optional[ApprovalRecord]:
        found = self.resolve(plan, step)
        if found is not None or self.ask is None:
            return found
        try:
            answer = self.ask(plan, step)
        except Exception as exc:
            return self.record(
                plan, DEFER, approver=self.ask_approver, step_id=step.id,
                reason=f"approval prompt failed: {type(exc).__name__}")
        if answer is None:
            return None
        try:
            decision, reason = answer
        except (TypeError, ValueError):
            decision, reason = None, "malformed approval answer"
        if decision not in DECISIONS:
            return self.record(
                plan, DEFER, approver=self.ask_approver, step_id=step.id,
                reason=reason if decision is None else
                f"unrecognised decision {decision!r}")
        return self.record(plan, decision, approver=self.ask_approver,
                           step_id=step.id, reason=str(reason or ""))
