"""The planning stage's evidence concern (#308).

The waist used to own decomposition, consensus/confirmation, context intake,
stage budgeting **and** the evidence questions its planning loop asks in one
module. #308 assigns each concern a single owner; this module owns the
evidence side of planning and nothing else:

* the largest brief that fits a round's allowance (:func:`_curated_brief`),
* what that brief admits it could not represent or where it conflicts,
* the bounded evidence request built from those admissions,
* the one sufficiency judgment, asked through its declared dimension, and
* the bound a plan must satisfy before it may be emitted.

The loop that walks the allowance ladder stays with the waist
(:func:`harness.waist.run_planning`): it consumes these answers, it does not
re-derive them. Nothing here imports the waist, so an owner module can be
imported and tested on its own.
"""
from typing import Any, Dict, List

from .brief import (
    MAX_TOTAL_WINDOW_CHARS,
    build_brief,
    estimate_brief_tokens,
    render_brief,
)
from .dag import TaskDAG
from .errors import HarnessError
from .plan_contracts import MAX_EVIDENCE_QUESTIONS
from .plan_context import _WINDOW_SEARCH_FLOOR

#: A plan is accepted only if it validates AND stays inside this bound. The
#: number is declared here, not negotiated in a prompt.
DEFAULT_MAX_PLAN_NODES = 12


def _curated_brief(goal, files, *, reader, allowance_tokens):
    """The largest brief whose MEASURED token estimate fits the allowance.

    :func:`harness.brief.build_brief` estimates over the bytes it actually
    ships, so the fit is checked against the real number rather than a
    characters-per-token guess. A brief's size is monotone in its window
    budget, so the window is bisected down to the largest value that fits --
    which is the only way to get this right, because the estimate is
    dominated by the pack's own metadata (sources, coverage, rules) rather
    than by the window: a step sized from the token excess leaves the pack
    byte-identical until the window drops below the content, so a larger
    allowance can fail where a smaller one succeeded.

    ``None`` means no honest brief exists at any window -- the round defers
    rather than shipping a brief it cannot pay for.
    """
    def build(window):
        pack = build_brief(goal, files, reader=reader, max_total_chars=window)
        return pack, estimate_brief_tokens(pack)

    smallest, smallest_tokens = build(0)
    if smallest_tokens > allowance_tokens:
        return None, 0
    low, high = 0, MAX_TOTAL_WINDOW_CHARS
    best = smallest
    while high - low > _WINDOW_SEARCH_FLOOR:
        mid = (low + high) // 2
        pack, tokens = build(mid)
        if tokens <= allowance_tokens:
            low, best = mid, pack
        else:
            high = mid
    return best, low


def _unrepresented(pack) -> List[str]:
    """The brief's own admission of what it could not represent."""
    return list(pack.get("omitted") or [])


def _conflicts(pack) -> List[Dict[str, Any]]:
    return [c for c in (pack.get("conflicts") or []) if isinstance(c, dict)]


def _evidence_request(pack, *, max_items=MAX_EVIDENCE_QUESTIONS):
    """A BOUNDED request for the evidence the brief says it is missing."""
    items: List[Dict[str, Any]] = [
        {"source": path, "reason": "not represented in the brief"}
        for path in _unrepresented(pack)]
    for conflict in _conflicts(pack):
        items.append({
            "source": ", ".join(str(s) for s in conflict.get("source_ids") or []),
            "reason": str(conflict.get("description") or "declared conflict"),
        })
        if len(items) >= max_items:
            break
    return items[:max_items]


def _jev_sufficiency(jev_policy, goal, pack, *, site):
    """Ask the one declared dimension that owns 'is this enough to plan on?'.

    Returns ``(signals, native)``. A policy that fails, falls back, or
    answers out of vocabulary yields ``native=False`` with whatever signals it
    produced, and the caller reads that as "not sufficient". Composition never
    re-implements the judgment and never promotes a fallback to native.

    The signal names come from the pack that declared them, not from a local
    list, so a new dimension's vocabulary cannot drift from this reader.
    """
    from .jev_packs import HOURGLASS_STAGE_DIMENSIONS
    state = {
        "goal": goal,
        "represented_sources": len(
            ((pack.get("grounding") or {}).get("sources") or [])),
        "omitted": _unrepresented(pack),
        "conflicts": [c.get("description") for c in _conflicts(pack)],
        "brief_render": render_brief(pack),
    }
    _result, structural = jev_policy.evaluate_hourglass_stage(
        "plan_soundness", state, site=site)
    structural = structural or {}
    declared = HOURGLASS_STAGE_DIMENSIONS["plan_soundness"]["signals"]
    signals = {name: structural.get(name) for name in declared
               if structural.get(name) is not None}
    return signals, bool(structural.get("native"))


def _validated_plan(plan_data, *, max_nodes=DEFAULT_MAX_PLAN_NODES):
    """A plan is accepted only if it validates AND stays inside its bound."""
    dag = plan_data if isinstance(plan_data, TaskDAG) else TaskDAG.from_dict(
        plan_data)
    count = len(dag.nodes)
    if count == 0:
        raise HarnessError("a plan must declare at least one node")
    if count > max_nodes:
        raise HarnessError(
            "plan declares {0} node(s), over the bound of {1}"
            .format(count, max_nodes))
    return dag
