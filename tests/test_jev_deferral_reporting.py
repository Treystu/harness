"""#489 residue item 2: fallback deferrals and statistical deferrals separate.

The defect class under test is the draft's own gate false-pass: a report whose
table states something the code never checks. Here the report must account for
every deferred verdict in exactly one class, must count a record it cannot
classify as `unattributed` rather than drop it, must count a record with no
confidence at all (every fallback has none), and must compute no rate it has
no sample for. No threshold is written anywhere in the module.
"""
import unittest

from harness.jev_calibration import (_class_totals, analyze_judgments,
                                    classify_route_reason, deferral_report,
                                    format_report)


class ClassifyTests(unittest.TestCase):
    def test_every_emitted_panel_reason_is_a_fallback(self):
        for reason in ("jev_error: timeout", "jev_fallback: rate_limited",
                       "jev_policy_absent", "jev_no_claims",
                       "jev_status_missing", "jev_not_run"):
            self.assertEqual(classify_route_reason(reason), "fallback", reason)

    def test_a_real_jev_deferral_is_statistical(self):
        self.assertEqual(classify_route_reason("jev_defer: below_gate"),
                         "statistical")

    def test_an_unknown_reason_is_unattributed_not_folded_into_fallback(self):
        self.assertEqual(classify_route_reason("jev_new_thing"), "unattributed")

    def test_absent_or_blank_reason_is_none(self):
        for reason in (None, "", "   "):
            self.assertIsNone(classify_route_reason(reason))


class DeferralReportTests(unittest.TestCase):
    def _entries(self):
        return [
            {"judgment_route": "jev_primary", "confidence": 0.91},
            {"judgment_route": "llm_fallback", "judgment_route_reason": "jev_error: 500"},
            {"judgment_route": "llm_fallback",
             "judgment_route_reason": "jev_fallback: account_rate_limited"},
            {"judgment_route": "llm_fallback",
             "judgment_route_reason": "jev_defer: confidence_below_gate",
             "confidence": 0.4},
            {"judgment_route": "llm_fallback",
             "judgment_route_reason": "jev_something_new"},
            # No confidence, no route: a plain record -- must still be counted
            # as an entry, never silently discarded.
            {"verdict": "pass", "confidence": None},
        ]

    def test_classes_account_for_every_deferred_verdict(self):
        report = deferral_report(self._entries())
        self.assertEqual(report["n_entries"], 6)
        self.assertEqual(report["n_verdicts"], 5)
        self.assertEqual(report["n_primary"], 1)
        self.assertEqual(report["n_fallback"], 4)
        self.assertEqual(report["by_class"],
                         {"fallback": 2, "statistical": 1, "unattributed": 1})
        self.assertEqual(sum(report["by_class"].values()), report["n_fallback"])

    def test_unattributed_reasons_are_named(self):
        report = deferral_report(self._entries())
        self.assertEqual(report["unattributed_reasons"], ["jev_something_new"])
        self.assertEqual(report["by_reason"]["jev_something_new"], 1)

    def test_report_carries_no_threshold_and_no_rate(self):
        report = deferral_report(self._entries())
        keys = " ".join(sorted(report)).lower()
        for forbidden in ("threshold", "min_confidence", "accuracy", "rate"):
            self.assertNotIn(forbidden, keys)

    def test_empty_stream_is_advisory(self):
        report = deferral_report([])
        self.assertEqual(report["n_verdicts"], 0)
        self.assertEqual(report["by_class"],
                         {"fallback": 0, "statistical": 0, "unattributed": 0})
        self.assertIn("advisory only", report["notes"][0])

    def test_a_class_counter_that_does_not_add_up_is_refused(self):
        # The guard for the draft's defect class: a figure the report shows
        # must be one the code can account for.
        with self.assertRaises(ValueError):
            _class_totals({"fallback": 1, "statistical": 1, "unattributed": 0,
                           "invented": 3})


class AnalyzeJudgmentsTests(unittest.TestCase):
    def test_records_with_a_reason_carry_the_separation(self):
        report = analyze_judgments([
            {"confidence": 0.9, "disposition": "proceed",
             "route_reason": "jev_error: 502"},
            {"confidence": 0.4, "disposition": "escalate",
             "route_reason": "jev_defer: below_gate"},
        ])
        self.assertEqual(report["deferral_n"], 2)
        self.assertEqual(report["by_deferral_class"],
                         {"fallback": 1, "statistical": 1, "unattributed": 0})
        self.assertIn("deferral classes (n=2)", format_report(report))

    def test_records_without_a_reason_are_unchanged(self):
        report = analyze_judgments([{"confidence": 0.9,
                                     "disposition": "proceed"}])
        self.assertNotIn("by_deferral_class", report)
        self.assertNotIn("deferral classes", format_report(report))

    def test_a_blank_reason_is_rejected_rather_than_treated_as_absent(self):
        with self.assertRaises(ValueError):
            analyze_judgments([{"confidence": 0.9, "route_reason": "  "}])

    def test_measurement_only_no_threshold_is_written(self):
        import harness.jev_calibration as cal
        report = analyze_judgments([{"confidence": 0.5,
                                     "route_reason": "jev_defer: low"}])
        self.assertNotIn("min_confidence", report)
        self.assertNotIn("threshold", " ".join(sorted(report)).lower())
        for name in ("freeze_jev_settings", "set_min_confidence"):
            self.assertFalse(hasattr(cal, name))


if __name__ == "__main__":
    unittest.main()
