"""Jev claim-support evaluator owner (#309).

``harness/jev_policy.py`` keeps the ONE policy owner: when a typed call may
dispatch, its bounded spend, reservation and cancellation settlement, the
ledger event and the shared structural envelope. This module owns one domain
evaluator family -- the optional JEV-P3 lean support flags a caller may ask
for before a panel judge -- so its inputs, its advisory-only rules and its
fail-closed envelope change and review on their own.

It does not own claims lint: that stays in :mod:`harness.claims`, and this
family adds advisory typed flags only.

The family receives the policy instance it runs under; it never imports
``harness.jev_policy`` at module scope, so the dependency stays one-way.
"""
from typing import Callable, Optional

from .errors import HarnessError, ProviderUsageUnknown, ToolCancelled
from .jev import JevEvaluationResult
from .jev_packs import claim_support_question_pack, claims_from_payload
from .provider_errors import ProviderSpendLimitError


def evaluate_claim_support(policy, claims, source_context: str, *,
                           enabled: bool = False,
                           site: str = "claims",
                           task_id: Optional[str] = None,
                           max_input_tokens: int,
                           refusal_reason: Callable[[Exception], str]):
    """JEV-P3-claims: optional lean support checks before panel judge.

    Default off (``enabled=False``). Does not own claims lint — that stays
    in :mod:`harness.claims`. This only adds advisory typed flags.
    """
    normalized = claims_from_payload(claims)
    if not enabled or not normalized:
        skipped = JevEvaluationResult(
            "pass", 0.0, 1.0,
            {"enabled": bool(enabled), "claims": [], "skipped": True},
            ["claim-support checks disabled or empty"],
            is_fallback=True, model=policy.evaluator.model,
            fallback_reason="claims_skipped")
        structural = policy._structural(skipped, site)
        structural["claim_flags"] = []
        structural["skipped"] = True
        return skipped, structural
    reservation = None
    try:
        reservation = policy._preflight(
            site=site, max_input_tokens=max_input_tokens)
        result = policy.evaluator.evaluate(
            {
                "claims": [{"id": c["id"], "text": c["text"]}
                           for c in normalized],
                "evidence": (source_context or "")[:4000],
            },
            claim_support_question_pack(len(normalized)))
        flags = []
        if result.is_fallback:
            # Unkeyed: no support claim either way — advisory unknown.
            flags = [{"id": c["id"], "supported": None, "fallback": True}
                     for c in normalized]
            result = JevEvaluationResult(
                "pass", 0.0, 1.0,
                {"claim_flags": flags, "skipped": False},
                result.reasons, cost=result.cost,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                is_fallback=True, model=result.model,
                discarded=result.discarded,
                fallback_reason=policy._fallback_reason_of(
                    result, "claims_unanswered"))
        else:
            for index, claim in enumerate(normalized):
                key = f"claim_{index}_supported"
                answer = (result.answers or {}).get(key)
                prob = None
                if isinstance(answer, dict):
                    prob = answer.get("noul")
                elif isinstance(answer, (int, float)):
                    prob = answer
                supported = None
                if isinstance(prob, (int, float)):
                    supported = float(prob) >= 0.5
                flags.append({"id": claim["id"], "supported": supported,
                              "noul": prob, "fallback": False})
            result = JevEvaluationResult(
                result.verdict, result.confidence, result.supported,
                {"claim_flags": flags, "skipped": False}, result.reasons,
                cost=result.cost, input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                is_fallback=False, model=result.model,
                cache_hit=result.cache_hit)
        structural = policy._account(
            result, site=site, task_id=task_id, reservation=reservation)
        structural["claim_flags"] = flags
        structural["skipped"] = False
        return result, structural
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
        flags = [{"id": c["id"], "supported": None, "fallback": True}
                 for c in normalized]
        fallback = JevEvaluationResult(
            "pass", 0.0, 1.0,
            {"claim_flags": flags, "skipped": False}, [str(exc)],
            is_fallback=True, model=policy.evaluator.model,
            fallback_reason=refusal_reason(exc))
        structural = policy._account(fallback, site=site, task_id=task_id)
        structural["claim_flags"] = flags
        structural["skipped"] = False
        return fallback, structural
