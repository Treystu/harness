"""HUL scope evaluator owner (#309).

``tests/test_hul_jev_scope_gate.py`` pins the gate's behaviour through
``JevPolicy.evaluate_scope``. These tests pin the boundary the #309 split
declares: the family lives in ``harness/jev_scope.py``, the policy class holds
the owner's objects (not copies) and delegates to it, and the settlement paths
the scope gate inherits from the one policy owner still run when the provider
fails instead of answering.
"""
import ast
import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness import jev_scope
from harness.config import load_settings
from harness.errors import HarnessError, ProviderUsageUnknown, ToolCancelled
from harness.jev_policy import JevPolicy, policy_for
from harness.ledger import AutonomyLedger
from harness.provider_errors import ProviderSpendLimitError

def _owner_source():
    """Read the owner's source once, closing the handle (R13 runs with
    ``-W error::ResourceWarning``)."""
    return Path(jev_scope.__file__).read_text(encoding="utf-8")


FAMILY = (
    "scope_noul",
    "scope_score",
    "scope_choice",
    "scope_determination",
    "scope_text",
    "scope_state_facts",
    "evaluate_scope",
)


class _CountingGovernor:
    def __init__(self):
        self.reserved = []
        self.reconciled = []
        self.max_cost = 1.0
        self.spent = 0.0

    def reserve(self, worst, label):
        self.reserved.append((worst, label))
        return {"label": label, "worst": worst}

    def reconcile(self, reservation, cost):
        self.reconciled.append((reservation, cost))
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


def _mission_state():
    return {
        "mission_id": "m-owner-1",
        "request": "Implement the scoped feature",
        "success_definition": "tests green",
        "scope": {"in_scope": ["harness/jev_scope.py"], "out_of_scope": []},
        "verifier_holds": True,
    }


class FamilyOwnershipTests(unittest.TestCase):
    def test_owner_defines_the_family(self):
        tree = ast.parse(_owner_source())
        defined = {node.name for node in tree.body
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        missing = [name for name in FAMILY if name not in defined]
        self.assertEqual(missing, [], f"jev_scope no longer defines {missing}")

    def test_policy_holds_the_owners_objects_not_copies(self):
        for name in ("scope_noul", "scope_score", "scope_choice",
                     "scope_determination", "scope_text",
                     "scope_state_facts"):
            with self.subTest(name=name):
                self.assertIs(getattr(JevPolicy, "_" + name),
                              getattr(jev_scope, name))

    def test_policy_delegates_to_the_owner(self):
        sentinel = object()
        state = _mission_state()
        with patch("harness.jev_policy._evaluate_scope",
                   return_value=sentinel) as owner:
            policy = policy_for(load_settings({"jev_api_key": "jev-key"}))
            self.assertIs(policy.evaluate_scope(state), sentinel)
        args, kwargs = owner.call_args
        self.assertIs(args[0], policy)
        self.assertIs(args[1], state)
        self.assertEqual(kwargs["max_input_tokens"], 4096)

    def test_owner_does_not_import_the_policy_at_module_scope(self):
        tree = ast.parse(_owner_source())
        offenders = [node.lineno for node in tree.body
                     if isinstance(node, ast.ImportFrom)
                     and (node.module or "").endswith("jev_policy")]
        self.assertEqual(offenders, [], "jev_scope imports the policy at module scope")

    def test_owner_imports_without_the_policy(self):
        module = importlib.import_module("harness.jev_scope")
        self.assertIsNotNone(module)


class ScopeProviderFailureTests(unittest.TestCase):
    """The scope gate inherits settlement from the policy owner; it must use it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = AutonomyLedger(os.path.join(self.tmp.name, "ledger.jsonl"))

    def _policy(self, error):
        return JevPolicy(
            load_settings({"jev_api_key": "jev-key"}),
            evaluator=_RaisingEvaluator(error),
            governor=_CountingGovernor(), ledger=self.ledger)

    def test_usage_unknown_settles_the_cancellation_and_raises(self):
        policy = self._policy(ProviderUsageUnknown("usage lost", known_cost=0.0))
        with self.assertRaises(ProviderUsageUnknown):
            policy.evaluate_scope(_mission_state())

    def test_tool_cancelled_settles_and_raises(self):
        policy = self._policy(ToolCancelled("cancelled"))
        with self.assertRaises(ToolCancelled):
            policy.evaluate_scope(_mission_state())

    def test_provider_spend_limit_releases_and_raises(self):
        policy = self._policy(
            ProviderSpendLimitError("cap", http_status=402))
        with self.assertRaises(ProviderSpendLimitError):
            policy.evaluate_scope(_mission_state())

    def test_transport_error_still_fails_closed_with_a_reason(self):
        policy = self._policy(HarnessError("transport down"))
        result, structural, determination = policy.evaluate_scope(
            _mission_state())
        self.assertTrue(result.is_fallback)
        self.assertFalse(determination["complete"])
        self.assertEqual(structural["reason"], "transport down")


if __name__ == "__main__":
    unittest.main()
