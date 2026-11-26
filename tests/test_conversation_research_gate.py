"""#342: the chat lane retrieves only behind an accepted research plan.

Every refusal case asserts the same terminal contract: zero searches, zero
fetches. The proposal, the gate and ``validate_plan`` are the production ones;
only the reviewer double and the network seams are patched.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from harness.agent import AutonomousAgent
from harness.config import load_settings
from harness.research_plan import request_hash_for
from tests._researchplan import AcceptingPlanPolicy


class _PolicySpy(AcceptingPlanPolicy):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.kwargs = []

    def evaluate_research_plan(self, state, **kwargs):
        self.kwargs.append(dict(kwargs))
        return super().evaluate_research_plan(state, **kwargs)


class _BoomPolicy:
    def evaluate_research_plan(self, state, **kwargs):
        raise RuntimeError("transport down")


class _NoPlanReview:
    """A reviewer that has no plan question at all."""


class ChatResearchGateTests(unittest.TestCase):
    _REPLY = {"choices": [{"message": {"content": "answer"}}],
              "usage": {"cost": 0.0}}
    _PROMPT = "search for the riemann bound"

    def _run(self, policy, *, prompt=None, lifecycle_state=None, results=None):
        prompt = prompt or self._PROMPT
        results = results if results is not None else [
            {"title": "Bound moved", "url": "https://e.example/a",
             "snippet": "zero-free region extended"}]
        with tempfile.TemporaryDirectory() as tmp:
            agent = AutonomousAgent(settings=load_settings(),
                                    root_dir=Path(tmp), history_dir=Path(tmp))
            with patch("harness.jev_policy.policy_for",
                       return_value=policy), \
                 patch("harness.web.search_web", return_value=results) as ms, \
                 patch("harness.web.fetch_url",
                       return_value={"url": "https://e.example/a",
                                     "title": "T", "text": "body"}) as mf, \
                 patch("harness.conversation_lifecycle.chat_routed",
                       return_value=(200, self._REPLY)) as mc, \
                 patch("harness.conversation_lifecycle.governor_for",
                       return_value=(None, MagicMock())), \
                 patch("harness.conversation_lifecycle.ledger_for",
                       return_value=MagicMock()):
                result = agent._handle_conversation(
                    prompt, "gate-sid", web=True,
                    lifecycle_state=lifecycle_state)
                messages = mc.call_args[1]["messages"]
        system = "\n\n".join(m["content"] for m in messages
                             if m["role"] == "system")
        return result, system, ms, mf

    def test_an_accepted_plan_sends_exactly_its_own_query(self):
        policy = _PolicySpy()
        result, system, search, fetch = self._run(policy)
        search.assert_called_once()
        self.assertEqual(search.call_args[0][0], self._PROMPT)
        fetch.assert_not_called()
        plan = result["research_plan"]
        self.assertEqual(plan["state"], "accepted")
        self.assertTrue(plan["native"])
        self.assertTrue(plan["plan_hash"])
        self.assertTrue(result["web_used"])
        self.assertIn("zero-free region extended", system)
        self.assertNotIn("WITHHELD", system)
        # The reviewer judged the exact plan the lane then bound.
        self.assertEqual(policy.kwargs[0]["plan_hash"], plan["plan_hash"])
        self.assertEqual(policy.calls[0]["request_hash"],
                         plan["request_hash"])

    def test_a_declined_plan_keeps_the_lane_at_zero_network(self):
        policy = AcceptingPlanPolicy(decision="decline")
        result, system, search, fetch = self._run(policy)
        search.assert_not_called()
        fetch.assert_not_called()
        self.assertEqual(result["research_plan"]["state"], "declined")
        self.assertFalse(result["web_used"])
        self.assertIn("WEB RETRIEVAL WITHHELD", system)
        self.assertIn("no accepted research plan", system)
        self.assertNotIn("Web tools ARE attached", system)

    def test_an_unkeyed_reviewer_keeps_the_lane_at_zero_network(self):
        result, system, search, fetch = self._run(_NoPlanReview())
        search.assert_not_called()
        fetch.assert_not_called()
        plan = result["research_plan"]
        self.assertEqual(plan["state"], "unavailable")
        self.assertEqual(plan["reason"], "policy_missing")
        self.assertFalse(plan["native"])
        self.assertIn("WITHHELD", system)

    def test_a_reviewer_that_raises_fails_closed(self):
        result, system, search, fetch = self._run(_BoomPolicy())
        search.assert_not_called()
        fetch.assert_not_called()
        plan = result["research_plan"]
        self.assertEqual(plan["state"], "unavailable")
        self.assertEqual(plan["reason"], "reviewer_error: RuntimeError")
        self.assertIn("WITHHELD", system)

    def test_the_plan_binds_to_the_lifecycle_request_id(self):
        policy = _PolicySpy()
        self._run(policy, lifecycle_state={"request_id": "req-x",
                                          "usage": {}})
        self.assertEqual(policy.calls[0]["request_id"], "req-x")
        self.assertEqual(policy.calls[0]["request_hash"],
                         request_hash_for("req-x", self._PROMPT))


if __name__ == "__main__":
    unittest.main()
