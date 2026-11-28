"""Jev model-route evaluator owner (#309).

``harness/jev_policy.py`` keeps the ONE policy owner: when a typed call may
dispatch, its bounded spend, reservation and cancellation settlement, the
ledger event and the shared structural envelope. This module owns one domain
evaluator family -- routing a query onto the declared model ladder (SITE-2)
-- so its inputs, its 0-hallucination rules and its fail-closed envelope
change and review on their own. Lane choice stays in ``evaluate_route``; this
family chooses the cheapest capable DECLARED rung.

The family receives the policy instance it runs under; it never imports
``harness.jev_policy`` at module scope, so the dependency stays one-way.
"""
from dataclasses import replace
from typing import Any, Callable, Optional

from .errors import HarnessError, ProviderUsageUnknown, ToolCancelled
from .jev import JevEvaluationResult, _digest
from .provider_errors import ProviderSpendLimitError
from .route_pack import (ROUTE_QUERY_SITE, choose_rung_for_tier, fallback_route,
                         route_combo, route_question_pack,
                         tier_floor_for_goal, tier_rank, validate_route_pack)

# Below this a live in-ladder answer is discarded even though it parsed: it is
# a coin flip, not an answer.
LOW_CONFIDENCE_FLOOR = 0.05


def route_query_text(state: Any) -> str:
    """Text extraction for route queries (accepts the ``goal`` key)."""
    if isinstance(state, str):
        return state
    if isinstance(state, dict):
        for key in ("goal", "query", "prompt", "issue", "text"):
            value = state.get(key)
            if isinstance(value, str):
                return value
        return ""
    return "" if state is None else str(state)

