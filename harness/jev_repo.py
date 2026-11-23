"""Jev repo-summary evaluator owner (#309).

``harness/jev_policy.py`` keeps the ONE policy owner: when a typed call may
dispatch, its bounded spend, reservation and cancellation settlement, the
ledger event and the shared structural envelope. This module owns one domain
evaluator family -- judging ONE repo element against the operator repo pack
(JEV-P6) -- so its inputs, its 0-hallucination rules and its fail-closed
envelope change and review on their own.

The family receives the policy instance it runs under; it never imports
``harness.jev_policy`` at module scope, so the dependency stays one-way.
"""
from typing import Any, Callable, Dict, List, Optional

from .errors import HarnessError, ProviderUsageUnknown, ToolCancelled
from .jev import LOCAL_HEURISTIC_MODEL, JevEvaluationResult
from .jev_packs import (
    REPO_SUMMARY_SITE,
    heuristic_repo_axes,
    repo_summary_question_pack,
    validate_repo_summary_pack,
)
from .provider_errors import ProviderSpendLimitError


def repo_element_text(state: Any) -> str:
    """Bounded text view of one element state for keyword fallback."""
    if isinstance(state, str):
        return state[:1200]
    if not isinstance(state, dict):
        return str(state)[:1200]
    parts = [str(state.get("path") or ""), str(state.get("kind") or ""),
             str(state.get("summary") or ""),
             " ".join(str(s) for s in (state.get("symbols") or [])[:18]),
             " ".join(str(h) for h in (state.get("headings") or [])[:12])]
    if state.get("element_kind") == "symbol":
        parts.append(str(state.get("symbol") or ""))
        parts.append(str(state.get("module_summary") or ""))
    return " ".join(p for p in parts if p)[:1200]

def repo_judgment(pack_doc, axes, level, value, confidence, nouls, *,
                  is_fallback: bool, evidence,
                  axis_confidence=None) -> Dict[str, Any]:
    """The stable JEV-P6 judgment shape (declared ids or None only).

    ``axis_confidence`` carries each choice's distribution confidence
    (TypeSafe-derived) so consumers can tell a settled axis from a
    near-tie that the seat may flip run-to-run (measured non-zero on
    identical input; see the 2026-09-22 determinism probe).
    """
    pack_doc = pack_doc if isinstance(pack_doc, dict) else {}
    score_config = pack_doc.get("score")
    score = score_config if isinstance(score_config, dict) else {}
    return {
        "pack_id": pack_doc.get("id"),
        "axes": dict(axes or {}),
        "axis_confidence": {
            axis: (float(value)
                   if isinstance(value, (int, float))
                   and not isinstance(value, bool) else None)
            for axis, value in (axis_confidence or {}).items()},
        "attention": {"id": score.get("id"), "level": level,
                      "value": value, "confidence": confidence},
        "nouls": dict(nouls or {}),
        "is_fallback": bool(is_fallback),
        "evidence": list(evidence or []),
    }

