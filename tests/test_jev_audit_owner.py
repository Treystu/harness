"""Jev 4-dimensional self-audit evaluator owner (#309).

``tests/test_audit_dimensions.py`` pins the JEV self-audit gate behaviour
through ``JevPolicy.evaluate_audit_dimensions``. These tests pin the boundary
the #309 split declares: the family lives in
``harness/jev_audit_dimensions.py``, the policy class holds the owner's helper
(not a copy) and delegates, the module-level resolver stays importable from
``harness.jev_policy`` because callers import it there, and the honesty rules
the family owns still hold.
"""
import ast
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from harness import jev_audit_dimensions, jev_policy
from harness.config import load_settings
from harness.errors import ProviderUsageUnknown, ToolCancelled
from harness.jev_packs import DEFAULT_AUDIT_DIMENSIONS_PACK
from harness.jev_policy import JevPolicy, policy_for
from harness.ledger import AutonomyLedger
from harness.provider_errors import ProviderSpendLimitError

FAMILY = ("audit_dimension_text", "evaluate_audit_dimensions",
          "resolve_audit_dimension")


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
    return Path(jev_audit_dimensions.__file__).read_text(encoding="utf-8")


def _evidence(score=9.7, satisfied=13, total=13):
    return {"score": score, "checks_satisfied": satisfied,
            "checks_count": total,
            "checks": [{"id": "A1", "label": "gate", "score": 1}]}


