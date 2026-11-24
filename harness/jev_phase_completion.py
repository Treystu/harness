"""Jev phase-completion bar evaluator owner (#309).

``harness/jev_policy.py`` keeps the ONE policy owner: when a typed call may
dispatch, its bounded spend, reservation and cancellation settlement, the
ledger event and the shared structural envelope. This module owns one domain
evaluator family -- judging one mission phase's evidence against the operator
phase-completion sentiment pack (JEV-BAR) -- so its inputs, its
0-hallucination rules and its fail-closed envelope change and review on their
own.

The family receives the policy instance it runs under; it never imports
``harness.jev_policy`` at module scope, so the dependency stays one-way.
"""
from typing import Any, Callable, Dict, List, Optional

from .errors import HarnessError, ProviderUsageUnknown, ToolCancelled
from .jev import LOCAL_HEURISTIC_MODEL, JevEvaluationResult
from .jev_packs import (
    PHASE_COMPLETION_SITE,
    completion_bar_question_pack,
    match_completion_keywords,
    validate_completion_pack,
)
from .provider_errors import ProviderSpendLimitError


def completion_state_text(state: Any) -> str:
    """Bounded text view of one phase's evidence for the JEV-BAR TypeSafe
    payload and the code-owned keyword fallback."""
    if isinstance(state, str):
        return state[:2400]
    if not isinstance(state, dict):
        return str(state)[:2400]
    parts = [
        str(state.get("phase") or ""),
        str(state.get("status_row") or ""),
        " ".join(str(b) for b in (state.get("open_blockers") or [])[:12]),
        " ".join(str(t) for t in (state.get("tests_missing") or [])[:12]),
        f"pr_merged={state.get('pr_merged')}",
        f"local_gates_green={state.get('local_gates_green')}",
        f"ci_green={state.get('ci_green')}",
        " ".join(str(n) for n in (state.get("notes") or [])[:6]),
    ]
    return " ".join(p for p in parts if p)[:2400]

def completion_judgment(pack_doc, live_levels, live_confidence, primary_gap,
                        *, is_fallback: bool, evidence) -> Dict[str, Any]:
    pack_doc = pack_doc if isinstance(pack_doc, dict) else {}
    return {
        "pack_id": pack_doc.get("id"),
        "live_levels": dict(live_levels or {}),
        "live_confidence": dict(live_confidence or {}),
        "primary_gap": primary_gap,
        "is_fallback": bool(is_fallback),
        "evidence": list(evidence or []),
    }

