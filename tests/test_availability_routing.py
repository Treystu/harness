"""Hermetic contracts for provider-availability routing (#538, #539, #540).

The owner is :mod:`harness.availability`; these tests pin the behaviour the
issues ask for: a provider refusal never ends a request that has another
configured backend, a pair already known to be unservable is not dispatched
again, and the ordinary-answer ladder is ordered by live availability with
the documented free-first posture.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from harness import availability as _availability_module
from harness.availability import (
    ACCOUNT_FUNDING,
    ROUTE_OR_MODEL_RESTRICTION,
    AvailabilityLedger,
    is_free_model,
    provider_of,
    record_error,
)
from harness.config import load_settings
from harness.errors import HarnessError, ProviderUsageUnknown
from harness.events import (
    mark_provider_spend_limit,
    raise_if_provider_spend_limited,
    reset_provider_spend_limit_latch,
    task_context,
)
from harness.lifecycle import LifecycleCoordinator
from harness.lifecycle_guards import (
    BUDGET_REFUSED,
    SPEND_EXHAUSTED,
    classify_harness_error,
    is_availability_failure,
    is_terminal_failure,
)
from harness.provider_errors import ProviderSpendLimitError


def _funding(model, *, reason="account balance is too low"):
    err = ProviderSpendLimitError(reason, http_status=402,
                                  cause=ACCOUNT_FUNDING, model=model)
    return err


class ProviderIdentityTests(unittest.TestCase):
    def test_provider_and_free_classification(self):
        self.assertEqual(provider_of("accounts/fireworks/models/x"), "fireworks")
        self.assertEqual(provider_of("muse-1"), "meta")
        self.assertEqual(provider_of("groq/llama"), "groq")
        self.assertEqual(provider_of("deepseek/deepseek-v4-flash"), "openrouter")
        self.assertTrue(is_free_model("inclusionai/ling-3.0-flash-fin:free"))
        self.assertTrue(is_free_model("openrouter/free"))
        self.assertFalse(is_free_model("deepseek/deepseek-v4-flash"))


class AvailabilityLedgerTests(unittest.TestCase):
    def _ledger(self, **kwargs):
        return AvailabilityLedger(None, **kwargs)

    def test_funding_blocks_paid_models_but_not_free_ones(self):
        ledger = self._ledger()
        ledger.record_failure("deepseek/deepseek-v4-flash", kind=SPEND_EXHAUSTED,
                              cause=ACCOUNT_FUNDING, http_status=402)
        self.assertTrue(ledger.is_excluded("deepseek/deepseek-v4-flash"))
        self.assertTrue(ledger.is_excluded("qwen/qwen3.8-max-0902"))
        self.assertFalse(ledger.is_excluded("inclusionai/ling-3.0-flash:free"))

    def test_restriction_blocks_only_the_named_model(self):
        ledger = self._ledger()
        ledger.record_failure("accounts/fireworks/models/a",
                              kind="model_unavailable",
                              cause=ROUTE_OR_MODEL_RESTRICTION, http_status=402)
        self.assertTrue(ledger.is_excluded("accounts/fireworks/models/a"))
        self.assertFalse(ledger.is_excluded("accounts/fireworks/models/b"))
        # A restriction is provider-scoped-by-model only: it never touches a
        # different provider's paid models.
        self.assertFalse(ledger.is_excluded("deepseek/deepseek-v4-flash"))

    def test_verdict_expires_and_success_clears_it(self):
        clock = {"now": 1000.0}
        ledger = self._ledger(ttl=10.0, clock=lambda: clock["now"])
        ledger.record_failure("m-a", kind=SPEND_EXHAUSTED,
                              cause=ACCOUNT_FUNDING)
        self.assertTrue(ledger.is_excluded("m-a"))
        clock["now"] = 1011.0
        self.assertFalse(ledger.is_excluded("m-a"))
        ledger.record_failure("m-b", kind=SPEND_EXHAUSTED,
                              cause=ACCOUNT_FUNDING)
        ledger.record_success("m-b")
        self.assertFalse(ledger.is_excluded("m-b"))

    def test_rate_limit_cooldown_is_shorter_than_a_funding_verdict(self):
        clock = {"now": 0.0}
        ledger = self._ledger(ttl=900.0, rate_limit_ttl=60.0,
                              clock=lambda: clock["now"])
        ledger.record_failure("m-a", kind="rate_limited",
                              cause="unknown")
        clock["now"] = 61.0
        self.assertFalse(ledger.is_excluded("m-a"))

    def test_verdicts_persist_across_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "availability.json")
            first = AvailabilityLedger(path)
            first.record_failure("deepseek/deepseek-v4-flash",
                                 kind=SPEND_EXHAUSTED,
                                 cause=ACCOUNT_FUNDING, http_status=402)
            second = AvailabilityLedger(path)
            self.assertTrue(second.is_excluded("deepseek/deepseek-v4-flash"))
            second.record_success("deepseek/deepseek-v4-flash")
            third = AvailabilityLedger(path)
            self.assertFalse(third.is_excluded("deepseek/deepseek-v4-flash"))

    def test_probe_budget_is_bounded_and_cost_recorded(self):
        ledger = self._ledger(probe_budget=1)
        ledger.record_failure("m-a", kind=SPEND_EXHAUSTED,
                              cause=ACCOUNT_FUNDING)
        self.assertEqual(ledger.probe_budget_left("m-a"), 1)
        ledger.note_probe("m-a", cost=0.0004)
        self.assertEqual(ledger.probe_budget_left("m-a"), 0)
        self.assertAlmostEqual(ledger.snapshot()["m-a"]["probe_cost"], 0.0004)

    def test_order_drops_unservable_pairs_and_prefers_free(self):
        ledger = self._ledger()
        ledger.record_failure("paid-head", kind=SPEND_EXHAUSTED,
                              cause=ACCOUNT_FUNDING)
        ordered = ledger.order(["paid-head", "paid-alt", "free-alt:free"])
        # The funding verdict is provider-wide for paid routes: paid-alt (the
        # same provider) is gone too, the $0 route survives.
        self.assertEqual(ordered, ["free-alt:free"])
        paid_first = ledger.order(
            ["accounts/fireworks/models/paid-alt", "free-alt:free"],
            prefer_free=False)
        self.assertEqual(paid_first, ["accounts/fireworks/models/paid-alt",
                                      "free-alt:free"])

    def test_order_never_empties_a_ladder(self):
        ledger = self._ledger()
        for model in ("a", "b"):
            ledger.record_failure(model, kind=SPEND_EXHAUSTED,
                                  cause=ACCOUNT_FUNDING)
        self.assertEqual(ledger.order(["a", "b"]), ["a", "b"])

    def test_live_backends_names_what_is_selectable(self):
        ledger = self._ledger()
        ledger.record_failure("dry", kind=SPEND_EXHAUSTED,
                              cause=ACCOUNT_FUNDING, reason="out of credits")
        report = {row["model"]: row for row in ledger.live_backends(
            ["dry", "accounts/fireworks/models/ok"])}
        self.assertFalse(report["dry"]["live"])
        self.assertEqual(report["dry"]["cause"], ACCOUNT_FUNDING)
        self.assertTrue(report["accounts/fireworks/models/ok"]["live"])


class TerminalPolicyTests(unittest.TestCase):
    def test_provider_exhaustion_is_rotatable_not_terminal(self):
        self.assertFalse(is_terminal_failure(SPEND_EXHAUSTED))
        self.assertTrue(is_availability_failure(SPEND_EXHAUSTED))
        self.assertTrue(is_availability_failure("rate_limited"))
        self.assertTrue(is_availability_failure("auth_failed"))

    def test_only_the_run_budget_cap_is_terminal(self):
        self.assertTrue(is_terminal_failure(BUDGET_REFUSED))
        self.assertFalse(is_availability_failure(BUDGET_REFUSED))
        self.assertEqual(
            classify_harness_error("run refused: would exceed phase ceiling"),
            BUDGET_REFUSED)


class SpendLatchTests(unittest.TestCase):
    def test_latch_does_not_block_a_different_provider(self):
        with task_context("latch-provider"):
            mark_provider_spend_limit(_funding("deepseek/deepseek-v4-flash"))
            # Same provider, paid: still blocked.
            with self.assertRaises(ProviderSpendLimitError):
                raise_if_provider_spend_limited(
                    model="qwen/qwen3.8-max-0902")
            # A funded backend on another provider: failover proceeds.
            raise_if_provider_spend_limited(
                model="accounts/fireworks/models/deepseek-v3p2")

    def test_latch_allows_a_free_route_after_funding(self):
        with task_context("latch-free"):
            mark_provider_spend_limit(_funding("deepseek/deepseek-v4-flash"))
            raise_if_provider_spend_limited(
                model="inclusionai/ling-3.0-flash-fin:free")

    def test_latch_still_blocks_the_same_model(self):
        with task_context("latch-same"):
            mark_provider_spend_limit(_funding("deepseek/deepseek-v4-flash"))
            with self.assertRaises(ProviderSpendLimitError):
                raise_if_provider_spend_limited(
                    model="deepseek/deepseek-v4-flash")
            reset_provider_spend_limit_latch()
            raise_if_provider_spend_limited(
                model="deepseek/deepseek-v4-flash")


class TransportBackendIdentityTests(unittest.TestCase):
    """Codex P1: the refusal is raised inside the transport, not the lane."""

    @staticmethod
    def _http_error(code, body):
        import io
        import urllib.error

        payload = json.dumps(body).encode("utf-8")
        return urllib.error.HTTPError(
            "https://example.invalid", code, "err", {}, io.BytesIO(payload))

    def test_transport_402_names_the_refusing_backend(self):
        from harness._http import HttpTransport

        capped = self._http_error(402, {
            "error": {"code": "payment_required",
                      "message": "add credits"}})
        with patch("urllib.request.urlopen", side_effect=[capped]):
            with self.assertRaises(ProviderSpendLimitError) as ctx:
                HttpTransport().post(
                    "https://openrouter.ai/api/v1/chat/completions", "k",
                    {"model": "deepseek/deepseek-v4-flash"})
        self.assertEqual(ctx.exception.model, "deepseek/deepseek-v4-flash")
        self.assertEqual(ctx.exception.cause, ACCOUNT_FUNDING)

    def test_transport_refusal_does_not_latch_another_provider(self):
        from harness._http import HttpTransport

        capped = self._http_error(402, {
            "error": {"code": "payment_required",
                      "message": "add credits"}})
        with task_context("transport-latch"):
            with patch("urllib.request.urlopen", side_effect=[capped]):
                with self.assertRaises(ProviderSpendLimitError):
                    HttpTransport().post(
                        "https://openrouter.ai/api/v1/chat/completions", "k",
                        {"model": "deepseek/deepseek-v4-flash"})
            raise_if_provider_spend_limited(
                model="accounts/fireworks/models/deepseek-v3p2")
            with self.assertRaises(ProviderSpendLimitError):
                raise_if_provider_spend_limited(
                    model="deepseek/deepseek-v4-flash")

    def test_latched_error_preserves_a_restriction_cause(self):
        with task_context("latch-cause"):
            restricted = ProviderSpendLimitError(
                "model not available", http_status=402,
                cause=ROUTE_OR_MODEL_RESTRICTION, model="m-a")
            mark_provider_spend_limit(restricted)
            with self.assertRaises(ProviderSpendLimitError) as ctx:
                raise_if_provider_spend_limited(model="m-a")
        self.assertEqual(ctx.exception.cause, ROUTE_OR_MODEL_RESTRICTION)


class LifecycleReplayTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.coord = LifecycleCoordinator(self._tmp.name)
        self.state = self.coord.begin("chat", "s1", "make a plan")

    def test_provider_refusal_is_replayable(self):
        attempts = []

        def invoke():
            attempts.append(1)
            if len(attempts) == 1:
                raise _funding("deepseek/deepseek-v4-flash")
            return {"ok": True}

        with self.assertRaises(ProviderSpendLimitError):
            self.coord.provider_call(self.state, "c1", invoke)
        self.assertEqual(
            self.state["usage"]["provider_calls"]["c1"]["status"], "refused")
        result = self.coord.provider_call(self.state, "c1", invoke)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(attempts), 2)

    def test_refused_retry_allocates_a_new_receipt(self):
        # Codex P2: an original unknown call plus a refused retry must still
        # be able to reach the next backend.
        def unknown():
            raise ProviderUsageUnknown("lost", known_cost=0.0)

        with self.assertRaises(ProviderUsageUnknown):
            self.coord.provider_call(self.state, "c4", unknown)
        attempts = []

        def refused_then_ok():
            attempts.append(1)
            if len(attempts) == 1:
                raise _funding("deepseek/deepseek-v4-flash")
            return {"ok": True}

        with self.assertRaises(ProviderSpendLimitError):
            self.coord.provider_call(self.state, "c4", refused_then_ok,
                                     retry_unknown=True)
        self.assertEqual(
            self.state["usage"]["provider_calls"]["c4:retry:1"]["status"],
            "refused")
        replayed = self.coord.provider_call(
            self.state, "c4", refused_then_ok, retry_unknown=True)
        self.assertEqual(replayed, {"ok": True})
        self.assertIn("c4:retry:2", self.state["usage"]["provider_calls"])

    def test_unknown_completion_is_still_not_replayed(self):
        def invoke():
            raise ProviderUsageUnknown("lost after dispatch", known_cost=0.0)

        with self.assertRaises(ProviderUsageUnknown):
            self.coord.provider_call(self.state, "c2", invoke)
        with self.assertRaises(HarnessError) as ctx:
            self.coord.provider_call(self.state, "c2", lambda: {"ok": True})
        self.assertIn("unknown completion", str(ctx.exception))


def _settings(root: Path):
    return load_settings({
        "panel_pool": "paid-head",
        "ledger_path": str(root / "ledger.jsonl"),
        "jev_api_key": "jev-test",
        "max_cost": 0.01,
    })


def _pre():
    return SimpleNamespace(is_fallback=False), {
        "native": True, "strategy": "direct_answer",
        "probabilities": {"direct_answer": 1.0}, "concentration": 1.0,
        "cost": 0.0,
    }


def _post():
    return SimpleNamespace(is_fallback=False, verdict="pass"), {
        "native": True, "verdict": "pass", "answer_sufficient": 0.95,
        "iteration_required": False, "plan_required": False, "cost": 0.0,
    }


class AnswerLadderSelectionTests(unittest.TestCase):
    """#540: the ordinary-answer rung is chosen by availability, not pool head."""

    def setUp(self):
        from harness.agent import AutonomousAgent

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.agent = AutonomousAgent(
            settings=_settings(self.root), root_dir=self.root,
            history_dir=self.root, transport=MagicMock())
        self.ledger = AvailabilityLedger(None, ttl=900.0)
        _availability_module.reset_default_ledger(self.ledger)
        self.addCleanup(_availability_module.reset_default_ledger)

    def _run(self, ladder, effects, *, session_id="answer-ladder"):
        self.agent.settings.panel_pool = list(ladder)
        self.agent.settings.use_free = True
        policy = MagicMock()
        policy.evaluate_simple_strategy.return_value = _pre()
        policy.evaluate_answer.return_value = _post()
        with (
            patch("harness.simple_answer_lifecycle.governor_for",
                  return_value=("key", MagicMock())),
            patch("harness.simple_answer_lifecycle.policy_for",
                  return_value=policy),
            patch("harness.simple_answer_lifecycle.ledger_for",
                  return_value=MagicMock()),
            patch("harness.simple_answer_lifecycle.governed_completion",
                  side_effect=list(effects)) as generate,
            patch("harness.simple_answer_lifecycle.load_chat_history",
                  return_value=[]),
        ):
            result = self.agent.run_simple_request(
                "How do I make a peanut butter and jelly sandwich?",
                session_id=session_id)
        return result, generate

    def test_free_route_answers_while_the_paid_head_is_dry(self):
        self.ledger.record_failure("paid-head", kind=SPEND_EXHAUSTED,
                                   cause=ACCOUNT_FUNDING, http_status=402)
        answer = {"content": "Free answer.", "model": "free-alt:free",
                  "cost": 0.0, "input_tokens": 5, "output_tokens": 4,
                  "cost_estimated": False}
        result, generate = self._run(
            ["paid-head", "free-alt:free"], [answer])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["model"], "free-alt:free")
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(generate.call_args_list[0].args[3], "free-alt:free")

    def test_answer_rotates_and_records_the_refused_pair(self):
        second = {"content": "Second rung.", "model": "rung-b",
                  "cost": 0.0, "input_tokens": 5, "output_tokens": 4,
                  "cost_estimated": False}
        result, generate = self._run(
            ["rung-a", "rung-b"],
            [_funding("rung-a"), second])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["model"], "rung-b")
        self.assertTrue(self.ledger.is_excluded("rung-a"))

    def test_result_names_live_backends(self):
        self.ledger.record_failure("paid-head", kind=SPEND_EXHAUSTED,
                                   cause=ACCOUNT_FUNDING)
        answer = {"content": "Free answer.", "model": "free-alt:free",
                  "cost": 0.0, "input_tokens": 5, "output_tokens": 4,
                  "cost_estimated": False}
        result, _ = self._run(["paid-head", "free-alt:free"], [answer])
        backends = {row["model"]: row
                    for row in result["simple_request"]["backends"]}
        self.assertFalse(backends["paid-head"]["live"])
        self.assertTrue(backends["free-alt:free"]["live"])


class DefaultLedgerWiringTests(unittest.TestCase):
    def test_record_error_carries_the_classified_cause(self):
        ledger = AvailabilityLedger(None)
        _availability_module.reset_default_ledger(ledger)
        self.addCleanup(_availability_module.reset_default_ledger)
        record_error("deepseek/deepseek-v4-flash",
                     _funding("deepseek/deepseek-v4-flash"),
                     kind=SPEND_EXHAUSTED)
        entry = ledger.entry("deepseek/deepseek-v4-flash")
        self.assertEqual(entry.cause, ACCOUNT_FUNDING)
        self.assertEqual(entry.http_status, 402)


if __name__ == "__main__":
    unittest.main()
