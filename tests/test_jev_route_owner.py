"""Jev model-route evaluator owner (#309).

``tests/test_route_pack.py`` pins the SITE-2 ladder behaviour through
``JevPolicy.evaluate_model_route``. These tests pin the boundary the #309
split declares: the family lives in ``harness/jev_route.py``, the policy class
holds the owner's objects (not copies) and delegates to it, and the
0-hallucination rules the family owns still hold against a ladder.
"""
import ast
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from harness import jev_route
from harness.config import load_settings
from harness.errors import ProviderUsageUnknown, ToolCancelled
from harness.jev_policy import JevPolicy, policy_for
from harness.ledger import AutonomyLedger
from harness.provider_errors import ProviderSpendLimitError
from tests.test_route_faces import _route_pack

FAMILY = ("route_query_text", "evaluate_model_route")


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
    return Path(jev_route.__file__).read_text(encoding="utf-8")


class FamilyOwnershipTests(unittest.TestCase):
    def test_owner_defines_the_family(self):
        tree = ast.parse(_owner_source())
        defined = {node.name for node in tree.body
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        missing = [name for name in FAMILY if name not in defined]
        self.assertEqual(missing, [], f"jev_route no longer defines {missing}")

    def test_owner_helpers_are_plain_functions(self):
        # A ``@staticmethod`` left on a module-level def is a no-op callable
        # on 3.10+ and a TypeError on 3.9, so the version-independent check
        # is the object's type.
        for name in FAMILY:
            with self.subTest(name=name):
                self.assertIs(type(getattr(jev_route, name)), types.FunctionType)

    def test_policy_holds_the_owners_object_and_the_constant(self):
        self.assertIs(JevPolicy._route_query_text, jev_route.route_query_text)
        self.assertEqual(JevPolicy.LOW_CONFIDENCE_FLOOR if hasattr(
            JevPolicy, "LOW_CONFIDENCE_FLOOR") else jev_route.LOW_CONFIDENCE_FLOOR,
            jev_route.LOW_CONFIDENCE_FLOOR)

    def test_policy_delegates_to_the_owner(self):
        sentinel = object()
        pack = _route_pack()
        with patch("harness.jev_policy._evaluate_model_route",
                   return_value=sentinel) as owner:
            policy = policy_for(load_settings({"jev_api_key": "jev-key"}))
            self.assertIs(policy.evaluate_model_route({"goal": "rename a typo"},
                                                      pack),
                          sentinel)
        args, kwargs = owner.call_args
        self.assertIs(args[0], policy)
        self.assertEqual(args[1], {"goal": "rename a typo"})
        self.assertIs(args[2], pack)
        self.assertEqual(kwargs["max_input_tokens"], 4096)

    def test_owner_does_not_import_the_policy_at_module_scope(self):
        tree = ast.parse(_owner_source())
        offenders = [node.lineno for node in tree.body
                     if isinstance(node, ast.ImportFrom)
                     and (node.module or "").endswith("jev_policy")]
        self.assertEqual(offenders, [], "jev_route imports the policy at module scope")


class RouteContractTests(unittest.TestCase):
    """The rules the family owns survive the move."""

    def _policy(self):
        return JevPolicy(load_settings({"jev_api_key": "jev-key"}))

    def test_unkeyed_route_answers_from_the_declared_ladder_only(self):
        policy = self._policy()
        result, structural, combo = policy.evaluate_model_route(
            {"goal": "rename a typo in the docstring"}, _route_pack())
        self.assertTrue(result.is_fallback)
        self.assertEqual(structural["site"], "model_route")
        self.assertEqual(combo["rung_id"], "scout")
        self.assertEqual(combo["model"], "helper-lite")

    def test_declared_tier_rank_and_floor_stay_code_owned(self):
        policy = self._policy()
        result, _structural, combo = policy.evaluate_model_route(
            {"goal": "refactor the multi-module architecture"}, _route_pack())
        # The ladder's top rung is still below the heuristic floor for a
        # frontier-shaped goal: the honest answer is no rung, not a guess.
        self.assertTrue(result.is_fallback)
        self.assertIsNone(combo["rung_id"])

    def test_invalid_pack_fails_closed(self):
        policy = self._policy()
        result, _structural, combo = policy.evaluate_model_route(
            {"goal": "rename"}, {"id": "broken"})
        self.assertTrue(result.is_fallback)
        self.assertEqual(result.fallback_reason, "invalid_pack")
        self.assertIsNone(combo["rung_id"])

    def test_query_text_reads_the_goal_key(self):
        self.assertEqual(jev_route.route_query_text({"goal": "g"}), "g")
        self.assertEqual(jev_route.route_query_text({"query": "q"}), "q")
        self.assertEqual(jev_route.route_query_text("s"), "s")
        self.assertEqual(jev_route.route_query_text({"other": "x"}), "")
        self.assertEqual(jev_route.route_query_text(None), "")
        self.assertEqual(jev_route.route_query_text(3), "3")


class RouteSettlementTests(unittest.TestCase):
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
                policy.evaluate_model_route({"goal": "rename"}, _route_pack())

    def test_tool_cancelled_settles_and_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = self._raising_policy(
                AutonomyLedger(os.path.join(tmp, "ledger.jsonl")),
                ToolCancelled("cancelled"))
            with self.assertRaises(ToolCancelled):
                policy.evaluate_model_route({"goal": "rename"}, _route_pack())

    def test_provider_spend_limit_releases_and_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = self._raising_policy(
                AutonomyLedger(os.path.join(tmp, "ledger.jsonl")),
                ProviderSpendLimitError("cap", http_status=402))
            with self.assertRaises(ProviderSpendLimitError):
                policy.evaluate_model_route({"goal": "rename"}, _route_pack())


if __name__ == "__main__":
    unittest.main()
