"""#342: route choice proposes retrieval; only an accepted plan authorizes it.

Every refusal case asserts the same terminal contract: zero search calls,
zero fetch calls and zero browser renders. No test touches a public network.
"""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from harness.agent import AutonomousAgent
from harness.config import load_settings
from harness.jev import JevEvaluationResult
from harness.web import ReviewedSources
from tests._researchplan import accepted_plan, declined_plan


class _RoutePolicy:
    """A policy double whose route and plan answers are configured."""

    def __init__(self, plan_answer, choice="web-research"):
        self.plan_answer = plan_answer
        self.choice = choice
        self.plan_calls = []

    def evaluate_request_workflow(self, state, **kwargs):
        return SimpleNamespace(
            answers={"workflow_tier": {"choice": self.choice}},
            is_fallback=False, cost=0.0, model="jev-test", reasons=[],
        ), {"cost": 0.0, "native": True}

    def evaluate_research_plan(self, state, **kwargs):
        self.plan_calls.append(dict(state))
        self._verdicts = [True] * len(state.get("queries") or [])
        return SimpleNamespace(answers={}), self.plan_answer(
            len(state.get("queries") or []))

    def evaluate_answer(self, prompt, answer, context, **kwargs):
        result = JevEvaluationResult(
            "pass", 0.0, 0.995,
            {"answer_sufficient": {"type": "noul", "noul": 0.995},
             "iteration_required": {"type": "noul", "noul": 0.0},
             "plan_required": {"type": "noul", "noul": 0.0}},
            ["test assessment"], model="jev-test")
        return result, {
            "native": True, "answer_sufficient": 0.995,
            "iteration_required": False, "plan_required": False,
            "cost": 0.0,
        }


def _accepting(plan_answer=None):
    def answer(count):
        return {
            "cost": 0.0, "native": True, "decision": "accept",
            "confidence": 0.99, "query_verdicts": [True] * count,
        }
    return _RoutePolicy(plan_answer or answer)


def _declining(plan_answer=None):
    def answer(count):
        return {
            "cost": 0.0, "native": True, "decision": "decline",
            "confidence": 0.99, "query_verdicts": [True] * count,
        }
    return _RoutePolicy(plan_answer or answer)


class _NoPlanReview:
    """A policy double with route and answer review but no plan review."""

    evaluate_request_workflow = _RoutePolicy.evaluate_request_workflow
    evaluate_answer = _RoutePolicy.evaluate_answer


def _unavailable(plan_answer=None):
    def answer(count):
        return {
            "cost": 0.0, "native": False, "decision": "unavailable",
            "confidence": 0.0, "query_verdicts": [],
        }
    return _RoutePolicy(plan_answer or answer)


class _AgentCase(unittest.TestCase):
    def _agent(self, tmp):
        root = Path(tmp)
        return AutonomousAgent(settings=load_settings(), root_dir=root,
                               history_dir=root)


