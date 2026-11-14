"""Deterministic unit coverage for the #453 adjudication contract v1.

Synthetic claim sets only. Jev answers are stubbed as plain support/risk
floats -- no network, no keys. Covers the deterministic mapping, all five
aggregation rules (including first-match precedence), supporting-claim
neutrality, the advisory-never-overrides shape, and the fallback labeling.
"""

import inspect

import pytest

from harness.adjudication import (
    FALLBACK_LABEL,
    ClaimAdjudication,
    ClaimInput,
    adjudicate_claim,
    aggregate,
    non_jev_fallback,
)


def defect(claim_id, materiality="material"):
    return ClaimInput(
        claim_id=claim_id,
        claim_text=f"synthetic defect {claim_id}",
        polarity="defect",
        materiality=materiality,
        evidence_refs=("ev1",),
    )


def reassurance(claim_id, materiality="material"):
    return ClaimInput(
        claim_id=claim_id,
        claim_text=f"synthetic reassurance {claim_id}",
        polarity="reassurance",
        materiality=materiality,
        evidence_refs=("ev1",),
    )


def decided(claim, verdict, contradicted=False):
    support = {"REAL": 0.9, "NOT_REAL": 0.1, "DEFER": 0.5}[verdict]
    return ClaimAdjudication(
        claim=claim,
        verdict=verdict,
        support=support,
        risk=0.1,
        missing_context=("ctx",) if verdict == "DEFER" else (),
        contradicted=contradicted,
    )


# --- deterministic mapping v1 ---


def test_mapping_real_at_threshold():
    adj = adjudicate_claim(defect("m1"), support=0.65, risk=0.30)
    assert adj.verdict == "REAL"


def test_mapping_not_real_at_threshold():
    adj = adjudicate_claim(reassurance("m2"), support=0.35, risk=0.30)
    assert adj.verdict == "NOT_REAL"


def test_mapping_defer_middle_band():
    adj = adjudicate_claim(defect("m3"), support=0.5, risk=0.1,
                           missing_context=["round-2-context"])
    assert adj.verdict == "DEFER"
    assert adj.missing_context == ("round-2-context",)


def test_mapping_high_risk_defers_despite_high_support():
    adj = adjudicate_claim(defect("m4"), support=0.9, risk=0.31,
                           missing_context=["risk-review"])
    assert adj.verdict == "DEFER"


def test_mapping_low_support_high_risk_defers():
    adj = adjudicate_claim(reassurance("m5"), support=0.1, risk=0.5,
                           missing_context=["risk-review"])
    assert adj.verdict == "DEFER"


def test_mapping_just_below_real_is_defer():
    adj = adjudicate_claim(defect("m6"), support=0.64, risk=0.1,
                           missing_context=["more-evidence"])
    assert adj.verdict == "DEFER"


def test_defer_requires_named_missing_context():
    with pytest.raises(ValueError):
        adjudicate_claim(defect("m7"), support=0.5, risk=0.1)


def test_advisory_inputs_cannot_override_in_code_shape():
    params = set(inspect.signature(adjudicate_claim).parameters)
    assert params == {"claim", "support", "risk", "missing_context"}
    agg_params = set(inspect.signature(aggregate).parameters)
    assert agg_params == {"adjudications"}


def test_advisory_notes_ride_along_without_changing_verdict():
    claim = defect("m8")
    plain = decided(claim, "REAL")
    noted = ClaimAdjudication(
        claim=claim, verdict="REAL", support=0.9, risk=0.1,
        advisory_notes=("panel says not_real", "judge says defer"),
    )
    assert aggregate([plain]).final == aggregate([noted]).final == "FAIL"


# --- aggregation rules ---


def test_rule1_material_defer_defers_and_escalates():
    res = aggregate([decided(defect("d1"), "DEFER")])
    assert (res.final, res.deciding_rule, res.escalate) == ("DEFER", 1, True)


def test_rule1_beats_rule2_first_match_decides():
    res = aggregate([
        decided(defect("d1"), "REAL"),
        decided(defect("d2"), "DEFER"),
    ])
    assert (res.final, res.deciding_rule) == ("DEFER", 1)


def test_rule2_material_defect_real_fails():
    res = aggregate([
        decided(defect("d1"), "REAL"),
        decided(reassurance("r1"), "REAL"),
    ])
    assert (res.final, res.deciding_rule, res.escalate) == ("FAIL", 2, False)


def test_rule3_material_reassurance_not_real_fails():
    res = aggregate([
        decided(defect("d1"), "NOT_REAL"),
        decided(reassurance("r1"), "NOT_REAL"),
    ])
    assert (res.final, res.deciding_rule) == ("FAIL", 3)


def test_rule4_unresolved_contradiction_defers():
    res = aggregate([
        decided(defect("d1"), "NOT_REAL", contradicted=True),
        decided(reassurance("r1"), "REAL"),
    ])
    assert (res.final, res.deciding_rule) == ("DEFER", 4)


def test_rule4_yields_to_rule2_in_fixed_order():
    res = aggregate([
        decided(defect("d1"), "REAL", contradicted=True),
    ])
    assert (res.final, res.deciding_rule) == ("FAIL", 2)


def test_rule5_clean_set_passes():
    res = aggregate([
        decided(defect("d1"), "NOT_REAL"),
        decided(reassurance("r1"), "REAL"),
    ])
    assert (res.final, res.deciding_rule) == ("PASS", 5)
    assert res.fallback_label is None


def test_rule5_empty_set_passes():
    res = aggregate([])
    assert (res.final, res.deciding_rule) == ("PASS", 5)


def test_supporting_claims_never_swing_verdict():
    res = aggregate([
        decided(defect("d1"), "NOT_REAL"),
        decided(reassurance("r1"), "REAL"),
        decided(defect("s1", materiality="supporting"), "REAL"),
        decided(reassurance("s2", materiality="supporting"), "NOT_REAL"),
        decided(defect("s3", materiality="supporting"), "DEFER"),
    ])
    assert (res.final, res.deciding_rule) == ("PASS", 5)
    assert "confidence only" in res.confidence_note


def test_supporting_defer_does_not_trigger_rule1():
    res = aggregate([
        decided(defect("d1"), "NOT_REAL"),
        decided(defect("s1", materiality="supporting"), "DEFER"),
    ])
    assert (res.final, res.deciding_rule) == ("PASS", 5)


# --- fallback ---


def test_fallback_labels_non_jev():
    res = non_jev_fallback("FAIL", note="jev transport refused")
    assert res.final == "FAIL"
    assert res.deciding_rule == 0
    assert res.fallback_label == FALLBACK_LABEL == "NON-JEV FALLBACK"
    assert "Jev-primary" not in res.confidence_note


def test_fallback_rejects_unknown_consensus():
    with pytest.raises(ValueError):
        non_jev_fallback("MAYBE")


def test_invalid_inputs_rejected():
    with pytest.raises(ValueError):
        ClaimInput(claim_id="x", claim_text="x", polarity="vibe",
                   materiality="material")
    with pytest.raises(ValueError):
        ClaimInput(claim_id="x", claim_text="x", polarity="defect",
                   materiality="critical")
