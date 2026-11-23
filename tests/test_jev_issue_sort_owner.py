"""Jev issue-sort evaluator owner (#309).

``tests/test_jev_issue_sort.py`` pins the JEV-P5 behaviour through
``JevPolicy.evaluate_issue_sort``. These tests pin the boundary the #309 split
declares: the family lives in ``harness/jev_issue_sort.py``, the policy class
holds the owner's objects (not copies) and delegates to it, and the
0-hallucination rules the family owns still hold when it runs against a pack.
"""
import ast
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness import jev_issue_sort
from harness.config import load_settings
from harness.errors import ProviderUsageUnknown, ToolCancelled
from harness.jev_policy import JevPolicy, policy_for
from harness.ledger import AutonomyLedger
from harness.provider_errors import ProviderSpendLimitError

FAMILY = (
    "issue_sort_text",
    "issue_sort_empty_combo",
    "issue_sort_combo",
    "evaluate_issue_sort",
)

PACK = {
    "id": "owner-pack-v1",
    "buckets": {
        "auth": {
            "label": "Auth / token trouble",
            "kind": "trouble_area",
            "path_id": "path/auth",
            "keywords": ["auth", "token"],
            "suggested_next_action": "open auth backlog",
            "attention": "high",
        },
    },
}


class _CountingGovernor:
    def __init__(self):
        self.released = []
        self.max_cost = 1.0
        self.spent = 0.0

    def reserve(self, worst, label):
        return {"label": label, "worst": worst}

    def release(self, reservation):
        self.released.append(reservation)

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
    return Path(jev_issue_sort.__file__).read_text(encoding="utf-8")


class FamilyOwnershipTests(unittest.TestCase):
    def test_owner_defines_the_family(self):
        tree = ast.parse(_owner_source())
        defined = {node.name for node in tree.body
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        missing = [name for name in FAMILY if name not in defined]
        self.assertEqual(missing, [], f"jev_issue_sort no longer defines {missing}")

    def test_policy_holds_the_owners_objects_not_copies(self):
        for name in ("issue_sort_text", "issue_sort_empty_combo",
                     "issue_sort_combo"):
            with self.subTest(name=name):
                self.assertIs(getattr(JevPolicy, "_" + name),
                              getattr(jev_issue_sort, name))

    def test_policy_delegates_to_the_owner(self):
        sentinel = object()
        with patch("harness.jev_policy._evaluate_issue_sort",
                   return_value=sentinel) as owner:
            policy = policy_for(load_settings({"jev_api_key": "jev-key"}))
            self.assertIs(
                policy.evaluate_issue_sort({"issue": "auth token"}, PACK),
                sentinel)
        args, kwargs = owner.call_args
        self.assertIs(args[0], policy)
        self.assertEqual(args[1], {"issue": "auth token"})
        self.assertIs(args[2], PACK)
        self.assertEqual(kwargs["max_input_tokens"], 4096)

    def test_owner_does_not_import_the_policy_at_module_scope(self):
        tree = ast.parse(_owner_source())
        offenders = [node.lineno for node in tree.body
                     if isinstance(node, ast.ImportFrom)
                     and (node.module or "").endswith("jev_policy")]
        self.assertEqual(offenders, [], "jev_issue_sort imports the policy at module scope")


class IssueSortContractTests(unittest.TestCase):
    """The rules the family owns survive the move."""

    def _policy(self):
        return JevPolicy(load_settings({"jev_api_key": "jev-key"}))

    def test_unkeyed_keyword_match_binds_pack_fields_only(self):
        policy = self._policy()
        result, _structural, combo = policy.evaluate_issue_sort(
            {"issue": "token expired on login"}, PACK)
        self.assertTrue(result.is_fallback)
        self.assertTrue(combo["is_fallback"])
        self.assertEqual(combo["bucket"], "auth")
        self.assertEqual(combo["path_id"], "path/auth")
        self.assertEqual(combo["suggested_next_action"], "open auth backlog")

    def test_no_keyword_match_invents_nothing(self):
        policy = self._policy()
        _result, _structural, combo = policy.evaluate_issue_sort(
            {"issue": "unrelated prose"}, PACK)
        self.assertIsNone(combo["bucket"])
        self.assertIsNone(combo["path_id"])
        self.assertIsNone(combo["suggested_next_action"])
        self.assertTrue(combo["is_fallback"])

    def test_invalid_pack_fails_closed_with_the_empty_combo(self):
        policy = self._policy()
        result, structural, combo = policy.evaluate_issue_sort(
            {"issue": "auth"}, {"id": "broken"})
        self.assertTrue(result.is_fallback)
        self.assertEqual(result.fallback_reason, "invalid_pack")
        self.assertIs(combo["structural"], structural)
        self.assertIsNone(combo["bucket"])

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
                policy.evaluate_issue_sort({"issue": "auth token"}, PACK)

    def test_tool_cancelled_settles_and_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = self._raising_policy(
                AutonomyLedger(os.path.join(tmp, "ledger.jsonl")),
                ToolCancelled("cancelled"))
            with self.assertRaises(ToolCancelled):
                policy.evaluate_issue_sort({"issue": "auth token"}, PACK)

    def test_provider_spend_limit_releases_and_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = self._raising_policy(
                AutonomyLedger(os.path.join(tmp, "ledger.jsonl")),
                ProviderSpendLimitError("cap", http_status=402))
            with self.assertRaises(ProviderSpendLimitError):
                policy.evaluate_issue_sort({"issue": "auth token"}, PACK)

    def test_empty_combo_helper_is_the_policy_helper(self):
        combo = JevPolicy._issue_sort_empty_combo(
            is_fallback=False, evidence=["e"], pack_id="p")
        self.assertEqual(combo["evidence_refs"], ["e"])
        self.assertEqual(combo["pack_id"], "p")
        self.assertFalse(combo["is_fallback"])


if __name__ == "__main__":
    unittest.main()
