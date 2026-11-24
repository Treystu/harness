"""Jev claim-support evaluator owner (#309).

``tests/test_jev_claims_support.py`` pins the JEV-P3 claim-flag behaviour
through ``JevPolicy.evaluate_claim_support``. These tests pin the boundary the
#309 split declares: the family lives in ``harness/jev_claims.py``, the policy
class delegates to it, and the advisory-only rules the family owns still hold.
"""
import ast
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from harness import jev_claims
from harness.config import load_settings
from harness.errors import ProviderUsageUnknown, ToolCancelled
from harness.jev import JevEvaluationResult
from harness.jev_policy import JevPolicy, policy_for
from harness.ledger import AutonomyLedger
from harness.provider_errors import ProviderSpendLimitError

FAMILY = ("evaluate_claim_support",)


class _CountingGovernor:
    def __init__(self):
        self.max_cost = 1.0
        self.spent = 0.0

    def reserve(self, worst, label):
        return {"label": label, "worst": worst}

    def release(self, reservation):
        return None

    def reconcile(self, reservation, cost):
        self.spent += float(cost or 0.0)

    def record_actual(self, cost, model):
        self.spent += float(cost or 0.0)


class _RaisingEvaluator:
    api_key = "jev-key"
    model = "jev-test"

    def __init__(self, error):
        self.error = error

    def evaluate(self, state, questions=None):
        raise self.error


def _owner_source():
    """Read the owner's source once, closing the handle (R13 runs with
    ``-W error::ResourceWarning``)."""
    return Path(jev_claims.__file__).read_text(encoding="utf-8")


class FamilyOwnershipTests(unittest.TestCase):
    def test_owner_defines_the_family(self):
        tree = ast.parse(_owner_source())
        defined = {node.name for node in tree.body
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        missing = [name for name in FAMILY if name not in defined]
        self.assertEqual(missing, [], f"jev_claims no longer defines {missing}")

    def test_owner_function_is_a_plain_function(self):
        # A ``@staticmethod`` left on a module-level def is a no-op callable
        # on 3.10+ and a TypeError on 3.9, so the version-independent check
        # is the object's type.
        self.assertIs(type(jev_claims.evaluate_claim_support),
                      types.FunctionType)

    def test_policy_delegates_to_the_owner(self):
        sentinel = (object(), object())
        claims = ["the ledger is append-only"]
        with patch("harness.jev_policy._evaluate_claim_support",
                   return_value=sentinel) as owner:
            policy = policy_for(load_settings({"jev_api_key": "jev-key"}))
            self.assertIs(
                policy.evaluate_claim_support(claims, "ctx", enabled=True),
                sentinel)
        args, kwargs = owner.call_args
        self.assertIs(args[0], policy)
        self.assertIs(args[1], claims)
        self.assertEqual(args[2], "ctx")
        self.assertTrue(kwargs["enabled"])
        self.assertEqual(kwargs["site"], "claims")
        self.assertEqual(kwargs["max_input_tokens"], 4096)

    def test_owner_does_not_import_the_policy_at_module_scope(self):
        tree = ast.parse(_owner_source())
        offenders = [node.lineno for node in tree.body
                     if isinstance(node, ast.ImportFrom)
                     and (node.module or "").endswith("jev_policy")]
        self.assertEqual(
            offenders, [], "jev_claims imports the policy at module scope")


class ClaimContractTests(unittest.TestCase):
    """The advisory-only rules the family owns survive the move."""

    def test_disabled_and_empty_paths_skip_without_a_call(self):
        policy = JevPolicy(load_settings({"jev_api_key": "jev-key"}))
        result, structural = policy.evaluate_claim_support(
            ["a claim"], "ctx", enabled=False)
        self.assertTrue(result.is_fallback)
        self.assertEqual(result.fallback_reason, "claims_skipped")
        self.assertTrue(structural["skipped"])
        self.assertEqual(structural["claim_flags"], [])
        result, structural = policy.evaluate_claim_support([], "ctx",
                                                           enabled=True)
        self.assertTrue(structural["skipped"])

    def test_live_flags_read_both_answer_shapes(self):
        class _AnswersEvaluator:
            api_key = "jev-key"
            model = "jev-test"

            def evaluate(self, state, questions=None):
                return JevEvaluationResult(
                    "pass", 0.9, 0.9,
                    {"claim_0_supported": 0.8,
                     "claim_1_supported": {"noul": 0.2},
                     "claim_2_supported": "unusable"},
                    [], cost=0.0, input_tokens=5, output_tokens=5,
                    model="jev-test")

        with tempfile.TemporaryDirectory() as tmp:
            policy = JevPolicy(
                load_settings({"jev_api_key": "jev-key"}),
                evaluator=_AnswersEvaluator(), governor=_CountingGovernor(),
                ledger=AutonomyLedger(os.path.join(tmp, "ledger.jsonl")))
            result, structural = policy.evaluate_claim_support(
                ["a", "b", "c"], "ctx", enabled=True)
        self.assertFalse(result.is_fallback)
        self.assertFalse(structural["skipped"])
        flags = structural["claim_flags"]
        self.assertEqual([f["supported"] for f in flags], [True, False, None])
        self.assertEqual([f["noul"] for f in flags][:2], [0.8, 0.2])
        self.assertEqual([f["id"] for f in flags],
                         ["claim_0", "claim_1", "claim_2"])

    def test_unkeyed_fallback_flags_stay_unknown(self):
        policy = policy_for(load_settings())
        result, structural = policy.evaluate_claim_support(
            ["the ledger is append-only", "the tests pass"], "ctx",
            enabled=True)
        self.assertTrue(result.is_fallback)
        self.assertFalse(structural["skipped"])
        self.assertEqual(len(structural["claim_flags"]), 2)
        for flag in structural["claim_flags"]:
            with self.subTest(claim=flag["id"]):
                self.assertIsNone(flag["supported"])
                self.assertTrue(flag["fallback"])


class ClaimSettlementTests(unittest.TestCase):
    def _raising_policy(self, ledger, error):
        return JevPolicy(
            load_settings({"jev_api_key": "jev-key"}),
            evaluator=_RaisingEvaluator(error),
            governor=_CountingGovernor(), ledger=ledger)

    def test_usage_unknown_settles_and_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = self._raising_policy(
                AutonomyLedger(os.path.join(tmp, "ledger.jsonl")),
                ProviderUsageUnknown("usage lost", known_cost=0.0))
            with self.assertRaises(ProviderUsageUnknown):
                policy.evaluate_claim_support(["a claim"], "ctx", enabled=True)

    def test_tool_cancelled_settles_and_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = self._raising_policy(
                AutonomyLedger(os.path.join(tmp, "ledger.jsonl")),
                ToolCancelled("cancelled"))
            with self.assertRaises(ToolCancelled):
                policy.evaluate_claim_support(["a claim"], "ctx", enabled=True)

    def test_provider_spend_limit_releases_and_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = self._raising_policy(
                AutonomyLedger(os.path.join(tmp, "ledger.jsonl")),
                ProviderSpendLimitError("cap", http_status=402))
            with self.assertRaises(ProviderSpendLimitError):
                policy.evaluate_claim_support(["a claim"], "ctx", enabled=True)


if __name__ == "__main__":
    unittest.main()
