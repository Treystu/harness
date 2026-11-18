"""#588: a billed Jev call can no longer lose its receipt silently.

The issue's evidence was an A/B: five live ``jev-1.14.0`` calls through
``session.jev_for(settings, governor=...)`` spent real money and wrote zero
``jev_eval`` rows, while the same calls with ``ledger=ledger_for(...)`` wrote
exactly one row each. Nothing in the return value said the receipt was
missing. These tests pin both halves of the cure: the sanctioned composition
now attaches the configured ledger by itself, and a composition that truly has
no ledger says so instead of going quiet.
"""
import io
import json
import os
import tempfile
import types
import unittest
from contextlib import redirect_stderr

from harness.jev_policy import JevEvaluationResult, policy_for
from harness.ledger import AutonomyLedger
from harness.session import jev_for, ledger_for, maybe_ledger_for


def _settings(tmp, **overrides):
    values = {
        "jev_api_key": None,
        "ledger_path": os.path.join(tmp, "ledger.jsonl"),
    }
    values.update(overrides)
    from harness.config import load_settings
    return load_settings(values)


def _paid_result(cost=0.00003):
    return JevEvaluationResult(
        "pass", 0.87, 0.9, {"support": 0.9}, ["evidence"], cost=cost,
        input_tokens=800, output_tokens=40, model="jev-test")


class JevForAttachesTheLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="harness-jev-588-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, True)

    def test_omitting_the_ledger_attaches_the_configured_one(self):
        settings = _settings(self.tmp)
        policy = jev_for(settings)
        self.assertIsNotNone(policy.ledger)
        self.assertEqual(str(policy.ledger.path), str(settings.ledger_path))

    def test_the_supplied_caller_tags_the_ledger(self):
        policy = jev_for(_settings(self.tmp), caller="audit_claims")
        self.assertEqual(policy.ledger.caller, "audit_claims")

    def test_the_caller_option_is_not_forwarded_to_the_policy(self):
        # JevPolicy does not take ``caller``; forwarding it would be a
        # TypeError, so this also proves the option is consumed here.
        with self.assertRaises(TypeError):
            jev_for(_settings(self.tmp), caller="audit", nonsense_knob=1)
        self.assertIsNotNone(jev_for(_settings(self.tmp), caller="audit").ledger)

    def test_an_explicit_ledger_wins(self):
        with tempfile.TemporaryDirectory() as other:
            explicit = AutonomyLedger(os.path.join(other, "explicit.jsonl"))
            policy = jev_for(_settings(self.tmp), ledger=explicit)
        self.assertIs(policy.ledger, explicit)

    def test_no_configured_path_means_no_fabricated_ledger(self):
        # ``load_settings`` always names a path, so the guard is exercised on
        # the settings shape that genuinely has none.
        bare = types.SimpleNamespace(ledger_path=None)
        self.assertIsNone(maybe_ledger_for(bare))
        self.assertIsNone(maybe_ledger_for(types.SimpleNamespace()))

    def test_a_defaulted_ledger_writes_exactly_one_row_per_call(self):
        settings = _settings(self.tmp)
        policy = jev_for(settings, caller="audit_claims")
        result = _paid_result()
        first = policy._account(result, site="audit_claims")
        second = policy._account(_paid_result(), site="audit_claims")
        self.assertIn("discarded", first)
        self.assertIn("discarded", second)
        rows = [json.loads(line) for line in
                open(policy.ledger.path, encoding="utf-8") if line.strip()]
        evals = [row for row in rows if row.get("event") == "jev_eval"]
        self.assertEqual(len(evals), 2)
        self.assertEqual(evals[0]["site"], "audit_claims")
        self.assertEqual(evals[0]["caller"], "audit_claims")
        self.assertGreater(evals[0]["cost"], 0.0)


class MissingLedgerIsVisibleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="harness-jev-588-noledger-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, True)

    def _policy_without_ledger(self):
        # Direct composition, the one shape that can still be ledger-free.
        return policy_for(_settings(self.tmp), ledger=None)

    def test_a_paid_call_without_a_ledger_warns_once_naming_the_site(self):
        policy = self._policy_without_ledger()
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            policy._account(_paid_result(), site="audit_claims")
            policy._account(_paid_result(), site="audit_claims")
        text = stderr.getvalue()
        self.assertEqual(text.count("[jev] WARNING:"), 1)
        self.assertIn("audit_claims", text)
        self.assertIn("no jev_eval row was written", text)
        self.assertIn("ledger=", text)

    def test_a_zero_cost_call_does_not_warn(self):
        policy = self._policy_without_ledger()
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            policy._account(_paid_result(cost=0.0), site="audit_claims")
        self.assertNotIn("WARNING", stderr.getvalue())

    def test_the_warning_is_per_policy_not_per_process(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self._policy_without_ledger()._account(_paid_result(), site="a")
            self._policy_without_ledger()._account(_paid_result(), site="b")
        self.assertEqual(stderr.getvalue().count("[jev] WARNING:"), 2)

    def test_ledger_for_is_the_documented_way_to_supply_one(self):
        settings = _settings(self.tmp)
        ledger = ledger_for(settings, caller="audit")
        policy = jev_for(settings, ledger=ledger)
        self.assertIs(policy.ledger, ledger)
        self.assertEqual(ledger.caller, "audit")


if __name__ == "__main__":
    unittest.main()
