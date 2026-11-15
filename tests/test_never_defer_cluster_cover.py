"""D12 coverage cure for the never-defer bundle (PR #547, #538-#544).

The bundle's tests pin the behaviour each issue asks for; this module walks
the branch seams those tests do not reach, so the changed lines are executed
by the suite rather than merely present in the diff. Every case here is a
real contract of the shipped code -- a degraded ledger read, a dry judge
seat, a salvage that has to normalise a mapping, a plan that must be
re-derived on the next backend -- not a line-touch:

* the availability ledger's corruption/degradation branches (#539);
* the panel's judge-seat and vote-seat refusal handoff (#538);
* the decomposition salvage's python-literal and ``nodes``-mapping shapes
  (#541);
* the artifact-request detour block and abort in the hourglass and
  simple-answer lanes (#542);
* the edit lane's plan-review replay refusal and bounded re-derivation
  (#538) and its generation fallback when no file scope was planned (#544);
* the operation-time workspace gate message (#544).

Hermetic: no network, no operator config, no ambient credentials.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from harness.availability import (
    ACCOUNT_FUNDING,
    DEFAULT_TTL_SECONDS,
    AvailabilityLedger,
    _default_path,
    default_ledger,
    provider_of,
    reset_default_ledger,
)
from harness.chat_policy import is_artifact_request, research_detour_blocked
from harness.config import load_settings
from harness.errors import HarnessError
from harness.panel import _run_judge_attempt, panel_judge
from harness.provider_errors import ProviderSpendLimitError
from harness.waist import _salvage_decomposition
from harness.workspace import (
    WORKSPACE_GATE_MESSAGE,
    require_workspace_for_operation,
)
from tests._fake import JUDGE, P1, P2, FakeTransport, _gov, comp, m


def _refusal(model="deepseek/deepseek-v4.1-flash"):
    return ProviderSpendLimitError("provider spend cap reached for this "
                                   "account", http_status=402,
                                   cause=ACCOUNT_FUNDING, model=model)


class AvailabilityLedgerDegradationTests(unittest.TestCase):
    """#539: bookkeeping outages degrade to memory, never stop a request."""

    def test_cerebras_routes_name_their_own_provider(self):
        self.assertEqual(provider_of("cerebras/llama-3.3-70b"), "cerebras")

    def test_unreadable_or_shapeless_documents_degrade_to_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "availability.json")
            for payload in (
                    "{not json at all",                       # OSError/ValueError
                    json.dumps(["a list, not a mapping"]),    # no entries map
                    json.dumps({"entries": {"m": "not a dict"}}),
                    json.dumps({"entries": {"m": {"recorded_at": "soon"}}}),
            ):
                with self.subTest(payload=payload):
                    Path(path).write_text(payload, encoding="utf-8")
                    self.assertEqual(AvailabilityLedger(path).snapshot(), {})

    def test_a_failed_save_keeps_the_verdict_in_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = AvailabilityLedger(None)
            ledger.path = os.path.join(tmp, "availability.json")
            with mock.patch("harness.availability.os.replace",
                            side_effect=OSError("read-only store")):
                ledger.record_failure("m-a", cause=ACCOUNT_FUNDING)
            self.assertTrue(ledger.is_excluded("m-a"))

    def test_an_expired_verdict_is_dropped_when_it_is_read(self):
        clock = {"now": 100.0}
        ledger = AvailabilityLedger(None, ttl=5.0,
                                    clock=lambda: clock["now"])
        ledger.record_failure("m-a", cause=ACCOUNT_FUNDING)
        clock["now"] = 106.0
        self.assertIsNone(ledger.entry("m-a"))
        self.assertFalse(ledger.is_excluded("m-a"))

    def test_a_nonsense_probe_cost_is_ignored_but_the_probe_counts(self):
        ledger = AvailabilityLedger(None)
        ledger.record_failure("m-a")
        ledger.note_probe("m-a", "not a number")
        entry = ledger.entry("m-a")
        self.assertEqual(entry.probes, 1)
        self.assertEqual(entry.probe_cost, 0.0)

    def test_a_probe_for_an_unrecorded_model_is_a_no_op(self):
        ledger = AvailabilityLedger(None)
        ledger.note_probe("m-never-seen", 0.5)
        self.assertEqual(ledger.snapshot(), {})

    def test_an_unclassified_verdict_excludes_only_its_own_model(self):
        ledger = AvailabilityLedger(None)
        ledger.record_failure("m-unknown", kind="unknown")
        self.assertTrue(ledger.is_unservable("m-unknown"))
        self.assertFalse(ledger.is_unservable("m-other"))

    def test_probe_budget_is_zero_without_a_verdict(self):
        self.assertEqual(AvailabilityLedger(None).probe_budget_left("m-none"), 0)

    def test_a_provider_wide_verdict_excludes_its_sibling_paid_routes(self):
        ledger = AvailabilityLedger(None)
        ledger.record_failure("accounts/fireworks/models/a",
                              cause=ACCOUNT_FUNDING)
        self.assertTrue(ledger.is_excluded("accounts/fireworks/models/b"))
        self.assertFalse(
            ledger.is_excluded("accounts/fireworks/models/b:free"))