def evaluate_phase_completion(policy, state, pack, *,
                              site=PHASE_COMPLETION_SITE,
                              task_id: Optional[str] = None,
                              node_id: Optional[str] = None,
                              max_input_tokens: int,
                              refusal_reason: Callable[[Exception], str]):
    """Judge one mission phase's evidence against the operator
    phase-completion sentiment pack (JEV-BAR).

    0-hallucination contract (same class as ``evaluate_log_item`` /
    ``evaluate_repo_summary``):
    - every axis's ``live_levels`` value is an index into the pack's own
      declared ``sentiment.levels`` (via the official legend: anchors ->
      criteria strings, highest probability wins), else ``None`` -- a
      missing/invalid answer never invents a level;
    - ``primary_gap`` ∈ declared bucket ids, else ``None``; the choice
      ``\"none\"`` also maps to ``None`` (no improvement needed); an
      out-of-pack choice is refused (reason recorded) without failing the
      whole call;
    - unkeyed / invalid-pack / transport-fail / all-axes-invalid paths
      fall back to the code-owned keyword matcher (``buckets[].keywords``
      in the pack only) for ``primary_gap``; ``live_levels`` stay ``None``
      across the board -- code's own heuristic (``jev_packs.
      heuristic_completion_sentiment``) lives outside this call and is
      mixed in by the caller (``jev_completion.score_phase_completion``),
      never invented here;
    - ONE ledger ``jev_eval`` per call; ``structural.site=phase_completion``.
    Returns ``(result, structural, judgment)``.
    """
    text = completion_state_text(state)
    try:
        pack_doc = validate_completion_pack(pack)
    except ValueError as exc:
        result = JevEvaluationResult(
            "fail", 0.0, 0.0, {}, [str(exc)], cost=0.0,
            input_tokens=0, output_tokens=0, is_fallback=True,
            model=policy.evaluator.model, fallback_reason="invalid_pack")
        structural = policy._account(
            result, site=site, task_id=task_id, node_id=node_id)
        judgment = completion_judgment(
            None, None, None, None, is_fallback=True, evidence=result.reasons)
        return result, structural, judgment

    axis_ids = list(pack_doc["axes"])
    level_ids = list(pack_doc["sentiment"]["levels"])
    bucket_ids = set(pack_doc["buckets"])
    none_live_levels = {axis: None for axis in axis_ids}
    none_live_confidence = {axis: None for axis in axis_ids}

    def fallback_judgment(reasons, *, model=None, cost=0.0,
                          input_tokens=0, output_tokens=0,
                          reservation=None, reason=None,
                          discarded=False):
        bucket_id, _hits, kw_evidence = match_completion_keywords(text, pack_doc)
        evidence_refs = list(reasons or []) + list(kw_evidence or [])
        result = JevEvaluationResult(
            "pass" if bucket_id else "fail", 0.0, 1.0 if bucket_id else 0.0,
            {"primary_gap": bucket_id}, evidence_refs,
            cost=cost, input_tokens=input_tokens,
            output_tokens=output_tokens, is_fallback=True,
            model=model or LOCAL_HEURISTIC_MODEL, discarded=discarded)
        result = policy._with_reason(result, reason, text)
        # ONE ledger jev_eval per evaluate_phase_completion call.
        structural = policy._account(
            result, site=site, task_id=task_id, node_id=node_id,
            reservation=reservation)
        judgment = completion_judgment(
            pack_doc, none_live_levels, none_live_confidence, bucket_id,
            is_fallback=True, evidence=evidence_refs)
        return result, structural, judgment

    if not policy.keyed:
        return fallback_judgment(["unkeyed: keyword match only"],
                                 reason=policy._no_key_reason())

    reservation = None
    try:
        questions = completion_bar_question_pack(pack_doc)
        payload = {
            "phase": state.get("phase") if isinstance(state, dict) else None,
            "evidence": text, "pack_id": pack_doc["id"],
        }
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
        # heuristic classification as a live one.
        return fallback_judgment(
            list(result.reasons or ["invalid TypeSafe response"]),
            model=result.model,
            cost=float(result.cost or 0.0),
            input_tokens=int(result.input_tokens or 0),
            output_tokens=int(result.output_tokens or 0),
            reservation=reservation, discarded=bool(result.discarded),
            reason=policy._fallback_reason_of(result, "invalid_answer"))

    live_levels: Dict[str, Optional[int]] = {}
    live_confidence: Dict[str, Optional[float]] = {}
    evidence: List[str] = []
    any_axis_valid = False
    for axis in axis_ids:
        answer = answers.get(axis)
        level = None
        value = None
        conf = None
        if isinstance(answer, dict):
            probs = answer.get("probabilities")
            legend = answer.get("legend")
            if isinstance(probs, dict) and isinstance(legend, dict):
                for anchor, lvl in legend.items():
                    if not isinstance(lvl, str) or lvl not in level_ids:
                        continue
                    prob = probs.get(str(anchor))
                    if isinstance(prob, (int, float)) and (
                            value is None or float(prob) > value):
                        level, value = lvl, float(prob)
            raw_conf = answer.get("confidence")
            if isinstance(raw_conf, (int, float)) and not isinstance(raw_conf, bool):
                conf = float(raw_conf)
        if level is not None:
            any_axis_valid = True
            live_levels[axis] = level_ids.index(level)
            evidence.append(f"{axis}:{level}")
        else:
            live_levels[axis] = None
            evidence.append(f"{axis}:unmatched")
        live_confidence[axis] = conf

    primary_gap: Optional[str] = None
    gap_answer = answers.get("primary_gap")
    choice = gap_answer.get("choice") if isinstance(gap_answer, dict) else None
    if isinstance(choice, str) and choice == "none":
        evidence.append("primary_gap:none")
    elif isinstance(choice, str) and choice in bucket_ids:
        primary_gap = choice
        evidence.append(f"primary_gap:{choice}")
    elif isinstance(choice, str):
        evidence.append(f"out-of-pack primary_gap refused: {choice!r}")
    else:
        evidence.append("primary_gap:unmatched")

    if not any_axis_valid:
        # Every axis was missing/invalid: present the whole call as a
        # fallback rather than a live judgment with nothing declared.
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
    judgment = completion_judgment(
        pack_doc, live_levels, live_confidence, primary_gap,
        is_fallback=False, evidence=evidence)
    return result, structural, judgment
