"""Jev 4-dimensional self-audit evaluator owner (#309).

``harness/jev_policy.py`` keeps the ONE policy owner: when a typed call may
dispatch, its bounded spend, reservation and cancellation settlement, the
ledger event and the shared structural envelope. This module owns one domain
evaluator family -- judging the 4-dimensional self-audit evidence with Jev as
the authoritative gate, and never scoring a dimension the run did not measure
-- so its inputs, its honesty rules and its fail-closed envelope change and
review on their own.

The family receives the policy instance it runs under; it never imports
``harness.jev_policy`` at module scope, so the dependency stays one-way.
"""
from typing import Any, Callable, Dict, Optional

from .errors import HarnessError, ProviderUsageUnknown, ToolCancelled
from .jev import LOCAL_HEURISTIC_MODEL, JevEvaluationResult
from .jev_packs import (
    AUDIT_DIMENSIONS_SITE,
    audit_dimensions_question_pack,
    heuristic_audit_dimensions,
    validate_audit_pack,
)
from .provider_errors import ProviderSpendLimitError


def resolve_audit_dimension(answer, levels, *, evidence_score, min_confidence):
    """Resolve one audit dimension from one declared answer.

    The answer is a score-typed legend (anchor -> declared level string) plus a
    probability distribution. The level is the highest-probability declared
    anchor, exactly like every other score-typed site here.

    A level whose own probability does not clear ``min_confidence`` is not a
    judgment the policy may act on. Observed live from jev-1.14.0, three runs:
    dim_A came back 0.59 on "failing" against 0.36 on "exemplary" with every
    declared scalar 0.0 -- a bimodal non-answer that the argmax reported as
    FAIL 5.00/10 on a dimension whose thirteen measured checks all passed.
    Such an answer resolves from the dimension's own evidence instead, which
    is the same path a missing answer already takes; the level and its
    probability are still recorded so the refusal can be audited. The 9.5 bar
    is untouched: weak evidence still fails, it just fails on its evidence.

    Pure, so the rule is testable without a transport or a key.
    """
    level = None
    value = None
    conf = None
    if isinstance(answer, dict):
        probs = answer.get("probabilities")
        legend = answer.get("legend")
        if isinstance(probs, dict) and isinstance(legend, dict):
            for anchor, declared in legend.items():
                if not isinstance(declared, str) or declared not in levels:
                    continue
                prob = probs.get(str(anchor))
                if (isinstance(prob, (int, float))
                        and not isinstance(prob, bool)
                        and (value is None or float(prob) > value)):
                    level, value = declared, float(prob)
        raw_conf = answer.get("confidence")
        if isinstance(raw_conf, (int, float)) and not isinstance(raw_conf, bool):
            conf = float(raw_conf)
    live_level = level
    live_conf = None if value is None else round(float(value), 4)
    if live_conf is not None and (conf is None or conf <= 0.0):
        conf = live_conf
    if level is not None and float(value) < float(min_confidence):
        level = None
    if level is not None:
        idx = levels.index(level)
        source = "live"
    else:
        score = float(evidence_score or 0.0)
        idx = (4 if score >= 9.99 else
               3 if score >= 9.5 else
               2 if score >= 8.5 else
               1 if score >= 7.0 else 0)
        source = ("heuristic_low_confidence" if live_conf is not None
                  else "heuristic")
    return idx, source, conf, live_level, live_conf


def audit_dimension_text(dimension_evidence: Any) -> str:
    lines = ["Harness 4-Dimensional Self-Audit Evidence:"]
    source = dimension_evidence if isinstance(dimension_evidence, dict) else {}
    for dim in ("A", "R", "SM", "SD"):
        ev = source.get(dim)
        if not isinstance(ev, dict):
            # A dimension this run did not measure has NO score. Rendering
            # it as score=0.00/10 with 0/0 checks asks the model to grade
            # the dimension against three fabricated zeros, which is how a
            # --dim run turned a 13/13 pass into "failing -- severe defect"
            # (#578). Say what is true: it was not evaluated, and the
            # absent score must not be inferred.
            lines.append(f"Dimension {dim}: not evaluated (no evidence "
                         "supplied for this run; do not infer a score for it)")
            continue
        score = ev.get("score", 0.0)
        satisfied = ev.get("checks_satisfied", 0)
        total = ev.get("checks_count", 0)
        lines.append(f"Dimension {dim}: score={score:.2f}/10 ({satisfied}/{total} checks fully satisfied)")
        for ch in (ev.get("checks") or [])[:5]:
            cid = ch.get("id", "")
            mark = "pass" if ch.get("score", 0) >= 1 else "part"
            label = ch.get("label", "")
            lines.append(f"  [{cid}] {mark} {label}")
    return "\n".join(lines)