class DefaultLedgerEnvironmentTests(unittest.TestCase):
    """``default_ledger`` resolves its path and window from the environment."""

    def setUp(self):
        # The ledger is process-wide, so an earlier test may already have
        # built one; every case here is about construction from the env.
        reset_default_ledger(None)
        self._saved = {k: os.environ.get(k) for k in (
            "HARNESS_AVAILABILITY_OFF", "HARNESS_AVAILABILITY_PATH",
            "HARNESS_AVAILABILITY_TTL")}

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_default_ledger(None)

    def test_the_off_switch_keeps_the_ledger_in_memory(self):
        os.environ["HARNESS_AVAILABILITY_OFF"] = "1"
        self.assertIsNone(_default_path())
        self.assertIsNone(default_ledger().path)

    def test_an_unusable_config_dir_degrades_to_memory(self):
        os.environ.pop("HARNESS_AVAILABILITY_OFF", None)
        os.environ.pop("HARNESS_AVAILABILITY_PATH", None)
        with mock.patch("harness.paths.get_config_dir",
                        side_effect=RuntimeError("no home")):
            self.assertIsNone(_default_path())

    def test_a_config_dir_resolves_the_persisted_name(self):
        os.environ.pop("HARNESS_AVAILABILITY_OFF", None)
        os.environ.pop("HARNESS_AVAILABILITY_PATH", None)
        with mock.patch("harness.paths.get_config_dir",
                        return_value=os.path.join(os.sep, "cfghome")):
            self.assertTrue(_default_path().endswith("availability.json"))

    def test_a_bad_ttl_falls_back_to_the_default_window(self):
        os.environ["HARNESS_AVAILABILITY_TTL"] = "soon"
        self.assertEqual(default_ledger().ttl, DEFAULT_TTL_SECONDS)


class PanelSeatRefusalTests(unittest.TestCase):
    """#538: a dry judge or vote seat rotates instead of aborting the panel."""

    def test_the_judge_seat_returns_a_named_status_and_bills_nothing(self):
        gov = _gov(FakeTransport(models=[m(JUDGE)]))
        ledger = mock.MagicMock()
        with mock.patch("harness.panel.chat_routed",
                        side_effect=_refusal(JUDGE)):
            note, content, cost = _run_judge_attempt(
                transport=FakeTransport(), api_key="k", governor=gov,
                judge_prompt="judge this", model=JUDGE,
                judge_reserve_tokens=256, reasoning_effort=None,
                reasoning_token_budget=0.1, task_id="t-judge", ledger=ledger,
                task_type="panel")
        self.assertEqual((note, content, cost),
                         ("provider_unavailable", None, 0.0))
        notes = [call.args[0] for call in ledger.append.call_args_list]
        self.assertEqual(notes, ["model_result"])

    def test_a_refused_vote_seat_is_recorded_and_rotated(self):
        gov = _gov(FakeTransport(models=[m(P1), m(P2), m(JUDGE)]))

        def routed(transport, api_key, model, messages, *args, **kwargs):
            if model == P1:
                raise _refusal(P1)
            return 200, comp("take two")

        with mock.patch("harness.panel.chat_routed", side_effect=routed):
            result = panel_judge(
                transport=FakeTransport(), api_key="k", governor=gov,
                prompt="Q?", panel=[P1, P2], judge=JUDGE,
                task_id="t-panel", ledger=mock.MagicMock())
        failures = result["panel_failures"]
        self.assertTrue(any(
            failure.get("status") == "provider_unavailable"
            and failure.get("model") == P1 for failure in failures))


