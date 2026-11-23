"""Jev log-item evaluator owner (#309).

``harness/jev_policy.py`` keeps the ONE policy owner: when a typed call may
dispatch, its bounded spend, reservation and cancellation settlement, the
ledger event and the shared structural envelope. This module owns one domain
evaluator family -- the JEV-LOG audit of one log item against an operator log
pack -- so its inputs, its 0-hallucination rules and its fail-closed envelope
change and review on their own.

The family receives the policy instance it runs under; it never imports
``harness.jev_policy`` at module scope, so the dependency stays one-way.
"""
from typing import Any, Callable, Optional

from .errors import HarnessError, ProviderUsageUnknown, ToolCancelled
from .jev import JevEvaluationResult
from .jev_packs import (
    LOG_FACTOR_SITE,
    log_factor_question_pack,
    match_keywords,
    validate_log_pack,
)
from .provider_errors import ProviderSpendLimitError


def log_item_text(state: Any) -> str:
    """Text extraction for log items (accepts the ``item`` key)."""
    if isinstance(state, str):
        return state
    if isinstance(state, dict):
        for key in ("item", "text", "issue", "reason", "note"):
            value = state.get(key)
            if isinstance(value, str):
                return value
        return ""
    return "" if state is None else str(state)

def log_judgment(bucket_id, pack_doc, *, score_level=None,
                 score_value=None, score_confidence=0.0,
                 evidence=None, is_fallback, structural):
    """Bind the log judgment to pack fields only — never invent."""
    pack_doc = pack_doc or {}
    entry = (pack_doc.get("buckets") or {}).get(bucket_id) \
        if isinstance(bucket_id, str) else None
    if entry is None:
        bucket_id = None
    return {
        "bucket": bucket_id,
        "path_id": entry.get("path_id") if entry else None,
        "kind": entry.get("kind") if entry else None,
        "attention": entry.get("attention") if entry else None,
        "suggested_next_action": entry.get("suggested_next_action") if entry else None,
        "score": {
            "id": (pack_doc.get("score") or {}).get("id"),
            "level": score_level,
            "value": score_value,
            "confidence": float(score_confidence or 0.0),
        },
        "evidence_refs": list(evidence or []),
        "is_fallback": bool(is_fallback),
        "pack_id": pack_doc.get("id"),
        "structural": structural,
    }

