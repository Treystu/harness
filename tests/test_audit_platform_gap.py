"""The audit states environment failures as environment failures (#454).

A check that could not run on this machine must not read as a verdict on the
code. These tests pin the marker, the score, and the two live paths that can
only fail for an environment reason.
"""
import unittest
from unittest import mock

from audits.self import audit
from harness.errors import HarnessError


class PlatformGapTests(unittest.TestCase):
    def test_the_line_names_the_missing_fact_and_the_marker(self):
        score, evidence = audit.platform_gap(
            "a resolvable ruff", "S5 ruff unresolved: boom")
        self.assertEqual(score, 0.0, "an unmeasured check is not a pass")
        self.assertIn(audit.PLATFORM_GAP, evidence)
        self.assertIn("a resolvable ruff", evidence)
        self.assertIn("S5 ruff unresolved: boom", evidence)

    def test_a_fact_without_detail_still_states_the_gap(self):
        _, evidence = audit.platform_gap("git objects")
        self.assertIn(audit.PLATFORM_GAP, evidence)
        self.assertNotIn(": ", evidence.split("needs ")[1])

    def test_the_status_vocabulary_reads_it_as_a_failure_not_a_skip(self):
        _, evidence = audit.platform_gap("a traced interpreter")
        self.assertEqual(audit._status(0.0, evidence), "FAIL")
        self.assertNotEqual(audit._status(0.0, evidence), "pass")

    def test_an_unresolved_ruff_is_reported_as_a_platform_gap(self):
        # HarnessError is the resolver's real refusal when nothing resolves;
        # sm_lint catches exactly that, so the test raises exactly that.
        with mock.patch("harness.tools.ruff_argv",
                        side_effect=HarnessError("no ruff anywhere")):
            score, evidence = audit.sm_lint()
        self.assertEqual(score, 0.0)
        self.assertTrue(evidence.startswith("[" + audit.PLATFORM_GAP + "]"),
                        evidence)
        self.assertIn("no ruff anywhere", evidence)

    def test_d12_absence_names_the_environment_fact_in_both_modes(self):
        score, evidence = audit.d12_coverage_unavailable(
            "no trace support", in_ci=True)
        self.assertEqual(score, 0.0)
        self.assertIn("FAIL:", evidence)
        self.assertIn(audit.PLATFORM_GAP, evidence)

        score, evidence = audit.d12_coverage_unavailable(
            "no trace support", in_ci=False)
        self.assertEqual(score, 1.0, "the local fail-open SKIP is unchanged")
        self.assertIn("SKIP (fail-open)", evidence)
        self.assertIn(audit.PLATFORM_GAP, evidence)


if __name__ == "__main__":
    unittest.main()