def evaluate_model_route(policy, state, pack, *, site: str = ROUTE_QUERY_SITE,
                         task_id: Optional[str] = None,
                         node_id: Optional[str] = None,
                         max_input_tokens: int,
                         refusal_reason: Callable[[Exception], str]):
    """Route a user query onto the declared model ladder (SITE-2).

    0-hallucination contract (same class as ``evaluate_issue_sort``):
    - choice criteria = declared rung ids only (via ``route_pack``);
      ``_parse_answer`` already requires choice ∈ criteria.
    - unkeyed / transport fail / out-of-ladder → the code-owned tier
      heuristic answers with ``is_fallback=True``; no rung is invented.
    - ladder cannot satisfy the heuristic floor → ``rung_id=None`` (the
      honest "no declared rung can do this" answer).
    - ONE ledger ``jev_eval`` per call; ``structural.site=model_route``.
    - a live in-ladder choice below ``min_confidence`` is still honored
      when it is escalation-safe: the final rung is never cheaper than the
      heuristic floor (``max(jev rung, floor)``), the combo stays
      ``is_fallback=False`` and its reasons record the confidence. The
      global ``min_confidence`` is not touched, so no other site changes.
    Extends (never modifies) ``evaluate_route``: lane choice stays there;
    this method chooses the cheapest capable DECLARED rung.
    Returns ``(result, structural, combo)``.
    """
    goal_text = route_query_text(state)

    try:
        pack_doc = validate_route_pack(pack)
    except ValueError as exc:
        result = JevEvaluationResult(
            "fail", 0.0, 0.0, {}, [str(exc)], cost=0.0,
            input_tokens=0, output_tokens=0, is_fallback=True,
            model=policy.evaluator.model, fallback_reason="invalid_pack")
        structural = policy._account(
            result, site=site, task_id=task_id, node_id=node_id)
        combo = route_combo(
            None, None, tier=None, reasons=[str(exc)],
            is_fallback=True, structural=structural)
        return result, structural, combo

    def heuristic_route(reasons, reason, *, model=None, cost=0.0,
                        input_tokens=0, output_tokens=0,
                        reservation=None, live_confidence=0.0,
                        discarded=False, state_hash=None):
        rung_id, tier, fb_reasons = fallback_route(goal_text, pack_doc)
        # ``cost`` is what the provider really billed for a live call
        # whose answer was discarded; it is settled and ledgered as-is.
        result = JevEvaluationResult(
            "pass" if rung_id else "fail", 0.0, 1.0 if rung_id else 0.0,
            {"rung": rung_id, "tier": tier},
            list(reasons or []) + list(fb_reasons),
            cost=cost, input_tokens=input_tokens,
            output_tokens=output_tokens, is_fallback=True,
            model=model or policy.evaluator.model,
            discarded=bool(discarded or cost > 0.0),
            fallback_reason=reason,
            state_hash=state_hash or _digest(goal_text, pack_doc["id"]))
        # ONE ledger jev_eval per evaluate_model_route call.
        structural = policy._account(
            result, site=site, task_id=task_id, node_id=node_id,
            reservation=reservation)
        combo = route_combo(
            rung_id, pack_doc, tier=tier,
            reasons=list(result.reasons), confidence=live_confidence,
            is_fallback=True, structural=structural)
        return result, structural, combo

    if not policy.keyed:
        return heuristic_route(
            ["unkeyed: deterministic tier heuristic only"],
            policy._no_key_reason())

    reservation = None
    try:
        questions = route_question_pack(pack_doc)
        reservation = policy._preflight(
            site=site, max_input_tokens=max_input_tokens)
        result = policy.evaluator.evaluate(
            {"goal": goal_text, "pack_id": pack_doc["id"]},
            questions)
    except ProviderUsageUnknown as exc:
        policy._settle_cancelled(reservation, exc)
        raise
    except ToolCancelled as exc:
        policy._settle_cancelled(reservation, exc)
        raise
    except ProviderSpendLimitError as exc:
        policy._release_after_provider_limit(reservation, exc, task_id=task_id)
        raise
    except HarnessError as exc:
        return heuristic_route(
            [str(exc)], refusal_reason(exc), reservation=reservation)

    answers = result.answers if isinstance(result.answers, dict) else {}
    rung_ans = answers.get("rung")
    choice = rung_ans.get("choice") if isinstance(rung_ans, dict) else None
    declared = {r["rung_id"] for r in pack_doc["rungs"]}
    in_ladder = (not result.is_fallback
                 and isinstance(choice, str)
                 and choice in declared)

    if in_ladder and result.verdict == "pass":
        structural = policy._account(
            result, site=site, task_id=task_id, node_id=node_id,
            reservation=reservation)
        entry = next(r for r in pack_doc["rungs"]
                     if r["rung_id"] == choice)
        combo = route_combo(
            choice, pack_doc, tier=entry["tier"],
            reasons=list(result.reasons or []) + [f"choice:{choice}"],
            confidence=result.confidence, is_fallback=False,
            structural=structural)
        return result, structural, combo

    min_confidence = float(getattr(policy.evaluator, "min_confidence", 0.70))
    live_confidence = float(result.confidence or 0.0)
    if (in_ladder and result.verdict == "fail"
            and LOW_CONFIDENCE_FLOOR <= live_confidence < min_confidence):
        # Confidence-aware acceptance: a declared rung chosen with low
        # confidence is still a real, in-vocabulary answer. Honor it only
        # when escalation-safe -- never cheaper than the heuristic floor.
        floor = tier_floor_for_goal(goal_text)
        entry = next(r for r in pack_doc["rungs"]
                     if r["rung_id"] == choice)
        final = (choice if tier_rank(entry["tier"]) >= tier_rank(floor)
                 else choose_rung_for_tier(pack_doc, floor))
        if final is not None:
            final_entry = next(r for r in pack_doc["rungs"]
                               if r["rung_id"] == final)
            reasons = list(result.reasons or []) + [
                f"choice:{final}",
                (f"low-confidence live choice {choice!r} accepted at "
                 f"confidence {live_confidence:.2f} < {min_confidence:.2f}"
                 f" (escalation-safe; heuristic floor {floor})")]
            if final != choice:
                reasons.append(
                    f"raised {choice!r} -> {final!r} to meet heuristic "
                    f"floor {floor}")
            result = replace(result, verdict="pass", reasons=reasons)
            structural = policy._account(
                result, site=site, task_id=task_id, node_id=node_id,
                reservation=reservation)
            combo = route_combo(
                final, pack_doc, tier=final_entry["tier"],
                reasons=list(reasons), confidence=live_confidence,
                is_fallback=False, structural=structural)
            return result, structural, combo

    # Out-of-ladder / transport fail / fallback / unparseable choice:
    # never invent a rung. Deterministic heuristic answers instead.
    reasons = list(result.reasons) if result.reasons else []
    if isinstance(choice, str) and choice not in declared:
        reasons = reasons + [
            f"out-of-ladder choice refused: {choice!r}"]
        default_reason = "route_out_of_vocabulary"
    elif in_ladder and live_confidence < LOW_CONFIDENCE_FLOOR:
        default_reason = "low_confidence"
        reasons = reasons + [
            f"live confidence {live_confidence:.2f} below the "
            f"{LOW_CONFIDENCE_FLOOR:.2f} floor; choice discarded"]
    elif in_ladder:
        default_reason = "below_floor_unsatisfiable"
    else:
        default_reason = "route_unanswered"
    return heuristic_route(
        reasons, policy._fallback_reason_of(result, default_reason),
        model=result.model,
        cost=float(result.cost or 0.0),
        input_tokens=int(result.input_tokens or 0),
        output_tokens=int(result.output_tokens or 0),
        reservation=reservation,
        live_confidence=live_confidence,
        discarded=bool(result.discarded),
        state_hash=result.state_hash)

