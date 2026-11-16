"""#489 residue item 1: the conformance corpus uses only real pack primitives.

The defect class under test is not a wrong verdict -- it is a corpus written
against a question model this repo does not have. The draft asked a `boolean`
primitive and graded scores by rubric index; both are rejected here, so a
future corpus cannot regress to an invented model in silence.
"""
import unittest

from harness.jev import JevEvaluationResult, _validate_questions, plan_question_pack
from harness.jev_conformance import (CONFORMANCE_CASES, PLAN_EXECUTION_LEGEND,
                                     case_by_id, conformance_report,
                                     validate_case, validated_case_ids)


class PipelinePrimitiveTests(unittest.TestCase):
    def test_every_case_validates_through_the_real_validator(self):
        self.assertEqual(len(validated_case_ids()), len(CONFORMANCE_CASES))
        for case in CONFORMANCE_CASES:
            validate_case(case)  # raises otherwise

    def test_only_implemented_primitives_appear(self):
        allowed = {"noul", "choice", "score"}
        for case in CONFORMANCE_CASES:
            for question in validate_case(case).values():
                self.assertIn(question["type"], allowed, case["id"])

    def test_the_draft_boolean_primitive_is_still_rejected(self):
        # The exact failure the validation run reported for the draft.
        with self.assertRaises(ValueError) as ctx:
            _validate_questions({"x": {"type": "boolean",
                                       "instructions": "is it?",
                                       "criteria": ["yes", "no"]}})
        self.assertIn("unsupported TypeSafe primitive", str(ctx.exception))

    def test_score_cases_reuse_a_production_legend(self):
        production = plan_question_pack()["requirement_complexity"]["criteria"]
        self.assertEqual(PLAN_EXECUTION_LEGEND, production)
        score_cases = [c for c in CONFORMANCE_CASES
                       if any(q["type"] == "score"
                              for q in validate_case(c).values())]
        self.assertTrue(score_cases)
        for case in score_cases:
            for question in validate_case(case).values():
                if question["type"] == "score":
                    self.assertEqual(question["criteria"], production, case["id"])


class AdversarialShapeTests(unittest.TestCase):
    def test_injection_case_answers_near_zero_support(self):
        case = case_by_id("injection_in_candidate")
        self.assertEqual(case["expected"]["verdict"], "fail")
        self.assertLess(
            case["expected"]["answer"]["claim_supported"]["noul"], 0.5)

    def test_numeric_inversion_case_answers_zero(self):
        case = case_by_id("numeric_inversion")
        self.assertEqual(case["expected"]["answer"]["figure_matches"]["noul"], 0.0)

    def test_partial_diff_case_is_a_mid_legend_score(self):
        case = case_by_id("partial_diff")
        answer = case["expected"]["answer"]["implementation_completeness"]
        self.assertGreater(answer["score"], 0.0)
        self.assertLess(answer["score"], len(PLAN_EXECUTION_LEGEND) - 1)

    def test_empty_context_case_names_the_fallback_route(self):
        case = case_by_id("empty_context")
        self.assertEqual(case["expected"]["route_reason"], "jev_no_claims")

    def test_confidence_only_case_escalates_without_a_second_threshold(self):
        case = case_by_id("confidence_only_escalation")
        exp = case["expected"]
        result = JevEvaluationResult(verdict="pass",
                                     confidence=exp["confidence"],
                                     supported=exp["supported"])
        self.assertGreaterEqual(exp["supported"], exp["min_confidence"])
        self.assertLess(exp["confidence"], exp["min_confidence"])
        self.assertFalse(result.is_passing(exp["min_confidence"]))

    def test_confidence_only_case_passes_when_confidence_clears_the_gate(self):
        case = case_by_id("confidence_only_escalation")
        exp = case["expected"]
        ok = JevEvaluationResult(verdict="pass", confidence=0.71,
                                 supported=exp["supported"])
        self.assertTrue(ok.is_passing(exp["min_confidence"]))


class ReportTests(unittest.TestCase):
    def test_report_states_n_for_every_case_and_computes_no_rate(self):
        report = conformance_report()
        self.assertEqual(report["n_cases"], len(CONFORMANCE_CASES))
        for row in report["cases"]:
            self.assertEqual(row["n"], 1, row["id"])
        self.assertEqual(set(report["primitives_seen"]) - {"noul", "choice", "score"},
                         set())
        blob = repr(report).lower()
        for forbidden in ("accuracy", "ece", "brier", "rate="):
            self.assertNotIn(forbidden, blob)

    def test_report_notes_deny_a_sample_reading(self):
        notes = " ".join(conformance_report()["notes"]).lower()
        self.assertIn("n=1 per case", notes)
        self.assertIn("no rate", notes)


if __name__ == "__main__":
    unittest.main()
