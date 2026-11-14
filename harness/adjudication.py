"""Typed adjudication contract v1 (issue #453).

Implements the oversight decision filed as issue #453 comment 6815774435
verbatim: per-claim Jev verdicts (REAL | NOT_REAL | DEFER) from a deterministic
support/risk mapping, lexicographic aggregation over the five v1 rules in fixed
order, and a named non-Jev fallback label.

LLM panel/judge outputs are advisory inputs only and can never override a Jev
verdict. That is enforced in code shape, not by convention: :func:`adjudicate_claim`
accepts no advisory parameter at all (there is no argument to smuggle an
override through), and :func:`aggregate` reads only the Jev verdicts on the
:class:`ClaimAdjudication` records. Advisory notes may ride along on
``ClaimAdjudication.advisory_notes`` for audit display; the verdict path never
consults that field.
"""

from dataclasses import dataclass
from typing import Literal, Optional, Sequence, Tuple

ClaimPolarity = Literal["defect", "reassurance"]
ClaimMateriality = Literal["material", "supporting"]
ClaimVerdict = Literal["REAL", "NOT_REAL", "DEFER"]
FinalVerdict = Literal["PASS", "FAIL", "DEFER"]

FALLBACK_LABEL = "NON-JEV FALLBACK"

# v1 thresholds, hardcoded per the decision. These are tunables: they change
# only through the gate process, never silently (decision #453 c6815774435).
SUPPORT_REAL_MIN = 0.65
SUPPORT_NOT_REAL_MAX = 0.35
RISK_MAX = 0.30


@dataclass(frozen=True)
class ClaimInput:
    """One adjudicable claim: id, text, polarity, materiality, evidence refs."""

    claim_id: str
    claim_text: str
    polarity: ClaimPolarity
    materiality: ClaimMateriality
    evidence_refs: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.polarity not in ("defect", "reassurance"):
            raise ValueError(f"unknown polarity: {self.polarity!r}")
        if self.materiality not in ("material", "supporting"):
            raise ValueError(f"unknown materiality: {self.materiality!r}")


@dataclass(frozen=True)
class ClaimAdjudication:
    """A Jev verdict on one claim. Advisory notes are audit-only."""

    claim: ClaimInput
    verdict: ClaimVerdict
    support: float
    risk: float
    missing_context: Tuple[str, ...] = ()
    contradicted: bool = False
    advisory_notes: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.verdict not in ("REAL", "NOT_REAL", "DEFER"):
            raise ValueError(f"unknown verdict: {self.verdict!r}")
        if self.verdict == "DEFER" and not self.missing_context:
            raise ValueError("DEFER requires a named missing-context list")


@dataclass(frozen=True)
class AdjudicationResult:
    """Final verdict plus the rule that decided it and audit trail."""

    final: FinalVerdict
    deciding_rule: int  # 0 = non-Jev fallback, 1-5 = aggregation rule v1
    escalate: bool
    fallback_label: Optional[str]
    confidence_note: str
    per_claim: Tuple[ClaimAdjudication, ...] = ()


def adjudicate_claim(
    claim: ClaimInput,
    support: float,
    risk: float,
    missing_context: Sequence[str] = (),
) -> ClaimAdjudication:
    """Deterministic Jev-verdict mapping v1 (decision #453 c6815774435).

    REAL when support >= 0.65 and risk <= 0.30; NOT_REAL when support <= 0.35
    and risk <= 0.30; otherwise DEFER. DEFER requires a named missing-context
    list, which drives the worker fetch + re-adjudication loop.
    """
    missing = tuple(missing_context)
    if support >= SUPPORT_REAL_MIN and risk <= RISK_MAX:
        verdict: ClaimVerdict = "REAL"
    elif support <= SUPPORT_NOT_REAL_MAX and risk <= RISK_MAX:
        verdict = "NOT_REAL"
    else:
        verdict = "DEFER"
    return ClaimAdjudication(
        claim=claim,
        verdict=verdict,
        support=support,
        risk=risk,
        missing_context=missing,
    )


def _confidence_note(adjudications: Sequence[ClaimAdjudication]) -> str:
    supporting = [a for a in adjudications if a.claim.materiality == "supporting"]
    if not supporting:
        return "no supporting claims"
    tally = {"REAL": 0, "NOT_REAL": 0, "DEFER": 0}
    for a in supporting:
        tally[a.verdict] += 1
    return (
        "supporting claims (confidence only, never verdict-swinging): "
        f"{tally['REAL']} REAL, {tally['NOT_REAL']} NOT_REAL, "
        f"{tally['DEFER']} DEFER of {len(supporting)}"
    )


def aggregate(adjudications: Sequence[ClaimAdjudication]) -> AdjudicationResult:
    """Lexicographic aggregation v1: fixed order, first match decides.

    1. Any material claim still DEFER -> final DEFER + escalate (never a
       silent pass). 2. Any material defect REAL -> FAIL. 3. Any material
       reassurance NOT_REAL -> FAIL. 4. Unresolved contradiction on a material
       claim across rounds -> DEFER. 5. Otherwise -> PASS. Supporting claims
       never swing the verdict; they appear in the confidence note only.
    """
    adjudications = tuple(adjudications)
    material = [a for a in adjudications if a.claim.materiality == "material"]
    note = _confidence_note(adjudications)

    def result(final: FinalVerdict, rule: int, escalate: bool) -> AdjudicationResult:
        return AdjudicationResult(
            final=final,
            deciding_rule=rule,
            escalate=escalate,
            fallback_label=None,
            confidence_note=note,
            per_claim=adjudications,
        )

    if any(a.verdict == "DEFER" for a in material):
        return result("DEFER", 1, True)
    if any(a.verdict == "REAL" and a.claim.polarity == "defect" for a in material):
        return result("FAIL", 2, False)
    if any(
        a.verdict == "NOT_REAL" and a.claim.polarity == "reassurance"
        for a in material
    ):
        return result("FAIL", 3, False)
    if any(a.contradicted for a in material):
        return result("DEFER", 4, False)
    return result("PASS", 5, False)


def non_jev_fallback(
    consensus: FinalVerdict, note: str = ""
) -> AdjudicationResult:
    """Named fallback when Jev is unavailable on the surface's canonical check.

    Falls back to panel + judge consensus and labels the output NON-JEV
    FALLBACK -- never Jev-primary.
    """
    if consensus not in ("PASS", "FAIL", "DEFER"):
        raise ValueError(f"unknown consensus: {consensus!r}")
    confidence = f"{FALLBACK_LABEL}: panel + judge consensus ({note})" if note else (
        f"{FALLBACK_LABEL}: panel + judge consensus"
    )
    return AdjudicationResult(
        final=consensus,
        deciding_rule=0,
        escalate=consensus == "DEFER",
        fallback_label=FALLBACK_LABEL,
        confidence_note=confidence,
        per_claim=(),
    )


__all__ = [
    "ClaimAdjudication",
    "ClaimInput",
    "ClaimMateriality",
    "ClaimPolarity",
    "ClaimVerdict",
    "FinalVerdict",
    "FALLBACK_LABEL",
    "RISK_MAX",
    "SUPPORT_NOT_REAL_MAX",
    "SUPPORT_REAL_MIN",
    "AdjudicationResult",
    "adjudicate_claim",
    "aggregate",
    "non_jev_fallback",
]
