"""Jev issue-sort evaluator owner (#309).

``harness/jev_policy.py`` keeps the ONE policy owner: when a typed call may
dispatch, its bounded spend, reservation and cancellation settlement, the
ledger event and the shared structural envelope. This module owns one domain
evaluator family -- sorting an issue into an operator-declared bucket -- so its
inputs, its 0-hallucination rules and its fail-closed envelope change and
review on their own.

The family receives the policy instance it runs under; it never imports
``harness.jev_policy`` at module scope, so the dependency stays one-way.
"""
from typing import Any, Callable, Dict, Optional

from .errors import HarnessError, ProviderUsageUnknown, ToolCancelled
from .jev import JevEvaluationResult
from .jev_packs import (
    issue_sort_question_pack,
    match_keywords,
    validate_operator_pack,
)
from .provider_errors import ProviderSpendLimitError


def issue_sort_text(state: Any) -> str:
    if isinstance(state, str):
        return state
    if isinstance(state, dict):
        for key in ("issue", "text", "prompt", "note", "reason"):
            value = state.get(key)
            if isinstance(value, str):
                return value
        return ""
    return "" if state is None else str(state)


def issue_sort_empty_combo(*, is_fallback: bool = True,
                           structural: Optional[Dict[str, Any]] = None,
                           evidence=None,
                           pack_id: Optional[str] = None) -> Dict[str, Any]:
    return {
        "bucket": None,
        "path_id": None,
        "confidence": 0.0,
        "evidence_refs": list(evidence or []),
        "suggested_next_action": None,
        "is_fallback": bool(is_fallback),
        "pack_id": pack_id,
        "kind": None,
        "attention": None,
        "structural": structural,
    }


def issue_sort_combo(bucket_id, pack_doc, *, confidence, evidence,
                     is_fallback, structural) -> Dict[str, Any]:
    """Bind the combo to pack fields only -- never invent path/action."""
    pack_id = (pack_doc or {}).get("id")
    buckets = (pack_doc or {}).get("buckets") or {}
    entry = buckets.get(bucket_id) if bucket_id else None
    if not entry:
        combo = issue_sort_empty_combo(
            is_fallback=True, structural=structural, evidence=evidence,
            pack_id=pack_id)
        return combo
    return {
        "bucket": bucket_id,
        "path_id": entry["path_id"],
        "confidence": float(confidence or 0.0),
        "evidence_refs": list(evidence or []),
        "suggested_next_action": entry.get("suggested_next_action"),
        "is_fallback": bool(is_fallback),
        "pack_id": pack_id,
        "kind": entry["kind"],
        "attention": entry.get("attention"),
        "structural": structural,
    }


