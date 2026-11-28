"""Jev phase-completion evaluator owner (#309).

``tests/test_jev_bar_sentiment.py`` pins the JEV-BAR behaviour through
``JevPolicy.evaluate_phase_completion``. These tests pin the boundary the #309
split declares: the family lives in ``harness/jev_phase_completion.py``, the
policy class holds the owner's objects (not copies) and delegates to it, and
the 0-hallucination rules the family owns still hold against a completion
pack.
"""
import ast
import copy
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from harness import jev_phase_completion
from harness.config import load_settings
from harness.errors import ProviderUsageUnknown, ToolCancelled
from harness.jev import JevEvaluationResult
from harness.jev_completion import DEFAULT_COMPLETION_PACK
from harness.jev_packs import PHASE_COMPLETION_SITE
from harness.jev_policy import JevPolicy, policy_for
from harness.ledger import AutonomyLedger
from harness.provider_errors import ProviderSpendLimitError
from tests.test_jev_bar_sentiment import _JevTransport, _build_live_answers

FAMILY = ("completion_state_text", "completion_judgment",
          "evaluate_phase_completion")


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
    return Path(jev_phase_completion.__file__).read_text(encoding="utf-8")


def completion_pack():
    return copy.deepcopy(DEFAULT_COMPLETION_PACK)


