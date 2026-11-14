"""Deterministic unit coverage for the #453 adjudication contract v1.

Synthetic claim sets only. Jev answers are stubbed as plain support/risk
floats -- no network, no keys. Covers the deterministic mapping, all five
aggregation rules (including first-match precedence), supporting-claim
neutrality, the advisory-never-overrides shape, and the fallback labeling.

unittest TestCase classes (the repo's hermetic convention) so the CI
hermetic suite and the D12 traced battery execute every test.
"""
import inspect
import unittest

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


class MappingTests(unittest.TestCase):
    """Deterministic mapping v1."""

    def test_mapping_real_at_threshold(self):
        adj = adjudicate_claim(defect("m1"), support=0.65, risk=0.30)
        self.assertEqual(adj.verdict, "REAL")

    def test_mapping_not_real_at_threshold(self):
        adj = adjudicate_claim(reassurance("m2"), support=0.35, risk=0.30)
        self.assertEqual(adj.verdict, "NOT_REAL")

    def test_mapping_defer_middle_band(self):
        adj = adjudicate_claim(defect("m3"), support=0.5, risk=0.1,
                               missing_context=["round-2-context"])
        self.assertEqual(adj.verdict, "DEFER")
        self.assertEqual(adj.missing_context, ("round-2-context",))

    def test_mapping_high_risk_defers_despite_high_support(self):
        adj = adjudicate_claim(defect("m4"), support=0.9, risk=0.31,
                               missing_context=["risk-review"])
        self.assertEqual(adj.verdict, "DEFER")

    def test_mapping_low_support_high_risk_defers(self):
        adj = adjudicate_claim(reassurance("m5"), support=0.1, risk=0.5,
                               missing_context=["risk-review"])
        self.assertEqual(adj.verdict, "DEFER")

    def test_mapping_just_below_real_is_defer(self):
        adj = adjudicate_claim(defect("m6"), support=0.64, risk=0.1,
                               missing_context=["more-evidence"])
        self.assertEqual(adj.verdict, "DEFER")

    def test_defer_requires_named_missing_context(self):
        with self.assertRaises(ValueError):
            adjudicate_claim(defect("m7"), support=0.5, risk=0.1)

    def test_advisory_inputs_cannot_override_in_code_shape(self):
        params = set(inspect.signature(adjudicate_claim).parameters)
        self.assertEqual(params, {"claim", "support", "risk", "missing_context"})
        agg_params = set(inspect.signature(aggregate).parameters)
        self.assertEqual(agg_params, {"adjudications"})

    def test_advisory_notes_ride_along_without_changing_verdict(self):
        claim = defect("m8")
        plain = decided(claim, "REAL")
        noted = ClaimAdjudication(
            claim=claim, verdict="REAL", support=0.9, risk=0.1,
            advisory_notes=("panel says not_real", "judge says defer"),
        )
        self.assertEqual(aggregate([plain]).final,
                         aggregate([noted]).final)
        self.assertEqual(aggregate([noted]).final, "FAIL")


class AggregationTests(unittest.TestCase):
    """Lexicographic aggregation rules, first match decides."""

    def test_rule1_material_defer_defers_and_escalates(self):
        res = aggregate([decided(defect("d1"), "DEFER")])
        self.assertEqual((res.final, res.deciding_rule, res.escalate),
                         ("DEFER", 1, True))

    def test_rule1_beats_rule2_first_match_decides(self):
        res = aggregate([
            decided(defect("d1"), "REAL"),
            decided(defect("d2"), "DEFER"),
        ])
        self.assertEqual((res.final, res.deciding_rule), ("DEFER", 1))

    def test_rule2_material_defect_real_fails(self):
        res = aggregate([
            decided(defect("d1"), "REAL"),
            decided(reassurance("r1"), "REAL"),
        ])
        self.assertEqual((res.final, res.deciding_rule, res.escalate),
                         ("FAIL", 2, False))

    def test_rule3_material_reassurance_not_real_fails(self):
        res = aggregate([
            decided(defect("d1"), "NOT_REAL"),
            decided(reassurance("r1"), "NOT_REAL"),
        ])
        self.assertEqual((res.final, res.deciding_rule), ("FAIL", 3))

    def test_rule4_unresolved_contradiction_defers(self):
        res = aggregate([
            decided(defect("d1"), "NOT_REAL", contradicted=True),
            decided(reassurance("r1"), "REAL"),
        ])
        self.assertEqual((res.final, res.deciding_rule), ("DEFER", 4))

    def test_rule4_yields_to_rule2_in_fixed_order(self):
        res = aggregate([
            decided(defect("d1"), "REAL", contradicted=True),
        ])
        self.assertEqual((res.final, res.deciding_rule), ("FAIL", 2))

    def test_rule5_clean_set_passes(self):
        res = aggregate([
            decided(defect("d1"), "NOT_REAL"),
            decided(reassurance("r1"), "REAL"),
        ])
        self.assertEqual((res.final, res.deciding_rule), ("PASS", 5))
        self.assertIsNone(res.fallback_label)

    def test_rule5_empty_set_passes(self):
        res = aggregate([])
        self.assertEqual((res.final, res.deciding_rule), ("PASS", 5))

    def test_supporting_claims_never_swing_verdict(self):
        res = aggregate([
            decided(defect("d1"), "NOT_REAL"),
            decided(reassurance("r1"), "REAL"),
            decided(defect("s1", materiality="supporting"), "REAL"),
            decided(reassurance("s2", materiality="supporting"), "NOT_REAL"),
            decided(defect("s3", materiality="supporting"), "DEFER"),
        ])
        self.assertEqual((res.final, res.deciding_rule), ("PASS", 5))
        self.assertIn("confidence only", res.confidence_note)

    def test_supporting_defer_does_not_trigger_rule1(self):
        res = aggregate([
            decided(defect("d1"), "NOT_REAL"),
            decided(defect("s1", materiality="supporting"), "DEFER"),
        ])
        self.assertEqual((res.final, res.deciding_rule), ("PASS", 5))


class FallbackTests(unittest.TestCase):
    """NON-JEV FALLBACK labeling."""

    def test_fallback_labels_non_jev(self):
        res = non_jev_fallback("FAIL", note="jev transport refused")
        self.assertEqual(res.final, "FAIL")
        self.assertEqual(res.deciding_rule, 0)
        self.assertEqual(res.fallback_label, FALLBACK_LABEL)
        self.assertEqual(FALLBACK_LABEL, "NON-JEV FALLBACK")
        self.assertNotIn("Jev-primary", res.confidence_note)

    def test_fallback_rejects_unknown_consensus(self):
        with self.assertRaises(ValueError):
            non_jev_fallback("MAYBE")

    def test_invalid_inputs_rejected(self):
        with self.assertRaises(ValueError):
            ClaimInput(claim_id="x", claim_text="x", polarity="vibe",
                       materiality="material")
        with self.assertRaises(ValueError):
            ClaimInput(claim_id="x", claim_text="x", polarity="defect",
                       materiality="critical")
