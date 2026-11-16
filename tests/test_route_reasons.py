"""Row-14 follow-up: `Router.route` now reports why it picked its first rung.

The historical contract is preserved exactly: no report means the declared
order and the same keys as before. A calibration report turns the returned spec
into a decision that an operator can read -- which is what #280's fourth
acceptance criterion asked for and what the row-14 receipt left as a named
follow-up.
"""
import unittest

from harness.router import Router


def router():
    return Router(panel=["openrouter/free", "cheap/paid-a"], judge="judge/model",
                  apply_model="openrouter/free",
                  panel_pool=["openrouter/free", "cheap/paid-a"],
                  apply_pool=["openrouter/free", "cheap/paid-a"])


CAL = {"calibration": {
    "openrouter/free": {"structured_success_rate": 0.333, "structured_samples": 12,
                        "success_rate": 0.4, "samples": 12},
    "cheap/paid-a": {"structured_success_rate": 0.9, "structured_samples": 12,
                     "success_rate": 0.9, "samples": 12},
}}


class FallbackShapeTests(unittest.TestCase):
    def test_without_a_report_the_spec_is_unchanged(self):
        spec = router().route("verify")
        self.assertEqual(set(spec), {"tier", "panel", "judge"})
        self.assertEqual(spec["panel"], ["openrouter/free", "cheap/paid-a"])

    def test_without_a_report_the_code_spec_is_unchanged(self):
        spec = router().route("code")
        self.assertEqual(set(spec), {"tier", "model", "pool"})
        self.assertEqual(spec["model"], "openrouter/free")

    def test_an_unknown_task_type_still_raises(self):
        with self.assertRaises(ValueError):
            router().route("nonsense")


class CalibrationTests(unittest.TestCase):
    def test_a_measured_challenger_takes_the_first_rung(self):
        spec = router().route("verify", report=CAL)
        self.assertEqual(spec["first_rung"], "cheap/paid-a")
        self.assertEqual(spec["panel"][0], "cheap/paid-a")
        self.assertEqual(spec["source"], "calibration")

    def test_the_reasons_travel_with_the_spec(self):
        spec = router().route("verify", report=CAL)
        self.assertTrue(spec["reasons"])
        self.assertIn("promoted", spec["reasons"][0])

    def test_an_empty_report_keeps_the_declared_head_and_says_so(self):
        spec = router().route("code", report={"calibration": {}})
        self.assertEqual(spec["first_rung"], "openrouter/free")
        self.assertEqual(spec["source"], "declared")
        self.assertIn("no recorded calibration", spec["reasons"][0])


if __name__ == "__main__":
    unittest.main()
