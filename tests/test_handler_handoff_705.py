"""#705: bounded handoffs between the conversation lane and the plan lane.

The live defect: a refusal re-entered the conversation lane without the
siblings' guards, the conversation lane deferred, the defer escalated back to
the plan lane, and the pair recursed until the operator cancelled the session.

These tests drive that exact path hermetically (the model seam and the
auto-escalation arming are patched) and pin three properties:

* the refusal's re-entry carries ``allow_escalation=False, persist=False``;
* the pair terminates -- one escalation, one bounded re-entry, then the
  refusal renders;
* the handoff budget restores its depth, so a later request starts at zero.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from harness.agent import AutonomousAgent
from harness.config import load_settings


def _agent(tmp):
    settings = load_settings()
    settings.jev_api_key = None
    return AutonomousAgent(settings=settings, root_dir=Path(tmp),
                           history_dir=Path(tmp))


def _refused_plan():
    return {
        "status": "refused",
        "confirmation": {"reason": "scope too broad"},
        "dag": {"nodes": []},
        "nodes": [],
    }


# A capability deferral: the conversation lane hands the request to the plan
# lane, which is exactly the handoff the live loop rode.
_DEFER = {"choices": [{"message": {"content": (
    "That is a multi-step repo refactor, larger than this lane can "
    "honestly do.\n\nHARNESS_DEFER: multi-step repo work exceeds the "
    "conversation lane")}}], "usage": {"cost": 0.0}}


class RefusedEditReentryTests(unittest.TestCase):
    def test_reentry_carries_the_sibling_guards(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = _agent(tmp)
            seen = {}

            def conversation(prompt, session_id, **kwargs):
                seen.update(kwargs)
                return {"response": "util.py sets x."}

            with patch.object(agent, "_handle_conversation",
                              side_effect=conversation):
                res = agent._refused_edit(_refused_plan(), "what is x?",
                                          ["util.py"], "s1")

        self.assertEqual(seen, {"allow_escalation": False, "persist": False})
        # The refusal still answers the question -- the guards bound the
        # handoff, they do not silence it.
        self.assertTrue(res["response"].startswith("util.py sets x."))
        self.assertEqual(res["status"], "refused")

    def test_refusal_never_escalates_back_into_the_plan_lane(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = _agent(tmp)
            with patch.object(agent, "_handle_edit") as edit, \
                 patch.object(agent, "_handle_conversation",
                              return_value={"response": "answered"}):
                agent._refused_edit(_refused_plan(), "Update util.py",
                                    ["util.py"], "s2")
        edit.assert_not_called()


class DeferLoopTerminationTests(unittest.TestCase):
    """The live loop, driven end to end: conversation -> edit -> conversation."""

    def test_deferring_refusal_terminates_instead_of_recursing(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = _agent(tmp)
            calls = {"chat": 0, "edit": 0}

            def chat(*args, **kwargs):
                calls["chat"] += 1
                return 200, _DEFER

            def edit(prompt, session_id, *args, **kwargs):
                calls["edit"] += 1
                # The plan lane refuses: its terminal envelope re-enters the
                # conversation lane, which is where the loop lived.
                return agent._refused_edit(_refused_plan(), prompt,
                                           ["util.py"], session_id)

            with patch("harness.conversation_lifecycle.chat_routed",
                       side_effect=chat), \
                 patch("harness.conversation_lifecycle.governor_for",
                       return_value=(None, MagicMock())), \
                 patch("harness.conversation_lifecycle.ledger_for",
                       return_value=MagicMock()), \
                 patch.object(AutonomousAgent, "_auto_escalation_armed",
                              return_value=True), \
                 patch.object(agent, "_handle_edit", side_effect=edit):
                res = agent.run_prompt("refactor the whole engine",
                                       session_id="loop-1", auto_apply=False,
                                       force_conversation=True)

        self.assertEqual(res["status"], "refused")
        # One deferral, one escalation, one bounded re-entry answer.
        self.assertEqual(calls["edit"], 1)
        self.assertLessEqual(calls["chat"], 2)
        # The bounded re-entry's answer is what the refusal carries.
        self.assertIn("multi-step repo refactor", res["response"])
        self.assertIn("scope too broad", res["response"])


class HandoffBudgetTests(unittest.TestCase):
    def test_budget_is_per_request_and_restores_its_depth(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = _agent(tmp)
            self.assertEqual(agent._handler_handoff_depth(), 0)
            self.assertTrue(agent._handler_handoff_allowed())
            seen = []
            with agent._handler_handoff():
                seen.append(agent._handler_handoff_depth())
                with agent._handler_handoff():
                    seen.append(agent._handler_handoff_depth())
            self.assertEqual(seen, [1, 2])
            self.assertEqual(agent._handler_handoff_depth(), 0)
            self.assertFalse(hasattr(agent, "_handler_handoff_depth_value"))

    def test_exhausted_budget_refuses_another_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = _agent(tmp)
            agent._handler_handoff_depth_value = agent._HANDLER_HANDOFF_LIMIT
            try:
                self.assertFalse(agent._handler_handoff_allowed())
            finally:
                del agent._handler_handoff_depth_value
            self.assertTrue(agent._handler_handoff_allowed())


if __name__ == "__main__":
    unittest.main()
