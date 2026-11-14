"""#340: measured spend metric + billed-but-unusable liability.

Hermetic: stubbed provider ``usage.cost`` vs a fake key-usage delta, tmp-dir
ledgers, recording fake governors. No network, no keys.

Ground-truth framing (issue #340 recon): the efficiency experiment's
key-usage delta is the spend that was actually billed; the harness-reported
sum understated it (worst case reported $0.00015 vs key-measured $0.00142).
Recon correction: reported costs come from the provider ``usage.cost``
fields, not stale catalog snapshots -- the gap is billed-but-unusable
responses recorded at $0.
"""
import os
import tempfile
import unittest
from unittest import mock

from harness.capability import (
    CapabilityProfile,
    cost_per_capability,
    measured_spend_by_model,
)
from harness.chat import governed_completion
from harness.errors import HarnessError
from harness.ledger import AutonomyLedger

# Fake key-usage meter standing in for GET /auth/key deltas (no network):
# the stubbed usage.cost below reads $0 while the key moved.
FAKE_KEY_DELTA_USD = 0.00142
FAKE_REPORTED_WORST_USD = 0.00015


def _profile(model_id="paid/model-x"):
    return CapabilityProfile(
        model_id,
        context_length=131072,
        free=False,
        prompt_price=1e-7,
        completion_price=4e-7,
        supports_reasoning=True,
        supports_structured_json=True,
    )


def _chat_resp(content, cost):
    return {"choices": [{"message": {"content": content},
                         "finish_reason": "stop"}],
            "usage": {"cost": cost, "prompt_tokens": 2000,
                      "completion_tokens": 100, "is_byok": False}}


class CostReportMeasuredTests(unittest.TestCase):
    def _ledger(self, tmp):
        ledger = AutonomyLedger(os.path.join(tmp, "ledger.jsonl"))
        ledger.append("offer", task_id="t1",
                      model="deepseek/deepseek-v4.1-flash")
        ledger.append(
            "model_result",
            task_id="t1",
            model="deepseek/deepseek-v4.1-flash",
            lane="apply",
            input_tokens=2000,
            output_tokens=1000,
            cost=0.0,
        )
        ledger.append(
            "model_result",
            task_id="t1",
            model="z-ai/glm-5.3-flash",
            lane="judge",
            input_tokens=1000,
            output_tokens=200,
            cost=0.0005,
        )
        ledger.append("complete", task_id="t1",
                      model="deepseek/deepseek-v4.1-flash")
        return ledger

    def test_success_metric_reads_measured_and_retains_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = self._ledger(tmp)
            price_table = {
                "deepseek/deepseek-v4.1-flash": {
                    "prompt_per_token": 1e-7,
                    "completion_per_token": 4e-7,
                }
            }
            rep = ledger.cost_report(price_table=price_table)
            # All-in view preserved: catalog estimate still pads the total.
            self.assertAlmostEqual(rep["total_cost"], 0.0011, places=6)
            # Measured/estimated provenance is now separate ...
            self.assertAlmostEqual(rep["measured_cost"], 0.0005, places=6)
            self.assertAlmostEqual(rep["estimated_cost"], 0.0006, places=6)
            # ... and cost-per-success reads measured only.
            self.assertEqual(rep["rolling"]["verified_lanes"], 1)
            self.assertAlmostEqual(
                rep["rolling"]["cost_per_verified_lane"], 0.0005, places=6)
            # The unexplained drift stays visible, not silently absorbed.
            self.assertAlmostEqual(
                rep["total_cost"] - rep["measured_cost"],
                rep["estimated_cost"], places=6)