def evaluate_repo_summary(policy, state, pack, *, site=REPO_SUMMARY_SITE,
                          task_id: Optional[str] = None,
                          node_id: Optional[str] = None,
                          max_input_tokens: int,
                          refusal_reason: Callable[[Exception], str]):
    """Judge ONE repo element against the operator repo pack (JEV-P6).

    0-hallucination contract (same class as ``evaluate_log_item``):
    - every axis value \u2208 operator criteria keys, else ``None`` -- an
      out-of-vocabulary choice is reported, never replaced by a guess;
    - ``attention.level`` \u2208 operator score levels (via the official
      legend), else ``None``; ``attention.value`` is the winning
      probability;
    - nouls ride as raw probabilities -- a low noul is an answer, not a
      parse failure, so verdict thresholds never discard classifications;
    - unkeyed / transport-fail / shape-invalid paths fall back to the
      code-owned keyword matcher (``keywords`` in the pack only);
    - ONE ledger ``jev_eval`` per call; ``structural.site=repo_summary``.
    Returns ``(result, structural, judgment)``.
    """
    text = repo_element_text(state)
    try:
        pack_doc = validate_repo_summary_pack(pack)
    except ValueError as exc:
        result = JevEvaluationResult(
            "fail", 0.0, 0.0, {}, [str(exc)], cost=0.0,
            input_tokens=0, output_tokens=0, is_fallback=True,
            model=policy.evaluator.model, fallback_reason="invalid_pack")
        structural = policy._account(
            result, site=site, task_id=task_id, node_id=node_id)
        judgment = repo_judgment(
            None, None, None, None, None, None,
            is_fallback=True, evidence=result.reasons)
        return result, structural, judgment

    axis_ids = {axis: set(spec["criteria"])
                for axis, spec in pack_doc["axes"].items()}
    level_ids = set(pack_doc["score"]["levels"])

    def fallback_judgment(reasons, *, model=None, cost=0.0,
                          input_tokens=0, output_tokens=0,
                          reservation=None, discarded=False,
                          reason=None):
        axes = heuristic_repo_axes(text, pack_doc)
        matched = any(v for v in axes.values())
        evidence = list(reasons or []) + [
            f"{axis}:{value}" for axis, value in sorted(axes.items())
            if value is not None]
        result = JevEvaluationResult(
            "pass" if matched else "fail", 0.0, 1.0 if matched else 0.0,
            {"axes": axes}, evidence,
            cost=cost, input_tokens=input_tokens,
            output_tokens=output_tokens, is_fallback=True,
            model=model or LOCAL_HEURISTIC_MODEL, discarded=discarded)
        result = policy._with_reason(result, reason, text)
        structural = policy._account(
            result, site=site, task_id=task_id, node_id=node_id,
            reservation=reservation)
        judgment = repo_judgment(
            pack_doc, axes, None, None, None, None,
            is_fallback=True, evidence=evidence)
        return result, structural, judgment

    if not policy.keyed:
        return fallback_judgment(
            ["unkeyed: code-owned keyword fallback only"],
            reason=policy._no_key_reason())

    reservation = None
    try:
        questions = repo_summary_question_pack(pack_doc)
        payload = state if isinstance(state, dict) else {"item": str(state)}
        reservation = policy._preflight(
            site=site, max_input_tokens=max_input_tokens)
        result = policy.evaluator.evaluate(payload, questions)
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
        return fallback_judgment([str(exc)], reservation=reservation,
                                 reason=refusal_reason(exc))

    answers = result.answers if isinstance(result.answers, dict) else {}
    if result.is_fallback or not answers:
        # Transport fail or shape-invalid response: never present a
        # heuristic classification as a live one. ``discarded`` rides
        # through so the run can report the paid calls it could not use
        # (DF-JEV-3) instead of presenting them as clean fallback rows.
        return fallback_judgment(
            list(result.reasons or ["invalid TypeSafe response"]),
            model=result.model,
            cost=float(result.cost or 0.0),
            input_tokens=int(result.input_tokens or 0),
            output_tokens=int(result.output_tokens or 0),
            reservation=reservation,
            discarded=bool(result.discarded),
            reason=policy._fallback_reason_of(result, "invalid_answer"))

    axes: Dict[str, Optional[str]] = {}
    axis_confidence: Dict[str, Optional[float]] = {}
    evidence: List[str] = []
    for axis in pack_doc["axes"]:
        answer = answers.get(axis)
        choice = answer.get("choice") if isinstance(answer, dict) else None
        raw_axis_conf = (answer.get("confidence")
                         if isinstance(answer, dict) else None)
        axis_confidence[axis] = (
            float(raw_axis_conf)
            if isinstance(raw_axis_conf, (int, float))
            and not isinstance(raw_axis_conf, bool) else None)
        if isinstance(choice, str) and choice in axis_ids[axis]:
            axes[axis] = choice
            evidence.append(f"{axis}:{choice}")
        else:
            axes[axis] = None
            evidence.append(f"{axis}:unmatched")

    level = None
    value = None
    confidence = 0.0
    score_id = pack_doc["score"]["id"]
    score_answer = answers.get(score_id)
    if isinstance(score_answer, dict):
        probabilities = score_answer.get("probabilities")
        legend = score_answer.get("legend")
        if isinstance(probabilities, dict) and isinstance(legend, dict):
            for anchor, label in legend.items():
                if not isinstance(label, str) or label not in level_ids:
                    continue
                probability = probabilities.get(str(anchor))
                if isinstance(probability, (int, float)) and (
                        value is None or float(probability) > value):
                    level, value = label, float(probability)
        raw_confidence = score_answer.get("confidence")
        if isinstance(raw_confidence, (int, float)):
            confidence = float(raw_confidence)
    if level is None:
        evidence.append("attention:unmatched")

    nouls: Dict[str, Optional[float]] = {}
    for name in pack_doc["nouls"]:
        answer = answers.get(name)
        raw = answer.get("noul") if isinstance(answer, dict) else None
        nouls[name] = (float(raw)
                       if isinstance(raw, (int, float))
                       and not isinstance(raw, bool) else None)
        if nouls[name] is None:
            evidence.append(f"{name}:unmatched")

    if not any(v is not None for v in axes.values()) and level is None:
        return fallback_judgment(
            evidence + list(result.reasons or []), model=result.model,
            cost=float(result.cost or 0.0),
            input_tokens=int(result.input_tokens or 0),
            output_tokens=int(result.output_tokens or 0),
            reservation=reservation, discarded=bool(result.discarded),
            reason=policy._fallback_reason_of(result, "no_declared_axes"))

    structural = policy._account(
        result, site=site, task_id=task_id, node_id=node_id,
        reservation=reservation)
    judgment = repo_judgment(
        pack_doc, axes, level, value, confidence, nouls,
        is_fallback=False, evidence=evidence,
        axis_confidence=axis_confidence)
    return result, structural, judgment