def evaluate_audit_dimensions(
    policy,
    dimension_evidence: Dict[str, Any],
    pack: Any = None,
    *,
    site: str = AUDIT_DIMENSIONS_SITE,
    task_id: Optional[str] = None,
    max_input_tokens: int,
    refusal_reason: Callable[[Exception], str],
) -> Dict[str, Any]:
    """Evaluate the 4 self-audit dimensions with Jev as the authoritative gate.

    0-hallucination / honesty contract (same class as
    ``evaluate_log_item`` / ``evaluate_phase_completion``):

    - a dimension ABSENT from ``dimension_evidence`` (a partial ``--dim``
      run) is reported ``not_evaluated`` -- ``level_index``/``score`` are
      ``None`` -- never a false 0.0/"failing" score for a check that
      never ran;
    - a live ``dim_<id>`` answer resolves to a level via the official
      legend (anchor -> declared level string) + highest probability,
      exactly like every other score-typed site in this module -- never
      a raw score-as-index guess. An unmatched/invalid live answer for
      one EVALUATED dimension falls back to that dimension's own
      evidence-calibrated heuristic; if every evaluated dimension is
      unmatched, the whole call is presented as a fallback rather than a
      live judgment with nothing actually declared by Jev;
    - ``bar_95_pass`` is true only when ALL FOUR declared dimensions
      were evaluated AND every one scores >= 9.5 -- fail closed, never a
      false PASS on a partial run;
    - preflight reservation + EXACTLY ONE ledger ``jev_eval`` per call
      (``structural.site=audit_dimensions``) on every path -- unkeyed,
      governor-missing, transport-error, and invalid-response fallbacks
      included -- via the shared ``_account`` accounting helper (never a
      bare ``jev_refusal`` standing in for the one required
      ``jev_eval``).
    """
    pack_doc = validate_audit_pack(pack)
    questions = audit_dimensions_question_pack(pack_doc)
    levels = pack_doc["sentiment"]["levels"]
    ordinals = pack_doc["sentiment"]["ordinals"]
    bar_idx = pack_doc["sentiment"].get("bar_met_index", 3)
    dim_ids = list(pack_doc["dimensions"])
    evidence_is_dict = isinstance(dimension_evidence, dict)

    model_name = getattr(policy.evaluator, "model", "jev-latest")

    def dim_evaluated(dim: str) -> bool:
        return (not evidence_is_dict) or (dim in dimension_evidence)

    def bar_pass(dim_results: Dict[str, Any]) -> bool:
        if set(dim_results) != set(dim_ids):
            return False
        if any(not d.get("evaluated") for d in dim_results.values()):
            return False
        scores = [d.get("score") for d in dim_results.values()]
        if any(s is None for s in scores):
            return False
        return all(float(s) >= 9.5 for s in scores)

    def fallback_judgment(reasons, *, model=None, cost=0.0, input_tokens=0,
                          output_tokens=0, reservation=None, reason=None,
                          declared=None):
        dim_results = heuristic_audit_dimensions(dimension_evidence, pack_doc)
        if declared:
            # A whole-call fallback must not erase a claim Jev did make: a
            # dimension whose declared level was too uncertain to act on
            # keeps that level and its probability on the receipt, exactly
            # as the live path records them (#585). Both mappings come from
            # the same pack, so the heuristic carries every id named here;
            # an unmatched answer declared no level and gains no key.
            for dim, entry in declared.items():
                level = entry.get("live_level")
                if level is None:
                    continue
                dim_results[dim]["live_level"] = level
                claim = entry["live_level_confidence"]
                dim_results[dim]["live_level_confidence"] = claim
        scores = {dim: d.get("score") for dim, d in dim_results.items()}
        evaluated_scores = [s for s in scores.values() if s is not None]
        passed = bar_pass(dim_results)
        fallback_result = JevEvaluationResult(
            "pass" if passed else "fail", 0.0,
            1.0 if evaluated_scores else 0.0,
            {f"dim_{dim}": dim_results[dim] for dim in dim_ids},
            list(reasons), cost=cost, input_tokens=input_tokens,
            output_tokens=output_tokens, is_fallback=True,
            model=model or LOCAL_HEURISTIC_MODEL)
        fallback_result = policy._with_reason(
            fallback_result, reason,
            audit_dimension_text(dimension_evidence))
        policy._account(fallback_result, site=site, task_id=task_id,
                      reservation=reservation)
        return {
            "dimensions": dim_results,
            "scores": scores,
            "bar_95_pass": passed,
            "min_score": min(evaluated_scores) if evaluated_scores else 0.0,
            "is_fallback": True,
            "reasons": list(reasons),
            # The report and the ledger row describe one judgment, so they
            # carry one identity; a caller-supplied live model wins (#332).
            "model": fallback_result.model,
            "cost": cost,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }

    if not policy.keyed or policy.governor is None:
        return fallback_judgment(
            ["unkeyed" if not policy.keyed else "governor_not_provided"],
            reason=(policy._no_key_reason() if not policy.keyed
                    else "governor_not_provided"))

    text = audit_dimension_text(dimension_evidence)
    reservation = None
    try:
        payload = {"evidence": text, "pack_id": pack_doc["id"]}
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
        return fallback_judgment(
            [f"transport_error: {exc}"], reservation=reservation,
            reason=refusal_reason(exc))
    except Exception as exc:  # unexpected transport failure -- fail closed
        return fallback_judgment(
            [f"transport_error: {exc}"], reservation=reservation,
            reason="transport_failure")

    answers = result.answers if isinstance(result.answers, dict) else {}
    if result.is_fallback or not answers:
        return fallback_judgment(
            list(result.reasons or ["invalid TypeSafe response"]),
            model=result.model or model_name,
            cost=float(result.cost or 0.0),
            input_tokens=int(result.input_tokens or 0),
            output_tokens=int(result.output_tokens or 0),
            reservation=reservation,
            reason=policy._fallback_reason_of(result, "invalid_answer"),
        )

    dim_results = {}
    any_dim_valid = False
    evaluated_dim_ids = []
    for dim, spec in pack_doc["dimensions"].items():
        if not dim_evaluated(dim):
            dim_results[dim] = {
                "name": spec["name"],
                "level_index": None,
                "level": "not_evaluated",
                "score": None,
                "bar_met": False,
                "confidence": None,
                "evaluated": False,
                "source": "not_evaluated",
            }
            continue
        evaluated_dim_ids.append(dim)
        ev = dimension_evidence.get(dim) if evidence_is_dict else None
        ev_score = float(ev.get("score", 0.0)) if isinstance(ev, dict) else 0.0
        idx, level_source, conf, live_level, live_conf = (
            resolve_audit_dimension(
                answers.get(f"dim_{dim}"), levels,
                evidence_score=ev_score,
                min_confidence=float(
                    getattr(policy.evaluator, "min_confidence", 0.70) or 0.70)))
        if level_source == "live":
            any_dim_valid = True
        dim_results[dim] = {
            "name": spec["name"],
            "level_index": idx,
            "level": levels[idx],
            "score": round(ordinals[idx], 2),
            "bar_met": idx >= bar_idx,
            "confidence": conf,
            "evaluated": True,
            # Which claim this level is: a level Jev declared for this
            # dimension, or this dimension's evidence-calibrated index
            # standing in for a missing/invalid answer. A call can be live
            # overall while one dimension is heuristic (#454 item 3).
            "source": level_source,
            # What Jev actually declared, kept even when it was too
            # uncertain to act on, so the refusal can be audited.
            "live_level": live_level,
            "live_level_confidence": live_conf,
        }

    if evaluated_dim_ids and not any_dim_valid:
        # Every evaluated dimension's live answer was unmatched/invalid:
        # present the whole call as a fallback rather than a live
        # judgment with nothing actually declared by Jev.
        return fallback_judgment(
            [f"dim_{dim}: unmatched" for dim in evaluated_dim_ids]
            + list(result.reasons or []),
            model=result.model, cost=float(result.cost or 0.0),
            input_tokens=int(result.input_tokens or 0),
            output_tokens=int(result.output_tokens or 0),
            reservation=reservation,
            reason=policy._fallback_reason_of(result, "no_declared_axes"),
            declared=dim_results)

    policy._account(result, site=site, task_id=task_id, reservation=reservation)
    scores = {dim: d.get("score") for dim, d in dim_results.items()}
    evaluated_scores = [s for s in scores.values() if s is not None]
    return {
        "dimensions": dim_results,
        "scores": scores,
        "bar_95_pass": bar_pass(dim_results),
        "min_score": min(evaluated_scores) if evaluated_scores else 0.0,
        "is_fallback": False,
        "reasons": [],
        "model": result.model or model_name,
        "cost": float(result.cost or 0.0),
        "input_tokens": int(result.input_tokens or 0),
        "output_tokens": int(result.output_tokens or 0),
    }
