"""HUL mission-scope evaluator owner (#309).

``harness/jev_policy.py`` keeps the ONE policy owner: when a typed call may
dispatch, its bounded spend, reservation and cancellation settlement, the
ledger event and the shared structural envelope. This module owns one domain
evaluator family -- the HUL-C mission scope gate -- so its inputs, its
determination and its fail-closed envelope change and review on their own.

The family receives the policy instance it runs under; it never imports
``harness.jev_policy`` at module scope, so the dependency stays one-way.
"""
from typing import Any, Callable, Dict, List, Optional

from .errors import HarnessError, ProviderUsageUnknown, ToolCancelled
from .jev import JevEvaluationResult
from .jev_packs import (
    HUL_SCOPE_SITE,
    SCOPE_COVERAGE_HOLD,
    SCOPE_NOUL_HOLD,
    hul_scope_question_pack,
    normalize_complexity_class,
    scope_in_scope_holds,
)
from .provider_errors import ProviderSpendLimitError


def scope_noul(answers: Dict[str, Any], key: str) -> Optional[float]:
    val = (answers or {}).get(key)
    if isinstance(val, dict) and "noul" in val:
        try:
            return float(val["noul"])
        except (TypeError, ValueError):
            return None
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return None
    return float(val)


def scope_score(answers: Dict[str, Any], key: str) -> Optional[float]:
    val = (answers or {}).get(key)
    if isinstance(val, dict) and "score" in val:
        try:
            return float(val["score"])
        except (TypeError, ValueError):
            return None
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return None
    return float(val)


def scope_choice(answers: Dict[str, Any], key: str) -> Optional[str]:
    val = (answers or {}).get(key)
    if isinstance(val, dict):
        return normalize_complexity_class(val.get("choice"))
    return normalize_complexity_class(val)


def scope_determination(
    *,
    verifier_holds: bool,
    success_met: Optional[float],
    coverage: Optional[float],
    claims: Optional[float],
    needs_human: Optional[float],
    complexity: Optional[str],
    is_fallback: bool,
    scope_declared: bool,
    reasons: List[str],
) -> Dict[str, Any]:
    """HUL-C determination: complete only when every hold is true.

    Unkeyed / fallback evaluations may NEVER alone mark complete.
    """
    success_ok = (
        success_met is not None
        and success_met >= SCOPE_NOUL_HOLD
        and not is_fallback
    )
    claims_ok = (
        claims is not None
        and claims >= SCOPE_NOUL_HOLD
        and not is_fallback
    )
    coverage_ok = (
        coverage is not None
        and coverage >= SCOPE_COVERAGE_HOLD
        and not is_fallback
    )
    human_clear = (
        needs_human is None
        or needs_human < SCOPE_NOUL_HOLD
    )
    scope_holds = bool(
        scope_declared and coverage_ok and claims_ok and human_clear
    )
    complete = bool(
        verifier_holds
        and success_ok
        and scope_holds
        and not is_fallback
    )
    out_reasons = list(reasons)
    if not scope_declared:
        out_reasons.append("missing scope.in_scope — cannot complete")
    if is_fallback:
        out_reasons.append(
            "unkeyed fallback cannot alone mark mission complete")
    if verifier_holds is False:
        out_reasons.append("verifier does not hold")
    if success_met is not None and success_met < SCOPE_NOUL_HOLD:
        out_reasons.append("success_definition_met is low")
    if claims is not None and claims < SCOPE_NOUL_HOLD:
        out_reasons.append("claims_supported is low")
    if coverage is not None and coverage < SCOPE_COVERAGE_HOLD:
        out_reasons.append("scope_coverage is low")
    if needs_human is not None and needs_human >= SCOPE_NOUL_HOLD:
        out_reasons.append("needs_human is true")
    return {
        "complete": complete,
        "verifier_holds": bool(verifier_holds),
        "success_definition_met": success_ok,
        "scope_holds": scope_holds,
        "scope_coverage": coverage,
        "claims_supported": claims,
        "needs_human": (
            None if needs_human is None
            else bool(needs_human >= SCOPE_NOUL_HOLD)),
        "complexity_class": complexity,
        "is_fallback": bool(is_fallback),
        "site": HUL_SCOPE_SITE,
        "reasons": out_reasons,
    }


def scope_text(state: Any) -> str:
    if isinstance(state, str):
        return state
    if isinstance(state, dict):
        for key in ("evidence_summary", "state_summary", "request",
                    "text", "prompt"):
            value = state.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""
    return "" if state is None else str(state)


def scope_state_facts(state: Any) -> Dict[str, Any]:
    if not isinstance(state, dict):
        return {
            "mission_id": None,
            "request": "",
            "success_definition": "",
            "scope": {"in_scope": [], "out_of_scope": []},
            "verifier_holds": False,
            "evidence_summary": scope_text(state),
        }
    scope = state.get("scope")
    if not isinstance(scope, dict):
        scope = {"in_scope": [], "out_of_scope": []}
    in_scope = scope.get("in_scope")
    out_scope = scope.get("out_of_scope")
    return {
        "mission_id": state.get("mission_id"),
        "request": str(state.get("request") or ""),
        "success_definition": str(state.get("success_definition") or ""),
        "scope": {
            "in_scope": list(in_scope) if isinstance(in_scope, (list, tuple)) else [],
            "out_of_scope": list(out_scope) if isinstance(out_scope, (list, tuple)) else [],
        },
        "verifier_holds": bool(state.get("verifier_holds", False)),
        "evidence_summary": scope_text(state),
    }


