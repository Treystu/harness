"""Jev log-item evaluator owner (#309).

``tests/test_jev_log_judgment.py`` pins the JEV-LOG behaviour through
``JevPolicy.evaluate_log_item``. These tests pin the boundary the #309 split
declares: the family lives in ``harness/jev_log.py``, the policy class holds
the owner's objects (not copies) and delegates to it, and the
0-hallucination rules the family owns still hold against a log pack.
"""
import ast
import os
import types
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness import jev_log
from harness.config import load_settings
from harness.errors import ProviderUsageUnknown, ToolCancelled
from harness.jev_policy import JevPolicy, policy_for
from harness.ledger import AutonomyLedger
from harness.provider_errors import ProviderSpendLimitError
from tests.test_jev_log_judgment import sample_log_pack

FAMILY = ("log_item_text", "log_judgment", "evaluate_log_item")


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
    return Path(jev_log.__file__).read_text(encoding="utf-8")


class FamilyOwnershipTests(unittest.TestCase):
    def test_owner_defines_the_family(self):
        tree = ast.parse(_owner_source())
        defined = {node.name for node in tree.body
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        missing = [name for name in FAMILY if name not in defined]
        self.assertEqual(missing, [], f"jev_log no longer defines {missing}")

    def test_policy_holds_the_owners_objects_not_copies(self):
        for name in ("log_item_text", "log_judgment"):
            with self.subTest(name=name):
                self.assertIs(getattr(JevPolicy, "_" + name),
                              getattr(jev_log, name))

    def test_policy_delegates_to_the_owner(self):
        sentinel = object()
        pack = sample_log_pack()
        with patch("harness.jev_policy._evaluate_log_item",
                   return_value=sentinel) as owner:
            policy = policy_for(load_settings({"jev_api_key": "jev-key"}))
            self.assertIs(policy.evaluate_log_item({"item": "swarm dial"}, pack),
                          sentinel)
        args, kwargs = owner.call_args
        self.assertIs(args[0], policy)
        self.assertEqual(args[1], {"item": "swarm dial"})
        self.assertIs(args[2], pack)
        self.assertEqual(kwargs["max_input_tokens"], 4096)

    def test_owner_helpers_are_plain_functions(self):
        # A ``@staticmethod`` left on a module-level def is a no-op callable
        # on 3.10+ and a TypeError on 3.9, so the version-independent check
        # is the object's type.
        for name in FAMILY:
            with self.subTest(name=name):
                self.assertIs(type(getattr(jev_log, name)), types.FunctionType)

    def test_owner_does_not_import_the_policy_at_module_scope(self):
        tree = ast.parse(_owner_source())
        offenders = [node.lineno for node in tree.body
                     if isinstance(node, ast.ImportFrom)
                     and (node.module or "").endswith("jev_policy")]
        self.assertEqual(offenders, [], "jev_log imports the policy at module scope")


class LogContractTests(unittest.TestCase):
    """The rules the family owns survive the move."""

    def _policy(self):
        return JevPolicy(load_settings({"jev_api_key": "jev-key"}))

    def test_unkeyed_keyword_match_binds_pack_fields_only(self):
        policy = self._policy()
        result, _structural, judgment = policy.evaluate_log_item(
            {"item": "swarm listener disconnected"}, sample_log_pack())
        self.assertTrue(result.is_fallback)
        self.assertEqual(judgment["bucket"], "transport")
        self.assertEqual(judgment["path_id"], "log/transport")
        self.assertIsNone(judgment["score"]["level"])
        self.assertEqual(judgment["score"]["id"], "sentiment")

    def test_no_keyword_match_invents_nothing(self):
        policy = self._policy()
        _result, _structural, judgment = policy.evaluate_log_item(
            {"item": "unrelated prose"}, sample_log_pack())
        self.assertIsNone(judgment["bucket"])
        self.assertIsNone(judgment["path_id"])
        self.assertIsNone(judgment["suggested_next_action"])

    def test_invalid_pack_fails_closed_with_the_empty_judgment(self):
        policy = self._policy()
        result, structural, judgment = policy.evaluate_log_item(
            {"item": "swarm"}, {"id": "broken"})
        self.assertTrue(result.is_fallback)
        self.assertEqual(result.fallback_reason, "invalid_pack")
        self.assertIs(judgment["structural"], structural)
        self.assertIsNone(judgment["bucket"])
        self.assertIsNone(judgment["pack_id"])

    def test_item_text_reads_the_item_key_and_other_shapes(self):
        self.assertEqual(jev_log.log_item_text({"item": "a"}), "a")
        self.assertEqual(jev_log.log_item_text({"note": "b"}), "b")
        self.assertEqual(jev_log.log_item_text("c"), "c")
        self.assertEqual(jev_log.log_item_text(None), "")
        self.assertEqual(jev_log.log_item_text(7), "7")
        self.assertEqual(jev_log.log_item_text({"unknown": "x"}), "")

    def test_judgment_tolerates_no_pack_and_unknown_bucket(self):
        combo = jev_log.log_judgment(
            "nope", None, is_fallback=True, structural={"site": "log_factor"})
        self.assertIsNone(combo["bucket"])
        self.assertIsNone(combo["pack_id"])
        self.assertEqual(combo["evidence_refs"], [])


class LogSettlementTests(unittest.TestCase):
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
                policy.evaluate_log_item({"item": "swarm"}, sample_log_pack())

    def test_tool_cancelled_settles_and_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = self._raising_policy(
                AutonomyLedger(os.path.join(tmp, "ledger.jsonl")),
                ToolCancelled("cancelled"))
            with self.assertRaises(ToolCancelled):
                policy.evaluate_log_item({"item": "swarm"}, sample_log_pack())

    def test_provider_spend_limit_releases_and_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = self._raising_policy(
                AutonomyLedger(os.path.join(tmp, "ledger.jsonl")),
                ProviderSpendLimitError("cap", http_status=402))
            with self.assertRaises(ProviderSpendLimitError):
                policy.evaluate_log_item({"item": "swarm"}, sample_log_pack())


if __name__ == "__main__":
    unittest.main()
