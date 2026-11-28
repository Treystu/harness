"""Jev repo-summary evaluator owner (#309).

``tests/test_jev_repo_judgment.py`` pins the JEV-P6 behaviour through
``JevPolicy.evaluate_repo_summary``. These tests pin the boundary the #309
split declares: the family lives in ``harness/jev_repo.py``, the policy class
holds the owner's objects (not copies) and delegates to it, and the
0-hallucination rules the family owns still hold against a repo pack.
"""
import ast
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from harness import jev_repo
from harness.config import load_settings
from harness.errors import ProviderUsageUnknown, ToolCancelled
from harness.jev_policy import JevPolicy, policy_for
from harness.ledger import AutonomyLedger
from harness.provider_errors import ProviderSpendLimitError
from tests.test_jev_repo_judgment import repo_pack

FAMILY = ("repo_element_text", "repo_judgment", "evaluate_repo_summary")


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
    return Path(jev_repo.__file__).read_text(encoding="utf-8")


class FamilyOwnershipTests(unittest.TestCase):
    def test_owner_defines_the_family(self):
        tree = ast.parse(_owner_source())
        defined = {node.name for node in tree.body
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        missing = [name for name in FAMILY if name not in defined]
        self.assertEqual(missing, [], f"jev_repo no longer defines {missing}")

    def test_owner_helpers_are_plain_functions(self):
        # A ``@staticmethod`` left on a module-level def is a no-op callable
        # on 3.10+ and a TypeError on 3.9, so the version-independent check
        # is the object's type.
        for name in FAMILY:
            with self.subTest(name=name):
                self.assertIs(type(getattr(jev_repo, name)), types.FunctionType)

    def test_policy_holds_the_owners_objects_not_copies(self):
        for name in ("repo_element_text", "repo_judgment"):
            with self.subTest(name=name):
                self.assertIs(getattr(JevPolicy, "_" + name),
                              getattr(jev_repo, name))

    def test_policy_delegates_to_the_owner(self):
        sentinel = object()
        pack = repo_pack()
        with patch("harness.jev_policy._evaluate_repo_summary",
                   return_value=sentinel) as owner:
            policy = policy_for(load_settings({"jev_api_key": "jev-key"}))
            self.assertIs(
                policy.evaluate_repo_summary({"path": "harness/jev.py"}, pack),
                sentinel)
        args, kwargs = owner.call_args
        self.assertIs(args[0], policy)
        self.assertEqual(args[1], {"path": "harness/jev.py"})
        self.assertIs(args[2], pack)
        self.assertEqual(kwargs["max_input_tokens"], 4096)

    def test_owner_does_not_import_the_policy_at_module_scope(self):
        tree = ast.parse(_owner_source())
        offenders = [node.lineno for node in tree.body
                     if isinstance(node, ast.ImportFrom)
                     and (node.module or "").endswith("jev_policy")]
        self.assertEqual(offenders, [], "jev_repo imports the policy at module scope")


class RepoContractTests(unittest.TestCase):
    """The rules the family owns survive the move."""

    def _policy(self):
        return JevPolicy(load_settings({"jev_api_key": "jev-key"}))

    def test_unkeyed_keyword_fallback_uses_pack_keywords_only(self):
        policy = self._policy()
        result, _structural, judgment = policy.evaluate_repo_summary(
            {"path": "harness/waist.py", "kind": "module",
             "summary": "verify ledger verdict"}, repo_pack())
        self.assertTrue(result.is_fallback)
        self.assertTrue(judgment["is_fallback"])
        self.assertEqual(judgment["axes"].get("stage"), "adjudicate")
        self.assertIsNone(judgment["attention"]["level"])
        self.assertEqual(judgment["attention"]["id"], "attention")

    def test_invalid_pack_fails_closed_with_the_empty_judgment(self):
        policy = self._policy()
        result, structural, judgment = policy.evaluate_repo_summary(
            {"path": "x"}, {"id": "broken"})
        self.assertTrue(result.is_fallback)
        self.assertEqual(result.fallback_reason, "invalid_pack")
        self.assertEqual(structural["site"], "repo_summary")
        self.assertIsNone(judgment["pack_id"])
        self.assertEqual(judgment["axes"], {})
        self.assertEqual(judgment["evidence"], list(result.reasons))

    def test_element_text_is_bounded_and_reads_symbol_fields(self):
        text = jev_repo.repo_element_text(
            {"path": "a.py", "kind": "module", "summary": "s",
             "symbols": ["f"], "element_kind": "symbol",
             "symbol": "f", "module_summary": "m"})
        self.assertIn("a.py", text)
        self.assertIn("module_summary", text.replace("m", "module_summary"))
        long_text = jev_repo.repo_element_text("x" * 5000)
        self.assertEqual(len(long_text), 1200)
        self.assertEqual(jev_repo.repo_element_text(7), "7")

    def test_judgment_carries_declared_ids_or_none(self):
        judgment = jev_repo.repo_judgment(
            {}, {"stage": "waist"}, None, None, 0.0, {},
            is_fallback=True, evidence=["e"], axis_confidence={"stage": 0.7})
        self.assertIsNone(judgment["pack_id"])
        self.assertIsNone(judgment["attention"]["id"])
        self.assertEqual(judgment["axis_confidence"], {"stage": 0.7})
        self.assertEqual(judgment["evidence"], ["e"])


class RepoSettlementTests(unittest.TestCase):
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
                policy.evaluate_repo_summary({"path": "x"}, repo_pack())

    def test_tool_cancelled_settles_and_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = self._raising_policy(
                AutonomyLedger(os.path.join(tmp, "ledger.jsonl")),
                ToolCancelled("cancelled"))
            with self.assertRaises(ToolCancelled):
                policy.evaluate_repo_summary({"path": "x"}, repo_pack())

    def test_provider_spend_limit_releases_and_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = self._raising_policy(
                AutonomyLedger(os.path.join(tmp, "ledger.jsonl")),
                ProviderSpendLimitError("cap", http_status=402))
            with self.assertRaises(ProviderSpendLimitError):
                policy.evaluate_repo_summary({"path": "x"}, repo_pack())


if __name__ == "__main__":
    unittest.main()