def evaluate_scope(policy, mission_state, *, site: str = HUL_SCOPE_SITE,
                   task_id: Optional[str] = None,
                   node_id: Optional[str] = None,
                   max_input_tokens: int,
                   refusal_reason: Callable[[Exception], str]):
    """HUL-C: mission scope gate via the ONE policy owner.

    Determination contract:
    - complete only if verifier_holds AND success_definition_met AND
      scope hold (declared in_scope + coverage + claims + no human block)
    - unkeyed / fallback may NOT alone mark complete
    - missing scope or low success → complete false
    - ledger gets one ``jev_eval``; mission packs store the same via
      ``mission_record.append_jev_eval`` (no second Jev client)

    Returns ``(result, structural, determination)``.
    """
    facts = scope_state_facts(mission_state)
    scope_declared = scope_in_scope_holds(facts["scope"])
    payload = {
        "mission_id": facts["mission_id"],
        "request": facts["request"],
        "success_definition": facts["success_definition"],
        "scope": facts["scope"],
        "evidence_summary": facts["evidence_summary"][:4000],
        "verifier_holds": facts["verifier_holds"],
    }
    questions = hul_scope_question_pack()

    if not policy.keyed:
        answers = {
            "scope_coverage": {"type": "score", "score": 0.0},
            "success_definition_met": {"type": "noul", "noul": 0.0},
            "claims_supported": {"type": "noul", "noul": 0.0},
            "needs_human": {"type": "noul", "noul": 0.0},
            "complexity_class": {"type": "choice", "choice": None},
        }
        determination = scope_determination(
            verifier_holds=facts["verifier_holds"],
            success_met=0.0,
            coverage=0.0,
            claims=0.0,
            needs_human=0.0,
            complexity=None,
            is_fallback=True,
            scope_declared=scope_declared,
            reasons=["unkeyed: scope pack not evaluated live"],
        )
        result = JevEvaluationResult(
            "fail" if not determination["complete"] else "pass",
            0.0, 0.0, answers, determination["reasons"],
            is_fallback=True, model=policy.evaluator.model,
            fallback_reason=("explicit_disable"
                             if getattr(policy.evaluator,
                                        "explicitly_disabled", False)
                             else "missing_key"))
        structural = policy._account(
            result, site=site, task_id=task_id, node_id=node_id)
        structural["determination"] = determination
        return result, structural, determination

    reservation = None
    try:
        reservation = policy._preflight(
            site=site, max_input_tokens=max_input_tokens)
        result = policy.evaluator.evaluate(payload, questions)
        answers = dict(result.answers or {}) if isinstance(result.answers, dict) else {}
        is_fallback = bool(result.is_fallback)
        coverage = scope_score(answers, "scope_coverage")
        success_met = scope_noul(answers, "success_definition_met")
        claims = scope_noul(answers, "claims_supported")
        needs_human = scope_noul(answers, "needs_human")
        complexity = scope_choice(answers, "complexity_class")
        if is_fallback:
            # Transport/fallback: never allow complete from unkeyed path.
            success_met = min(success_met, 0.0) if success_met is not None else 0.0
            coverage = min(coverage, 0.0) if coverage is not None else 0.0
            claims = min(claims, 0.0) if claims is not None else 0.0
        determination = scope_determination(
            verifier_holds=facts["verifier_holds"],
            success_met=success_met,
            coverage=coverage,
            claims=claims,
            needs_human=needs_human,
            complexity=complexity,
            is_fallback=is_fallback,
            scope_declared=scope_declared,
            reasons=list(result.reasons or []),
        )
        normalized = dict(answers)
        normalized["scope_coverage"] = coverage
        normalized["success_definition_met"] = success_met
        normalized["claims_supported"] = claims
        normalized["needs_human"] = determination["needs_human"]
        normalized["complexity_class"] = complexity
        normalized["determination"] = determination
        verdict = "pass" if determination["complete"] else "fail"
        supported = min(
            [x for x in (success_met, claims, coverage) if x is not None]
            or [0.0])
        result = JevEvaluationResult(
            verdict,
            float(result.confidence or 0.0),
            float(supported),
            normalized,
            determination["reasons"] or list(result.reasons or []),
            cost=result.cost,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            is_fallback=is_fallback,
            model=result.model,
            discarded=result.discarded,
            cache_hit=result.cache_hit,
            fallback_reason=result.fallback_reason)
        structural = policy._account(
            result, site=site, task_id=task_id, node_id=node_id,
            reservation=reservation)
        structural["determination"] = determination
        return result, structural, determination
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
        policy._release(reservation)
        determination = scope_determination(
            verifier_holds=facts["verifier_holds"],
            success_met=0.0,
            coverage=0.0,
            claims=0.0,
            needs_human=0.0,
            complexity=None,
            is_fallback=True,
            scope_declared=scope_declared,
            reasons=[str(exc), "scope evaluation failed closed"],
        )
        fallback = JevEvaluationResult(
            "fail", 0.0, 0.0, {}, determination["reasons"],
            is_fallback=True, model=policy.evaluator.model,
            fallback_reason=refusal_reason(exc))
        structural = policy._account(fallback, site=site, task_id=task_id)
        structural["determination"] = determination
        structural["reason"] = str(exc)
        return fallback, structural, determination