def evaluate_log_item(policy, state, pack, *, site=LOG_FACTOR_SITE,
                      task_id: Optional[str] = None,
                      node_id: Optional[str] = None,
                      max_input_tokens: int,
                      refusal_reason: Callable[[Exception], str]):
    """Jev audit of one log item against an operator log pack (JEV-LOG).

    0-hallucination contract (same class as ``evaluate_issue_sort``):
    - ``bucket`` ∈ operator pack keys, else ``None`` — out-of-pack,
      unparseable, transport-failed, or unkeyed runs fall back to the
      code-owned keyword matcher against pack keywords only.
    - ``score.level`` ∈ operator score levels, else ``None`` — the live
      level is the declared level string with the highest probability.
    - ``path_id`` / ``suggested_next_action`` always come from the pack.
    - ONE ledger ``jev_eval`` per call; ``structural.site=log_factor``.
    Returns ``(result, structural, judgment)``.
    """
    text = log_item_text(state)
    try:
        pack_doc = validate_log_pack(pack)
    except ValueError as exc:
        result = JevEvaluationResult(
            "fail", 0.0, 0.0, {}, [str(exc)], cost=0.0,
            input_tokens=0, output_tokens=0, is_fallback=True,
            model=policy.evaluator.model, fallback_reason="invalid_pack")
        structural = policy._account(
            result, site=site, task_id=task_id, node_id=node_id)
        judgment = log_judgment(
            None, None, is_fallback=True, structural=structural,
            evidence=result.reasons)
        return result, structural, judgment

    def keyword_judgment(reasons, *, model=None, cost=0.0,
                         input_tokens=0, output_tokens=0,
                         reservation=None, reason=None):
        bucket_id, hits, evidence = match_keywords(text, pack_doc)
        evidence_refs = list(reasons or []) + list(evidence or [])
        if bucket_id:
            result = JevEvaluationResult(
                "pass", 0.0, 1.0,
                {"bucket": bucket_id},
                (reasons or ["keyword match against operator pack"]),
                cost=cost, input_tokens=input_tokens,
                output_tokens=output_tokens, is_fallback=True,
                model=model or policy.evaluator.model)
        else:
            result = JevEvaluationResult(
                "fail", 0.0, 0.0, {"bucket": None},
                (list(reasons or []) + ["no declared pack keyword match"]),
                cost=cost, input_tokens=input_tokens,
                output_tokens=output_tokens, is_fallback=True,
                model=model or policy.evaluator.model)
        result = policy._with_reason(result, reason, text)
        # ONE ledger jev_eval per evaluate_log_item call.
        structural = policy._account(
            result, site=site, task_id=task_id, node_id=node_id,
            reservation=reservation)
        judgment = log_judgment(
            bucket_id, pack_doc, is_fallback=True,
            structural=structural, evidence=evidence_refs)
        return result, structural, judgment

    if not policy.keyed:
        # Unkeyed: skip live; code-owned keyword match only.
        return keyword_judgment(["unkeyed: keyword match only"],
                                reason=policy._no_key_reason())

    reservation = None
    try:
        questions = log_factor_question_pack(pack_doc)
        reservation = policy._preflight(
            site=site, max_input_tokens=max_input_tokens)
        result = policy.evaluator.evaluate(
            {"item": text, "pack_id": pack_doc["id"]}, questions)
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
        return keyword_judgment([str(exc)], reservation=reservation,
                                reason=refusal_reason(exc))

    answers = result.answers if isinstance(result.answers, dict) else {}
    score_id = pack_doc["score"]["id"]
    bucket_ans = answers.get("bucket")
    choice = bucket_ans.get("choice") if isinstance(bucket_ans, dict) else None
    pack_ids = set(pack_doc["buckets"])
    declared = (not result.is_fallback
                and isinstance(choice, str)
                and choice in pack_ids)

    # Live score: the DECLARED level string (via the official legend:
    # anchors -> criteria strings) with the highest probability, else None.
    score_level = score_value = None
    score_conf = 0.0
    score_ans = answers.get(score_id)
    if not result.is_fallback and isinstance(score_ans, dict):
        probs = score_ans.get("probabilities")
        legend = score_ans.get("legend")
        pack_levels = set(pack_doc["score"]["levels"])
        if isinstance(probs, dict) and isinstance(legend, dict):
            for anchor, level in legend.items():
                if not isinstance(level, str) or level not in pack_levels:
                    continue
                prob = probs.get(str(anchor))
                if isinstance(prob, (int, float)) and (
                        score_value is None or float(prob) > score_value):
                    score_level, score_value = level, float(prob)
        raw_conf = score_ans.get("confidence")
        if isinstance(raw_conf, (int, float)):
            score_conf = float(raw_conf)

    if declared and result.verdict == "pass":
        structural = policy._account(
            result, site=site, task_id=task_id, node_id=node_id,
            reservation=reservation)
        judgment = log_judgment(
            choice, pack_doc, score_level=score_level,
            score_value=score_value, score_confidence=score_conf,
            evidence=list(result.reasons) + [f"choice:{choice}"],
            is_fallback=False, structural=structural)
        return result, structural, judgment

    # Out-of-pack / transport fail / fallback / unparseable: never invent
    # a bucket or a score level. Keyword match against the pack only.
    reasons = list(result.reasons) if result.reasons else []
    if isinstance(choice, str) and choice not in pack_ids:
        reasons = reasons + [f"out-of-pack choice refused: {choice!r}"]
    return keyword_judgment(
        reasons, model=result.model,
        cost=float(result.cost or 0.0),
        input_tokens=int(result.input_tokens or 0),
        output_tokens=int(result.output_tokens or 0),
        reservation=reservation,
        reason=policy._fallback_reason_of(result, "out_of_pack"))