class SalvageShapeTests(unittest.TestCase):
    """#541: only shapes the strict DAG contract accepts come back."""

    def test_an_empty_body_is_not_salvaged(self):
        self.assertIsNone(_salvage_decomposition(""))
        self.assertIsNone(_salvage_decomposition("   \n"))

    def test_a_python_literal_span_is_recovered(self):
        dag = _salvage_decomposition(
            "{'node_id': 'n1', 'instruction': 'Create the windows script'}")
        self.assertIsNotNone(dag)
        self.assertIn("n1", dag.nodes)

    def test_a_nodes_mapping_is_normalised_before_validation(self):
        body = json.dumps({"nodes": {
            "n1": {"node_id": "n1", "instruction": "Create the script"},
            "n2": {"node_id": "n2", "instruction": "Run the script",
                   "dependencies": ["n1"]},
        }})
        dag = _salvage_decomposition(body)
        self.assertIsNotNone(dag)
        self.assertEqual(sorted(dag.nodes), ["n1", "n2"])

    def test_a_span_with_no_usable_structure_is_skipped(self):
        # A balanced span that parses but names neither nodes nor a node.
        self.assertIsNone(_salvage_decomposition('{"notes": "nothing here"}'))
        self.assertIsNone(_salvage_decomposition('{"a": 1}'))
        # A python set literal is not a JSON object and never becomes one.
        self.assertIsNone(_salvage_decomposition("{1, 2}"))
        # A span that is not a python literal either is skipped, not raised.
        self.assertIsNone(_salvage_decomposition("{node_id: n1}"))

    def test_a_nodes_list_the_dag_contract_rejects_is_not_salvaged(self):
        body = json.dumps({"nodes": [{"node_id": "n1",
                                       "instruction": "Create the script",
                                       "dependencies": ["n9"]}]})
        self.assertIsNone(_salvage_decomposition(body))

    def test_recovered_nodes_the_dag_contract_rejects_are_not_salvaged(self):
        cyclic = ('{"node_id": "n1", "instruction": "a", '
                  '"dependencies": ["n2"]} '
                  '{"node_id": "n2", "instruction": "b", '
                  '"dependencies": ["n1"]}')
        self.assertIsNone(_salvage_decomposition(cyclic))


class ArtifactPredicateTests(unittest.TestCase):
    """#542: the predicate is conservative on an empty request."""

    def test_an_empty_prompt_is_not_an_artifact_request(self):
        self.assertFalse(is_artifact_request(""))
        self.assertFalse(is_artifact_request("   "))
        self.assertFalse(research_detour_blocked(""))


class WorkspaceGateOperationTests(unittest.TestCase):
    """#544: the gate fires at the operation and keeps one message."""

    def test_an_empty_root_names_the_desktop_message(self):
        for raw in (None, "", "   "):
            with self.subTest(raw=raw):
                with self.assertRaises(HarnessError) as ctx:
                    require_workspace_for_operation(raw)
                self.assertEqual(str(ctx.exception), WORKSPACE_GATE_MESSAGE)

    def test_a_real_root_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(require_workspace_for_operation(tmp),
                             Path(tmp).resolve())