class FamilyOwnershipTests(unittest.TestCase):
    def test_owner_defines_the_family(self):
        tree = ast.parse(_owner_source())
        defined = {node.name for node in tree.body
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        missing = [name for name in FAMILY if name not in defined]
        self.assertEqual(
            missing, [], f"jev_audit_dimensions no longer defines {missing}")

    def test_owner_functions_are_plain_functions(self):
        # A ``@staticmethod`` left on a module-level def is a no-op callable
        # on 3.10+ and a TypeError on 3.9, so the version-independent check
        # is the object's type.
        for name in FAMILY:
            with self.subTest(name=name):
                self.assertIs(type(getattr(jev_audit_dimensions, name)),
                              types.FunctionType)

    def test_policy_holds_the_owners_helper_and_the_module_alias(self):
        self.assertIs(JevPolicy._audit_dimension_text,
                      jev_audit_dimensions.audit_dimension_text)
        self.assertIs(jev_policy._resolve_audit_dimension,
                      jev_audit_dimensions.resolve_audit_dimension)

    def test_policy_delegates_to_the_owner(self):
        sentinel = object()
        evidence = {"A": _evidence()}
        with patch("harness.jev_policy._evaluate_audit_dimensions",
                   return_value=sentinel) as owner:
            policy = policy_for(load_settings({"jev_api_key": "jev-key"}))
            self.assertIs(policy.evaluate_audit_dimensions(evidence), sentinel)
        args, kwargs = owner.call_args
        self.assertIs(args[0], policy)
        self.assertIs(args[1], evidence)
        self.assertIsNone(args[2])
        self.assertEqual(kwargs["task_id"], None)
        self.assertEqual(kwargs["max_input_tokens"], 4096)

    def test_owner_does_not_import_the_policy_at_module_scope(self):
        tree = ast.parse(_owner_source())
        offenders = [node.lineno for node in tree.body
                     if isinstance(node, ast.ImportFrom)
                     and (node.module or "").endswith("jev_policy")]
        self.assertEqual(
            offenders, [],
            "jev_audit_dimensions imports the policy at module scope")


class AuditContractTests(unittest.TestCase):
    """The rules the family owns survive the move."""

    def _policy(self):
        return JevPolicy(load_settings({"jev_api_key": "jev-key"}))

    def test_unmeasured_dimension_is_never_scored(self):
        policy = self._policy()
        report = policy.evaluate_audit_dimensions({"A": _evidence()})
        self.assertTrue(report["is_fallback"])
        self.assertFalse(report["bar_95_pass"])
        self.assertEqual(report["dimensions"]["A"]["score"], 9.7)
        for dim in ("R", "SM", "SD"):
            with self.subTest(dim=dim):
                entry = report["dimensions"][dim]
                self.assertEqual(entry["level"], "not_evaluated")
                self.assertIsNone(entry["score"])
                self.assertFalse(entry["evaluated"])
                self.assertIsNone(report["scores"][dim])
        self.assertEqual(report["min_score"], 9.7)

    def test_governor_missing_falls_back_without_a_transport(self):
        policy = policy_for(load_settings({"jev_api_key": "jev-key"}))
        report = policy.evaluate_audit_dimensions({"A": _evidence()})
        self.assertTrue(report["is_fallback"])
        self.assertIn("governor_not_provided", report["reasons"])

    def test_dimension_text_names_every_dimension(self):
        text = jev_audit_dimensions.audit_dimension_text({"A": _evidence()})
        self.assertIn("Harness 4-Dimensional Self-Audit Evidence:", text)
        for dim in ("A", "R", "SM", "SD"):
            self.assertIn(f"Dimension {dim}:", text)
        self.assertIn("[A1] pass gate", text)

    def test_resolver_rejects_a_level_below_min_confidence(self):
        idx, source, _conf, live_level, live_conf = (
            jev_audit_dimensions.resolve_audit_dimension(
                {"legend": {"a": "l0", "b": "l3"},
                 "probabilities": {"a": 0.59, "b": 0.36}},
                ["l0", "l1", "l2", "l3"], evidence_score=9.8,
                min_confidence=0.70))
        self.assertEqual(source, "heuristic_low_confidence")
        self.assertEqual(live_level, "l0")
        self.assertAlmostEqual(live_conf, 0.59)
        self.assertEqual(idx, 3)


class AuditFailClosedGuardTests(unittest.TestCase):
    """The defensive gates the family owns cannot be bypassed."""

    def _policy(self):
        return JevPolicy(load_settings({"jev_api_key": "jev-key"}))

    def test_unexpected_transport_failure_falls_back(self):
        class _Boom:
            api_key = "jev-key"
            model = "jev-test"

            def evaluate(self, state, questions=None):
                raise RuntimeError("socket reset")

        with tempfile.TemporaryDirectory() as tmp:
            policy = JevPolicy(
                load_settings({"jev_api_key": "jev-key"}),
                evaluator=_Boom(), governor=_CountingGovernor(),
                ledger=AutonomyLedger(os.path.join(tmp, "ledger.jsonl")))
            report = policy.evaluate_audit_dimensions({"A": _evidence()})
        self.assertTrue(report["is_fallback"])
        self.assertIn("transport_error: socket reset", report["reasons"])
        self.assertFalse(report["bar_95_pass"])

    def test_extra_heuristic_dimension_cannot_pass_the_bar(self):
        dims = dict(DEFAULT_AUDIT_DIMENSIONS_PACK["dimensions"])
        results = {dim: {"name": spec["name"], "level_index": 3,
                         "level": "l3", "score": 9.9, "bar_met": True,
                         "evaluated": True, "source": "heuristic",
                         "live_level": None, "live_level_confidence": None}
                   for dim, spec in dims.items()}
        results["X"] = dict(results[next(iter(dims))])
        with patch("harness.jev_audit_dimensions.heuristic_audit_dimensions",
                   return_value=results):
            report = self._policy().evaluate_audit_dimensions(
                {"A": _evidence()})
        self.assertTrue(report["is_fallback"])
        self.assertFalse(report["bar_95_pass"])

    def test_evaluated_dimension_without_a_score_cannot_pass(self):
        dims = dict(DEFAULT_AUDIT_DIMENSIONS_PACK["dimensions"])
        results = {dim: {"name": spec["name"], "level_index": 3,
                         "level": "l3", "score": 9.9, "bar_met": True,
                         "evaluated": True, "source": "heuristic",
                         "live_level": None, "live_level_confidence": None}
                   for dim, spec in dims.items()}
        results[next(iter(dims))]["score"] = None
        with patch("harness.jev_audit_dimensions.heuristic_audit_dimensions",
                   return_value=results):
            report = self._policy().evaluate_audit_dimensions(
                {"A": _evidence()})
        self.assertTrue(report["is_fallback"])
        self.assertFalse(report["bar_95_pass"])


class AuditSettlementTests(unittest.TestCase):
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
                policy.evaluate_audit_dimensions({"A": _evidence()})

    def test_tool_cancelled_settles_and_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = self._raising_policy(
                AutonomyLedger(os.path.join(tmp, "ledger.jsonl")),
                ToolCancelled("cancelled"))
            with self.assertRaises(ToolCancelled):
                policy.evaluate_audit_dimensions({"A": _evidence()})

    def test_provider_spend_limit_releases_and_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = self._raising_policy(
                AutonomyLedger(os.path.join(tmp, "ledger.jsonl")),
                ProviderSpendLimitError("cap", http_status=402))
            with self.assertRaises(ProviderSpendLimitError):
                policy.evaluate_audit_dimensions({"A": _evidence()})


if __name__ == "__main__":
    unittest.main()
