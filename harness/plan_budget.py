"""Composed plan budget envelope owner (#308).

Before the plan lane dispatches an execution it asks ONE question: does the
worst case of everything still unincurred fit the governor's remaining
allowance? This module owns that answer -- the node ceilings of the plan about
to run, the worst-case cost of each planning stage not yet incurred
(decompose, consensus, waist rounds), the plan's own ceiling, and the
fail-closed envelope returned when the composition does not fit.

The waist keeps the orchestration: ``compose_plan`` decides *when* to ask and
what a refusal means. The ladders stay in the waist (the lanes that pin
routing patch them there), so they are resolved at call time rather than bound
here.
"""
from typing import Any, Dict, Optional, Sequence

from .plan_contracts import MAX_WAIST_ROUNDS, WAIST_MAX_TOKENS

DECOMPOSE_MAX_TOKENS = 1024


def _call_worst_case(governor, model, max_tokens) -> float:
    """Worst-case dollar cost of ONE bounded chat call on ``model``.

    Completion-side only (prompt tokens are typically small relative to the
    pinned output budget for plan-lane calls). Free / unpriceable models
    contribute $0.0 -- the node ceilings still bind the run.
    """
    if governor is None or not model:
        return 0.0
    try:
        pricing = governor.fetch_pricing([model])
        _pp, cp = pricing[model]
    except Exception:
        return 0.0
    try:
        return max(0.0, float(max_tokens) * float(cp))
    except (TypeError, ValueError):
        return 0.0


def composed_worst_case(
    plan_result: Dict[str, Any],
    *,
    governor=None,
    decompose_llm: bool = False,
    confirm: bool = False,
    decompose_model: Optional[str] = None,
    frontier_model: Optional[str] = None,
    use_free: bool = True,
    allow_escalation: bool = False,
    plan_consensus: bool = False,
    incurred_stages: Optional[Sequence[str]] = None,
    planning_spent: Optional[float] = None,
) -> Dict[str, Any]:
    """Composed pyramid ceiling over remaining unincurred work (#346).

    ONE owner of the pre-execute worst-case budget. Stages listed in
    ``incurred_stages`` (``"decompose"``, ``"consensus"``, ``"waist"``) have
    already completed and deducted their actual/reserved cost from
    ``governor.remaining()``, so only not-yet-incurred future liability is
    compared against ``governor.remaining()``. Called before spend when a
    governor is present; if remaining liability exceeds
    ``governor.remaining()`` the plan lane REFUSES instead of dispatching
    into an unfunded pyramid.
    """
    # The ladders are patched on ``harness.waist`` by the lanes that pin
    # routing, so they are resolved at call time instead of bound here.
    from .waist import resolve_scout_ladder, resolve_waist_ladder

    node_ceiling = 0.0
    try:
        node_ceiling = float(plan_result.get("total_cost_ceiling") or 0.0)
    except (TypeError, ValueError):
        node_ceiling = 0.0
    if node_ceiling <= 0.0:
        for detail in plan_result.get("nodes") or ():
            if not isinstance(detail, dict):
                continue
            route = detail.get("route") if isinstance(detail.get("route"), dict) else {}
            try:
                node_ceiling += float(route.get("cost_ceiling") or detail.get("cost_ceiling") or 0.0)
            except (TypeError, ValueError):
                continue

    completed = set(incurred_stages or ())
    decompose_cost = 0.0
    waist_cost = 0.0
    consensus_cost = 0.0
    if governor is not None:
        if decompose_llm and "decompose" not in completed:
            model = decompose_model
            if not model:
                try:
                    model = resolve_scout_ladder(use_free=use_free,
                                                 custom_frontier=frontier_model)[0]
                except Exception:
                    model = None
            decompose_cost = _call_worst_case(governor, model, DECOMPOSE_MAX_TOKENS)
        if plan_consensus and "consensus" not in completed:
            model = decompose_model
            if not model:
                try:
                    model = resolve_scout_ladder(use_free=use_free,
                                                 custom_frontier=frontier_model)[0]
                except Exception:
                    model = None
            consensus_cost = _call_worst_case(governor, model, 256)
        if confirm and "waist" not in completed:
            try:
                ladder = resolve_waist_ladder(
                    use_free=use_free, custom_frontier=frontier_model,
                    allow_escalation=allow_escalation)
            except Exception:
                ladder = [frontier_model] if frontier_model else []
            # Worst-case: every ladder rung could be attempted across the
            # window-round budget before one lands.
            for rung in ladder[:4]:
                waist_cost += _call_worst_case(
                    governor, rung, WAIST_MAX_TOKENS * MAX_WAIST_ROUNDS)

    composed = round(node_ceiling + decompose_cost + waist_cost + consensus_cost, 6)
    remaining = None
    if governor is not None and callable(getattr(governor, "remaining", None)):
        try:
            remaining = float(governor.remaining())
        except Exception:
            remaining = None
    plan_ceiling = None
    if governor is not None and getattr(governor, "max_cost", None) is not None:
        try:
            plan_ceiling = round(float(governor.max_cost), 6)
        except (TypeError, ValueError):
            plan_ceiling = None
    envelope = {
        "composed_worst_case": composed,
        "node_ceiling": round(node_ceiling, 6),
        "decompose": round(decompose_cost, 6),
        "waist": round(waist_cost, 6),
        "consensus": round(consensus_cost, 6),
        "remaining": remaining,
        "plan_ceiling": plan_ceiling,
        "exceeds_remaining": (
            None if remaining is None else bool(composed > remaining + 1e-12)),
    }
    if planning_spent is not None:
        spent_val = round(max(0.0, float(planning_spent)), 6)
        envelope["planning_spent"] = spent_val
        envelope["all_in_worst_case"] = round(spent_val + composed, 6)
    return envelope


def _refuse_composed_ceiling(plan_result: Dict[str, Any], composed: Dict[str, Any]) -> Dict[str, Any]:
    """Fail-closed envelope when the composed pyramid ceiling cannot fit."""
    refused = dict(plan_result)
    refused["status"] = "refused"
    refused["composed_worst_case"] = composed
    reason = (
        f"composed worst-case ${composed['composed_worst_case']:.6f} exceeds "
        f"remaining budget ${composed['remaining']:.6f}")
    evidence = (
        f"nodes={composed['node_ceiling']:.6f} "
        f"decompose={composed['decompose']:.6f} "
        f"waist={composed['waist']:.6f} "
        f"consensus={composed['consensus']:.6f}")
    if composed.get("planning_spent") is not None:
        evidence += f" planning_spent={composed['planning_spent']:.6f}"
    refused["confirmation"] = {
        "verdict": "refused",
        "model": "composed-ceiling",
        "rounds": 0,
        "reason": reason,
        "evidence": evidence,
        "cost": 0.0,
    }
    return refused