class ArtifactDetourTests(unittest.TestCase):
    """#542: an artifact request does not spend the run on research."""

    def _agent(self, tmp):
        from harness.agent import AutonomousAgent

        return AutonomousAgent(history_dir=Path(tmp))

    def test_an_artifact_request_never_opens_a_research_detour(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._agent(tmp)
            gathered = mock.MagicMock()
            with mock.patch.object(agent, "_gather_web_context", gathered), \
                    mock.patch("harness.hourglass_lifecycle.emit") as emit_mock:
                _context, _files, _brief, sources = (
                    agent._hourglass_request_context(
                        "make a script that runs in windows to generate "
                        "the image", web=True))
        gathered.assert_not_called()
        self.assertIn("research_detour_blocked",
                      [call.args[0] for call in emit_mock.call_args_list
                       if call.args])
        notes = [source["note"] for source in sources
                 if source.get("kind") == "detour"]
        self.assertEqual(len(notes), 1)
        self.assertIn("blocked", notes[0])

    def test_a_detour_that_gathered_only_empty_bodies_is_aborted(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._agent(tmp)
            empty = [{"kind": "web", "ok": True, "url": "https://x.test/a",
                      "text": "   "}]
            with mock.patch.object(agent, "_gather_web_context",
                                   return_value=empty), \
                    mock.patch("harness.hourglass_lifecycle.emit") as emit_mock:
                _context, _files, _brief, sources = (
                    agent._hourglass_request_context(
                        "What is the latest news about Python releases?",
                        web=True))
        self.assertIn("research_detour_aborted",
                      [call.args[0] for call in emit_mock.call_args_list
                       if call.args])
        notes = [source["note"] for source in sources
                 if source.get("kind") == "detour"]
        self.assertEqual(len(notes), 1)
        self.assertIn("0 chars", notes[0])


class SimpleAnswerDetourTests(unittest.TestCase):
    """#542 on the ordinary-answer lane: an artifact request keeps building."""

    def test_a_jev_suggested_detour_on_an_artifact_is_dropped(self):
        from harness.agent import AutonomousAgent

        with tempfile.TemporaryDirectory() as tmp:
            settings = load_settings({
                "panel_pool": "m", "ledger_path": str(Path(tmp) / "l.jsonl"),
                "max_cost": 0.01})
            agent = AutonomousAgent(settings=settings, history_dir=Path(tmp))
            policy = mock.MagicMock()
            policy.evaluate_simple_strategy.return_value = (
                SimpleNamespace(is_fallback=False),
                {"native": True, "strategy": "web_research",
                 "probabilities": {"web_research": 1.0},
                 "concentration": 1.0, "cost": 0.0})
            gov = mock.MagicMock()
            with mock.patch(
                    "harness.simple_answer_lifecycle.governor_for",
                    return_value=("k", gov)), \
                    mock.patch("harness.simple_answer_lifecycle.policy_for",
                               return_value=policy), \
                    mock.patch.object(agent, "_live_jev_available",
                                      return_value=False), \
                    mock.patch.object(
                        agent, "_handle_conversation",
                        return_value={"status": "ok",
                                      "response": "built"}) as convo:
                result = agent.run_simple_request(
                    "Can you make a script that runs in Windows to "
                    "generate the image?", session_id="s-artifact")
        self.assertEqual(result["status"], "ok")
        convo.assert_called_once()
        self.assertFalse(convo.call_args[1].get("web"))


class EditPlanReplayTests(unittest.TestCase):
    """#538 / #544 on the edit lane's plan-stage replay boundary."""

    def _agent(self, tmp):
        from harness.agent import AutonomousAgent

        agent = AutonomousAgent(history_dir=Path(tmp))
        agent.root_dir = Path(tmp)
        return agent

    def test_a_dry_plan_backend_is_re_derived_twice_then_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._agent(tmp)
            plan_eval = mock.MagicMock()
            plan_eval.answers = {}
            plan_eval.verdict = "pass"
            plan_eval.is_fallback = False
            plan_policy = mock.MagicMock()
            plan_policy.evaluate_plan.return_value = (plan_eval, None)
            distill = mock.MagicMock()
            distill.return_value.ledger_fields.return_value = {}
            with mock.patch.object(agent, "_triage_scope",
                                   return_value=["a.py"]), \
                    mock.patch("harness.edit_lifecycle.distill_context",
                               distill), \
                    mock.patch("harness.edit_lifecycle.governor_for",
                               return_value=("k", mock.MagicMock())), \
                    mock.patch("harness.edit_lifecycle.policy_for",
                               return_value=plan_policy), \
                    mock.patch("harness.edit_lifecycle.budget_from_settings",
                               return_value=None), \
                    mock.patch("harness.edit_lifecycle.emit") as emit_mock, \
                    mock.patch.object(agent, "_plan_round",
                                      side_effect=_refusal("plan-lane")):
                result = agent._handle_edit("Refactor the login helper",
                                            "sid-dry", False)
        self.assertEqual(result["status"], "deferred")
        self.assertTrue(result.get("unservable_backends"))
        reasons = [call.kwargs.get("reason")
                   for call in emit_mock.call_args_list
                   if call.args and call.args[0] == "rotation"]
        self.assertEqual(reasons.count("edit_plan_availability_retry"), 2)

    def test_an_unscoped_generation_falls_back_to_the_conversation_lane(self):
        with tempfile.TemporaryDirectory() as tmp:
            from harness.agent import AutonomousAgent

            settings = load_settings({
                "panel_pool": "m", "ledger_path": str(Path(tmp) / "l.jsonl"),
                "max_cost": 0.01})
            agent = AutonomousAgent(settings=settings, root_dir=None,
                                    history_dir=Path(tmp), transport=None)
            with mock.patch.object(agent, "run_simple_request",
                                   return_value={"status": "failed"}), \
                    mock.patch.object(agent, "_handle_conversation",
                                      return_value={"status": "ok",
                                                    "response": "answered"}) \
                    as convo:
                result = agent._handle_edit("make a script that prints hello",
                                            "s-gen", False, None)
        self.assertEqual(result["response"], "answered")
        convo.assert_called_once()


if __name__ == "__main__":
    unittest.main()