class HourglassRetrievalSeamTests(_AgentCase):
    def test_no_plan_means_no_search_fetch_or_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._agent(tmp)
            with patch.object(agent, "_gather_web_context") as gather, \
                    patch("harness.hourglass_lifecycle.render_site_evidence") \
                    as render, \
                    patch("harness.hourglass_lifecycle.emit") as emit:
                context, _files, _brief, sources = (
                    agent._hourglass_request_context(
                        "audit this site https://example.test", web=True))
        gather.assert_not_called()
        render.assert_not_called()
        self.assertNotIn("WEB EVIDENCE", context)
        notes = [s.get("note") or "" for s in sources
                 if s.get("kind") == "detour"]
        self.assertEqual(len(notes), 1)
        self.assertIn("no accepted research plan", notes[0])
        self.assertEqual(
            [call.kwargs.get("code") for call in emit.call_args_list
             if call.args and call.args[0] == "research_plan_gate"],
            ["plan_missing"])

    def test_an_accepted_plan_reaches_the_single_gatherer(self):
        prompt = "what is new in python"
        plan, approval = accepted_plan(prompt)
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._agent(tmp)
            with patch.object(agent, "_gather_web_context",
                              return_value=[{"kind": "search", "ok": True,
                                             "text": "body"}]) as gather:
                context, _f, _b, _s = agent._hourglass_request_context(
                    prompt, web=True, plan=plan, approval=approval,
                    request_id="req-1")
        gather.assert_called_once()
        self.assertIs(gather.call_args.kwargs["plan"], plan)
        self.assertIs(gather.call_args.kwargs["approval"], approval)
        self.assertEqual(gather.call_args.kwargs["request_id"], "req-1")
        self.assertIn("WEB EVIDENCE", context)

    def test_a_billed_review_cost_survives_context_intake(self):
        prompt = "what is new in python"
        plan, approval = accepted_plan(prompt)
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._agent(tmp)
            reviewed = ReviewedSources(
                [{"kind": "search", "ok": True, "text": "body"}], cost=0.25)
            with patch.object(agent, "_gather_web_context",
                              return_value=reviewed):
                _context, _files, _brief, sources = (
                    agent._hourglass_request_context(
                        prompt, web=True, plan=plan, approval=approval,
                        request_id="req-1"))
        self.assertEqual(sources.cost, 0.25)

    def test_the_renderer_runs_only_for_a_url_the_plan_names(self):
        prompt = "audit this site https://example.test"
        plan, approval = accepted_plan(prompt)
        evidence = {"engine": "chromium",
                    "final_url": "https://example.test/",
                    "title": "Example"}
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._agent(tmp)
            with patch.object(agent, "_gather_web_context", return_value=[]), \
                    patch("harness.hourglass_lifecycle.is_site_audit_request",
                          return_value=True), \
                    patch("harness.hourglass_lifecycle.extract_site_target",
                          return_value="https://example.test"), \
                    patch("harness.hourglass_lifecycle.render_site_evidence",
                          return_value=evidence) as render, \
                    patch("harness.hourglass_lifecycle.evidence_summary",
                          return_value="RENDERED"):
                _c, _f, _b, sources = agent._hourglass_request_context(
                    prompt, web=True, plan=plan, approval=approval,
                    request_id="req-1")
        render.assert_called_once()
        self.assertEqual([s["kind"] for s in sources], ["browser"])

    def test_the_renderer_skips_a_url_the_plan_does_not_name(self):
        prompt = "what is new in python"
        plan, approval = accepted_plan(prompt)
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._agent(tmp)
            with patch.object(agent, "_gather_web_context", return_value=[]), \
                    patch("harness.hourglass_lifecycle.is_site_audit_request",
                          return_value=True), \
                    patch("harness.hourglass_lifecycle.extract_site_target",
                          return_value="https://quoted.example/log"), \
                    patch("harness.hourglass_lifecycle.render_site_evidence") \
                    as render:
                agent._hourglass_request_context(
                    prompt, web=True, plan=plan, approval=approval,
                    request_id="req-1")
        render.assert_not_called()

    def test_a_declined_plan_leaves_every_network_path_closed(self):
        prompt = "audit this site https://example.test"
        plan, approval = declined_plan(prompt)
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._agent(tmp)
            with patch.object(agent, "_gather_web_context") as gather, \
                    patch("harness.hourglass_lifecycle.is_site_audit_request",
                          return_value=True), \
                    patch("harness.hourglass_lifecycle.render_site_evidence") \
                    as render:
                _c, _f, _b, sources = agent._hourglass_request_context(
                    prompt, web=True, plan=plan, approval=approval,
                    request_id="req-1")
        gather.assert_not_called()
        render.assert_not_called()
        self.assertTrue(all(s.get("kind") == "detour" for s in sources))

    def test_a_non_native_approval_is_not_approval(self):
        prompt = "what is new in python"
        plan, _approval = accepted_plan(prompt)
        local = SimpleNamespace(
            decision="accept", native=False, plan_hash=plan.hash(),
            request_hash=plan.request_hash, revision=plan.revision,
            confidence=0.99, consent_id="",
            query_verdicts=tuple(True for _ in plan.queries),
            issued_at=0.0, expires_at=0.0)
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._agent(tmp)
            with patch.object(agent, "_gather_web_context") as gather:
                agent._hourglass_request_context(
                    prompt, web=True, plan=plan, approval=local,
                    request_id="req-1")
        gather.assert_not_called()