def evaluate_issue_sort(policy, state, pack, *, site: str = "issue_sort",
                        task_id: Optional[str] = None,
                        node_id: Optional[str] = None,
                        max_input_tokens: int,
                        refusal_reason: Callable[[Exception], str]):
    """Sort an issue into an operator-declared bucket (JEV-P5 owner).

    0-hallucination contract:
    - choice criteria = operator bucket labels only (via jev_packs);
      ``_parse_answer`` already requires choice \u2208 criteria.
    - unkeyed / transport fail / out-of-pack \u2192 ``is_fallback=true``;
      keyword match only against pack keywords.
    - no match \u2192 ``bucket=None``, ``path_id=None``.
    - ``suggested_next_action`` always equals ``pack[bucket]`` when set.
    ONE owner: this family + ``structural.site=issue_sort`` + one
    ledger ``jev_eval`` per call.
    Returns ``(result, structural, combo)``.
    """
    issue_text = issue_sort_text(state)

    try:
        pack_doc = validate_operator_pack(pack)
    except ValueError as exc:
        result = JevEvaluationResult(
            "fail", 0.0, 0.0, {}, [str(exc)], cost=0.0,
            input_tokens=0, output_tokens=0, is_fallback=True,
            model=policy.evaluator.model, fallback_reason="invalid_pack")
        structural = policy._account(
            result, site=site, task_id=task_id, node_id=node_id)
        combo = issue_sort_empty_combo(
            is_fallback=True, structural=structural,
            evidence=result.reasons)
        return result, structural, combo

    def local_result(bucket_id, score, evidence, reasons, *, model=None):
        evidence_refs = list(reasons or []) + list(evidence or [])
        if bucket_id:
            return JevEvaluationResult(
                "pass", 0.0, 1.0,
                {"bucket": bucket_id, "score": score},
                (reasons or ["keyword match against operator pack"]),
                is_fallback=True,
                model=model or policy.evaluator.model), evidence_refs
        return JevEvaluationResult(
            "fail", 0.0, 0.0, {"bucket": None},
            (list(reasons or []) + ["no declared pack keyword match"]),
            is_fallback=True,
            model=model or policy.evaluator.model), evidence_refs

    def keyword_sort(reasons, *, model=None, cost=0.0, input_tokens=0,
                     output_tokens=0, reservation=None, reason=None):
        bucket_id, score, evidence = match_keywords(issue_text, pack_doc)
        result, evidence_refs = local_result(
            bucket_id, score, evidence, reasons, model=model)
        if cost or input_tokens or output_tokens:
            result = JevEvaluationResult(
                result.verdict, result.confidence, result.supported,
                result.answers, result.reasons, cost=cost,
                input_tokens=input_tokens, output_tokens=output_tokens,
                is_fallback=True, model=result.model)
        result = policy._with_reason(result, reason, issue_text)
        # ONE ledger jev_eval per evaluate_issue_sort call.
        structural = policy._account(
            result, site=site, task_id=task_id, node_id=node_id,
            reservation=reservation)
        combo = issue_sort_combo(
            bucket_id, pack_doc, confidence=0.0, evidence=evidence_refs,
            is_fallback=True, structural=structural)
        return result, structural, combo

    if not policy.keyed:
        # Unkeyed: skip live; code-owned keyword match only.
        return keyword_sort(["unkeyed: keyword match only"],
                            reason=policy._no_key_reason())

    reservation = None
    try:
        questions = issue_sort_question_pack(pack_doc)
        reservation = policy._preflight(
            site=site, max_input_tokens=max_input_tokens)
        result = policy.evaluator.evaluate(
            {"issue": issue_text, "pack_id": pack_doc["id"]},
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
        return keyword_sort([str(exc)], reservation=reservation,
                            reason=refusal_reason(exc))

    answers = result.answers if isinstance(result.answers, dict) else {}
    bucket_ans = answers.get("bucket")
    choice = bucket_ans.get("choice") if isinstance(bucket_ans, dict) else None
    pack_ids = set(pack_doc["buckets"])
    declared = (not result.is_fallback
                and isinstance(choice, str)
                and choice in pack_ids)

    if declared and result.verdict == "pass":
        structural = policy._account(
            result, site=site, task_id=task_id, node_id=node_id,
            reservation=reservation)
        combo = issue_sort_combo(
            choice, pack_doc,
            confidence=result.confidence,
            evidence=list(result.reasons) + [f"choice:{choice}"],
            is_fallback=False, structural=structural)
        return result, structural, combo

    # Out-of-pack / transport fail / fallback / unparseable choice:
    # never invent a bucket. Keyword match against pack only.
    reasons = list(result.reasons) if result.reasons else []
    if isinstance(choice, str) and choice not in pack_ids:
        reasons = reasons + [
            f"out-of-pack choice refused: {choice!r}"]
    return keyword_sort(
        reasons, model=result.model,
        cost=float(result.cost or 0.0),
        input_tokens=int(result.input_tokens or 0),
        output_tokens=int(result.output_tokens or 0),
        reservation=reservation,
        reason=policy._fallback_reason_of(result, "out_of_pack"))