class SelectorMeasuredTests(unittest.TestCase):
    def _entries(self):
        return [
            {"event": "model_result", "task_id": "t1",
             "model": "paid/model-x", "cost": 0.001, "billable_cost": 0.001},
            {"event": "model_result", "task_id": "t2",
             "model": "paid/model-x:free", "cost": 0.0},
            {"event": "model_result", "task_id": "t3",
             "model": "paid/model-x", "cost": 0.003},
            {"event": "model_result", "task_id": "t4",
             "model": "paid/other", "cost": 0.010},
            {"event": "complete", "task_id": "t1", "model": "paid/model-x"},
        ]

    def test_measured_spend_sums_settled_per_canonical_model(self):
        by_model = measured_spend_by_model(self._entries())
        # billable_cost preferred, cost fallback, :free variant canonicalized.
        self.assertAlmostEqual(by_model["paid/model-x"], 0.004, places=6)
        self.assertAlmostEqual(by_model["paid/other"], 0.010, places=6)
        # Rows with no carried spend contribute nothing.
        self.assertNotIn("paid/unseen", by_model)

    def test_cost_per_capability_carries_measured_cost_per_success(self):
        report = {"calibration": {"paid/model-x": {
            "success_pass": 2, "success_fail": 1, "success_rate": 0.5,
            "samples": 3,
        }}}
        res = cost_per_capability(
            _profile(), None, report=report,
            ledger=self._entries(), lane="apply")
        self.assertAlmostEqual(res["measured_spend"], 0.004, places=6)
        self.assertEqual(res["measured_successes"], 2)
        self.assertAlmostEqual(
            res["measured_usd_per_success"], 0.002, places=6)

    def test_selector_ranking_inputs_unchanged_by_ledger(self):
        report = {"calibration": {"paid/model-x": {
            "success_pass": 2, "success_fail": 1,
        }}}
        with_ledger = cost_per_capability(
            _profile(), None, report=report,
            ledger=self._entries(), lane="apply")
        without_ledger = cost_per_capability(
            _profile(), None, report=report, lane="apply")
        for key in ("effective_usd", "usd_per_capability", "value_ratio",
                    "effective_capability", "reliability"):
            self.assertEqual(with_ledger[key], without_ledger[key],
                             f"ranking input {key} must not move")
        self.assertIsNone(without_ledger["measured_usd_per_success"])

    def test_no_successes_yields_null_ratio(self):
        res = cost_per_capability(
            _profile(), None, report={"calibration": {}},
            ledger=self._entries(), lane="apply")
        self.assertAlmostEqual(res["measured_spend"], 0.004, places=6)
        self.assertEqual(res["measured_successes"], 0)
        self.assertIsNone(res["measured_usd_per_success"])


class GovernedZeroCostLiabilityTests(unittest.TestCase):
    def _gov(self, preflight_outcome=(0.004, [])):
        gov = mock.Mock()
        gov.check_byok.return_value = None
        gov.preflight.return_value = preflight_outcome
        gov.retain_unknown.return_value = 0.004
        return gov

    def test_empty_body_zero_cost_retains_liability(self):
        # Stubbed usage.cost $0 while the fake key delta is nonzero: the
        # billed-but-unusable response must hold liability, not book $0.
        self.assertGreater(FAKE_KEY_DELTA_USD, FAKE_REPORTED_WORST_USD)
        gov = self._gov()
        with mock.patch("harness.chat.chat",
                        return_value=(200, _chat_resp("", 0.0))):
            with self.assertRaisesRegex(HarnessError, "empty response body"):
                governed_completion(
                    mock.Mock(), "k", gov, "paid/x", "question", 128)
        gov.retain_unknown.assert_called_once_with(0.004, "paid/x")
        gov.record_actual.assert_not_called()

    def test_empty_body_reported_cost_records_actual_no_liability(self):
        gov = self._gov()
        with mock.patch("harness.chat.chat",
                        return_value=(200, _chat_resp("", 0.002))):
            with self.assertRaisesRegex(HarnessError, "empty response body"):
                governed_completion(
                    mock.Mock(), "k", gov, "paid/x", "question", 128)
        gov.record_actual.assert_called_once_with(0.002, "paid/x")
        gov.retain_unknown.assert_not_called()

    def test_usable_zero_cost_records_nothing(self):
        gov = self._gov()
        with mock.patch("harness.chat.chat",
                        return_value=(200, _chat_resp("ok", 0.0))):
            completion = governed_completion(
                mock.Mock(), "k", gov, "paid/x", "question", 128)
        self.assertEqual(completion["content"], "ok")
        gov.retain_unknown.assert_not_called()
        gov.record_actual.assert_not_called()

    def test_minimal_governor_without_retain_unknown_is_safe(self):
        gov = mock.Mock(spec=["check_byok", "preflight", "record_actual"])
        gov.check_byok.return_value = None
        gov.preflight.return_value = None
        with mock.patch("harness.chat.chat",
                        return_value=(200, _chat_resp("", 0.0))):
            with self.assertRaisesRegex(HarnessError, "empty response body"):
                governed_completion(
                    mock.Mock(), "k", gov, "paid/x", "question", 128)

    def test_free_tier_worst_case_is_noop(self):
        gov = self._gov(preflight_outcome=(0.0, []))
        with mock.patch("harness.chat.chat",
                        return_value=(200, _chat_resp("", 0.0))):
            with self.assertRaisesRegex(HarnessError, "empty response body"):
                governed_completion(
                    mock.Mock(), "k", gov, "paid/x", "question", 128)
        gov.retain_unknown.assert_not_called()

    def test_retain_failure_never_masks_empty_body(self):
        gov = self._gov()
        gov.retain_unknown.side_effect = HarnessError("ceiling")
        with mock.patch("harness.chat.chat",
                        return_value=(200, _chat_resp("", 0.0))):
            with self.assertRaisesRegex(HarnessError, "empty response body"):
                governed_completion(
                    mock.Mock(), "k", gov, "paid/x", "question", 128)
        gov.record_actual.assert_not_called()


if __name__ == "__main__":
    unittest.main()