class FamilyOwnershipTests(unittest.TestCase):
    def test_owner_defines_the_family(self):
        tree = ast.parse(_owner_source())
        defined = {node.name for node in tree.body
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        missing = [name for name in FAMILY if name not in defined]
        self.assertEqual(
            missing, [], f"jev_phase_completion no longer defines {missing}")

    def test_owner_helpers_are_plain_functions(self):
        # A ``@staticmethod`` left on a module-level def is a no-op callable
        # on 3.10+ and a TypeError on 3.9, so the version-independent check
        # is the object's type.
        for name in FAMILY:
            with self.subTest(name=name):
                self.assertIs(type(getattr(jev_phase_completion, name)),
                              types.FunctionType)

    def test_policy_holds_the_owners_objects_not_copies(self):
        for name in ("completion_state_text", "completion_judgment"):
            with self.subTest(name=name):
                self.assertIs(getattr(JevPolicy, "_" + name),
                              getattr(jev_phase_completion, name))

    def test_policy_delegates_to_the_owner(self):
        sentinel = object()
        pack = completion_pack()
        state = {"phase": "JEV-P5", "status_row": "| JEV-P5 | complete |"}
        with patch("harness.jev_policy._evaluate_phase_completion",
                   return_value=sentinel) as owner:
            policy = policy_for(load_settings({"jev_api_key": "jev-key"}))
            self.assertIs(policy.evaluate_phase_completion(state, pack),
                          sentinel)
        args, kwargs = owner.call_args
        self.assertIs(args[0], policy)
        self.assertIs(args[1], state)
        self.assertIs(args[2], pack)
        self.assertEqual(kwargs["site"], PHASE_COMPLETION_SITE)
        self.assertEqual(kwargs["max_input_tokens"], 4096)

    def test_owner_does_not_import_the_policy_at_module_scope(self):
        tree = ast.parse(_owner_source())
        offenders = [node.lineno for node in tree.body
                     if isinstance(node, ast.ImportFrom)
                     and (node.module or "").endswith("jev_policy")]
        self.assertEqual(
            offenders, [],
            "jev_phase_completion imports the policy at module scope")


class CompletionContractTests(unittest.TestCase):
    """The rules the family owns survive the move."""

    def _policy(self):
        return JevPolicy(load_settings({"jev_api_key": "jev-key"}))

    def test_unkeyed_keyword_fallback_uses_pack_keywords_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = load_settings()
            settings.jev_api_key = None
            policy = policy_for(
                settings, transport=None, governor=None,
                ledger=AutonomyLedger(os.path.join(tmp, "ledger.jsonl")))
            result, structural, judgment = policy.evaluate_phase_completion(
                {"phase": "JEV-P1", "status_row": "not merged draft PR"},
                completion_pack())
        self.assertTrue(result.is_fallback)
        self.assertTrue(judgment["is_fallback"])
        self.assertEqual(judgment["primary_gap"], "merge_pending")
        self.assertEqual(structural["site"], PHASE_COMPLETION_SITE)
        self.assertEqual(judgment["live_levels"],
                         {axis: None for axis in completion_pack()["axes"]})

    def test_invalid_pack_fails_closed_with_the_empty_judgment(self):
        policy = self._policy()
        result, structural, judgment = policy.evaluate_phase_completion(
            {"phase": "x"}, {"id": "broken"})
        self.assertTrue(result.is_fallback)
        self.assertEqual(result.fallback_reason, "invalid_pack")
        self.assertEqual(structural["site"], PHASE_COMPLETION_SITE)
        self.assertIsNone(judgment["pack_id"])
        self.assertEqual(judgment["live_levels"], {})
        self.assertEqual(judgment["evidence"], list(result.reasons))

    def test_keyed_live_path_declares_answered_levels(self):
        pack = completion_pack()
        answers = _build_live_answers(
            pack, axis_indices={"merge_evidence": 4, "dogfood": 3},
            primary_gap="dogfood_missing")
        transport = _JevTransport(
            {"model": "jev-test", "answers": answers,
             "usage": {"input_tokens": 150, "output_tokens": 50}})
        with tempfile.TemporaryDirectory() as tmp:
            policy = policy_for(
                load_settings({"jev_api_key": "test-key"}),
                transport=transport, governor=_CountingGovernor(),
                ledger=AutonomyLedger(os.path.join(tmp, "ledger.jsonl")))
            result, _structural, judgment = policy.evaluate_phase_completion(
                {"phase": "JEV-P5",
                 "status_row": "| JEV-P5 | **complete** | PR #42 MERGED |"},
                pack)
        self.assertFalse(result.is_fallback)
        self.assertFalse(judgment["is_fallback"])
        self.assertEqual(judgment["live_levels"]["merge_evidence"], 4)
        self.assertEqual(judgment["live_levels"]["dogfood"], 3)
        self.assertEqual(judgment["primary_gap"], "dogfood_missing")

    def test_shape_invalid_live_answer_falls_back_without_inventing(self):
        class _FallbackEvaluator:
            api_key = "jev-key"
            model = "jev-test"

            def evaluate(self, state, questions=None):
                return JevEvaluationResult(
                    "fail", 0.0, 0.0, {}, ["shape"], is_fallback=True,
                    model="jev-test")

        with tempfile.TemporaryDirectory() as tmp:
            policy = JevPolicy(
                load_settings({"jev_api_key": "jev-key"}),
                evaluator=_FallbackEvaluator(), governor=_CountingGovernor(),
                ledger=AutonomyLedger(os.path.join(tmp, "ledger.jsonl")))
            result, structural, judgment = policy.evaluate_phase_completion(
                {"phase": "x"}, completion_pack())
        self.assertTrue(result.is_fallback)
        self.assertEqual(structural["site"], PHASE_COMPLETION_SITE)
        self.assertEqual(judgment["live_levels"],
                         {axis: None for axis in completion_pack()["axes"]})
        self.assertIsNone(judgment["primary_gap"])

    def test_undeclared_legend_level_and_none_gap_stay_honest(self):
        pack = completion_pack()
        axes = list(pack["axes"])
        levels = list(pack["sentiment"]["levels"])
        answers = {
            axes[0]: {"legend": {"a0": levels[3], "a1": "not-a-level"},
                      "probabilities": {"a0": 0.6, "a1": 0.4}},
            "primary_gap": {"choice": "none"},
        }

        class _AnswersEvaluator:
            api_key = "jev-key"
            model = "jev-test"

            def evaluate(self, state, questions=None):
                return JevEvaluationResult(
                    "pass", 0.8, 0.9, answers, [], cost=0.0,
                    input_tokens=10, output_tokens=5, model="jev-test")

        with tempfile.TemporaryDirectory() as tmp:
            policy = JevPolicy(
                load_settings({"jev_api_key": "jev-key"}),
                evaluator=_AnswersEvaluator(), governor=_CountingGovernor(),
                ledger=AutonomyLedger(os.path.join(tmp, "ledger.jsonl")))
            result, _structural, judgment = policy.evaluate_phase_completion(
                {"phase": "x"}, pack)
        self.assertFalse(result.is_fallback)
        self.assertFalse(judgment["is_fallback"])
        self.assertEqual(judgment["live_levels"][axes[0]], 3)
        self.assertEqual(judgment["live_levels"][axes[1]], None)
        self.assertIsNone(judgment["primary_gap"])
        self.assertIn("primary_gap:none", judgment["evidence"])

    def test_state_text_is_bounded_and_reads_evidence_fields(self):
        text = jev_phase_completion.completion_state_text(
            {"phase": "JEV-P5", "status_row": "row", "open_blockers": ["b1"],
             "tests_missing": ["t1"], "pr_merged": True,
             "local_gates_green": False, "ci_green": None,
             "notes": ["n1"]})
        for piece in ("JEV-P5", "row", "b1", "t1", "pr_merged=True",
                      "local_gates_green=False", "n1"):
            self.assertIn(piece, text)
        self.assertEqual(len(jev_phase_completion.completion_state_text("x" * 5000)),
                         2400)
        self.assertEqual(jev_phase_completion.completion_state_text(7), "7")

    def test_judgment_carries_declared_ids_or_none(self):
        judgment = jev_phase_completion.completion_judgment(
            None, None, None, None, is_fallback=True, evidence=["e"])
        self.assertIsNone(judgment["pack_id"])
        self.assertEqual(judgment["live_levels"], {})
        self.assertEqual(judgment["live_confidence"], {})
        self.assertIsNone(judgment["primary_gap"])
        self.assertTrue(judgment["is_fallback"])
        self.assertEqual(judgment["evidence"], ["e"])


class CompletionSettlementTests(unittest.TestCase):
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
                policy.evaluate_phase_completion({"phase": "x"},
                                                 completion_pack())

    def test_tool_cancelled_settles_and_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = self._raising_policy(
                AutonomyLedger(os.path.join(tmp, "ledger.jsonl")),
                ToolCancelled("cancelled"))
            with self.assertRaises(ToolCancelled):
                policy.evaluate_phase_completion({"phase": "x"},
                                                 completion_pack())

    def test_provider_spend_limit_releases_and_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = self._raising_policy(
                AutonomyLedger(os.path.join(tmp, "ledger.jsonl")),
                ProviderSpendLimitError("cap", http_status=402))
            with self.assertRaises(ProviderSpendLimitError):
                policy.evaluate_phase_completion({"phase": "x"},
                                                 completion_pack())


if __name__ == "__main__":
    unittest.main()