def _run_with_policy(agent, policy, prompt, **kwargs):
    with patch("harness.hourglass_lifecycle.policy_for",
               return_value=policy), \
            patch("harness.hourglass_lifecycle.governor_for",
                  return_value=(None, MagicMock())), \
            patch("harness.hourglass_lifecycle.ledger_for",
                  return_value=MagicMock()), \
            patch.object(agent, "_hourglass_request_context",
                         return_value=("ctx", {}, MagicMock(
                             estimated_tokens=2), [])) as gather, \
            patch.object(agent, "_hourglass_answer_once", return_value={
                "model": "m1", "answer": "grounded answer", "cost": 0.0}), \
            patch("harness.hourglass_lifecycle.save_chat_turn"):
        result = agent.run_hourglass_request(prompt, **kwargs)
    return result, gather


class HourglassPlanProposerTests(_AgentCase):
    def _run(self, agent, policy, prompt, **kwargs):
        return _run_with_policy(agent, policy, prompt, **kwargs)

    def test_an_accepted_plan_is_what_the_lane_retrieves_under(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._agent(tmp)
            policy = _accepting()
            result, gather = self._run(
                agent, policy, "latest python release",
                request_preflight={"source": "jev_request_workflow",
                                   "choice": "web-research",
                                   "native": True, "cost": 0.0})
        self.assertTrue(gather.call_args.kwargs["web"])
        self.assertIsNotNone(gather.call_args.kwargs["plan"])
        self.assertTrue(gather.call_args.kwargs["approval"].native)
        self.assertEqual(result["research_plan"]["state"], "accepted")
        self.assertEqual(result["research_plan"]["decision"], "accept")
        self.assertEqual(len(policy.plan_calls), 1)

    def test_a_declined_plan_keeps_the_lane_at_zero_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._agent(tmp)
            policy = _declining()
            result, gather = self._run(
                agent, policy, "latest python release",
                request_preflight={"source": "jev_request_workflow",
                                   "choice": "web-research",
                                   "native": True, "cost": 0.0})
        self.assertFalse(gather.call_args.kwargs["web"])
        self.assertIsNone(gather.call_args.kwargs["approval"])
        self.assertEqual(result["research_plan"]["state"], "declined")
        self.assertFalse(result["web_used"])

    def test_a_goal_too_short_to_research_is_not_proposed(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._agent(tmp)
            policy = _accepting()
            result, gather = self._run(agent, policy, "hi", web=True)
        self.assertFalse(gather.call_args.kwargs["web"])
        self.assertEqual(result["research_plan"]["state"], "invalid")
        self.assertEqual(result["research_plan"]["reason"], "goal_too_short")
        self.assertEqual(policy.plan_calls, [])

    def test_a_caller_supplied_accepted_plan_is_validated_not_trusted(self):
        prompt = "latest python release"
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._agent(tmp)
            state = agent.lifecycle.begin(
                "chat", "caller-plan", prompt, stage="route",
                max_review_rounds=1, data={"route": "hourglass"})
            plan, approval = accepted_plan(
                prompt, request_id=state["request_id"])
            result, gather = self._run(
                agent, _accepting(), prompt, session_id="caller-plan",
                web=True, research_plan=plan, plan_approval=approval,
                request_preflight={"source": "jev_request_workflow",
                                   "choice": "answer", "native": True,
                                   "cost": 0.0})
        self.assertTrue(gather.call_args.kwargs["web"])
        self.assertIs(gather.call_args.kwargs["plan"], plan)
        self.assertEqual(result["research_plan"]["state"], "accepted")

    def test_a_caller_supplied_plan_without_approval_closes_the_lane(self):
        prompt = "latest python release"
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._agent(tmp)
            state = agent.lifecycle.begin(
                "chat", "caller-plan-none", prompt, stage="route",
                max_review_rounds=1, data={"route": "hourglass"})
            plan, _approval = accepted_plan(
                prompt, request_id=state["request_id"])
            result, gather = self._run(
                agent, _accepting(), prompt, session_id="caller-plan-none",
                web=True, research_plan=plan,
                request_preflight={"source": "jev_request_workflow",
                                   "choice": "answer", "native": True,
                                   "cost": 0.0})
        self.assertFalse(gather.call_args.kwargs["web"])
        self.assertEqual(result["research_plan"]["state"], "declined")
        self.assertIn("approval_missing", result["research_plan"]["reason"])

    def test_a_plan_bound_to_another_request_is_refused(self):
        prompt = "latest python release"
        plan, approval = accepted_plan(prompt, request_id="someone-else")
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._agent(tmp)
            result, gather = self._run(
                agent, _accepting(), prompt, web=True, research_plan=plan,
                plan_approval=approval,
                request_preflight={"source": "jev_request_workflow",
                                   "choice": "answer", "native": True,
                                   "cost": 0.0})
        self.assertFalse(gather.call_args.kwargs["web"])
        self.assertEqual(result["research_plan"]["state"], "declined")
        self.assertIn("request_mismatch", result["research_plan"]["reason"])

    def test_a_policy_that_cannot_review_a_plan_closes_the_lane(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._agent(tmp)
            result, gather = self._run(
                agent, _NoPlanReview(), "latest python release",
                request_preflight={"source": "jev_request_workflow",
                                   "choice": "web-research",
                                   "native": True, "cost": 0.0})
        self.assertFalse(gather.call_args.kwargs["web"])
        self.assertEqual(result["research_plan"]["state"], "unavailable")
        self.assertEqual(result["research_plan"]["reason"], "policy_missing")
        self.assertFalse(result["web_used"])

    def test_an_unkeyed_reviewer_reports_unavailable_not_acceptance(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._agent(tmp)
            policy = _unavailable()
            result, gather = self._run(
                agent, policy, "latest python release",
                request_preflight={"source": "jev_request_workflow",
                                   "choice": "web-research",
                                   "native": True, "cost": 0.0})
        self.assertFalse(gather.call_args.kwargs["web"])
        self.assertEqual(result["research_plan"]["decision"], "unavailable")
        self.assertIn("approval_not_native", result["research_plan"]["reason"])
        self.assertFalse(result["web_used"])


class ResearchPlanCheckpointTests(_AgentCase):
    """#342/#344: the accepted plan and its receipt survive in the checkpoint."""

    def test_the_gate_and_its_native_receipt_are_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._agent(tmp)
            result, _gather = _run_with_policy(
                agent, _accepting(), "latest python release",
                session_id="plan-session",
                request_preflight={"source": "jev_request_workflow",
                                   "choice": "web-research",
                                   "native": True, "cost": 0.0})
            data = agent.lifecycle.load("plan-session")["data"]
        self.assertEqual(data["research_plan_gate"]["state"], "accepted")
        self.assertEqual(data["approved_plan_hash"],
                         result["research_plan"]["plan_hash"])
        self.assertTrue(data["plan_approval"]["native"])
        self.assertEqual(data["plan_approval"]["decision"], "accept")

    def test_a_blocked_plan_is_recorded_instead_of_the_lane_silently_skipping(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._agent(tmp)
            result, _gather = _run_with_policy(
                agent, _declining(), "latest python release",
                session_id="plan-blocked",
                request_preflight={"source": "jev_request_workflow",
                                   "choice": "web-research",
                                   "native": True, "cost": 0.0})
        self.assertEqual(result["research_plan"]["state"], "declined")
        self.assertIn("approval_declined", result["research_plan"]["reason"])
        self.assertFalse(result["web_used"])


if __name__ == "__main__":
    unittest.main()
