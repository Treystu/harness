"""#415: GUI/chat web capability boundary and exact research-plan receipt."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from harness.agent import AutonomousAgent
from harness.config import load_settings
from harness.research_plan import (
    DECISION_ACCEPT,
    DECISION_DECLINE,
    decide_research_plan,
    propose_plan,
)
from tests._researchplan import AcceptingPlanPolicy

_UI_APP = Path(__file__).resolve().parent.parent / "harness" / "ui" / "app.js"


class _ModelAwarePlanPolicy(AcceptingPlanPolicy):
    def evaluate_research_plan(self, state, **kwargs):
        result, structural = super().evaluate_research_plan(state, **kwargs)
        structural = dict(structural)
        structural.setdefault("model", "jev-1.14.0")
        structural.setdefault("verdict", getattr(result, "verdict", "proceed"))
        return result, structural


class GuiResearchPlanReceiptTests(unittest.TestCase):
    _REPLY = {"choices": [{"message": {"content": "grounded"}}],
              "usage": {"cost": 0.0}}

    def test_empty_capabilities_yields_capability_unavailable(self):
        plan, why = propose_plan("What changed in HTTP semantics?",
                                 request_id="req-empty-caps",
                                 capabilities=())
        self.assertIsNone(plan)
        self.assertEqual(why, "capability_unavailable")

        policy = _ModelAwarePlanPolicy()
        out_plan, approval, record = decide_research_plan(
            "What changed in HTTP semantics?",
            policy=policy,
            request_id="req-empty-caps",
            capabilities=(),
        )
        self.assertIsNone(out_plan)
        self.assertIsNone(approval)
        self.assertEqual(record["state"], "capability_unavailable")
        self.assertTrue(record["capability_unavailable"])
        self.assertEqual(record["active_capabilities"], [])
        self.assertEqual(record["search_calls"], 0)
        self.assertEqual(record["fetch_calls"], 0)
        self.assertEqual(policy.calls, [])

    def test_chat_with_web_on_and_zero_capabilities_makes_no_network_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = AutonomousAgent(settings=load_settings(),
                                    root_dir=Path(tmp), history_dir=Path(tmp))
            agent.web_capabilities = ()
            policy = _ModelAwarePlanPolicy()
            with patch("harness.jev_policy.policy_for", return_value=policy), \
                 patch("harness.web.search_web") as ms, \
                 patch("harness.web.fetch_url") as mf, \
                 patch("harness.conversation_lifecycle.chat_routed",
                       return_value=(200, self._REPLY)) as mc, \
                 patch("harness.conversation_lifecycle.governor_for",
                       return_value=(None, MagicMock())), \
                 patch("harness.conversation_lifecycle.ledger_for",
                       return_value=MagicMock()):
                res = agent._handle_conversation(
                    "Summarize latest RFC updates", "sid-415-nocap", web=True)
                sysmsg = mc.call_args[1]["messages"][0]["content"]
        ms.assert_not_called()
        mf.assert_not_called()
        self.assertFalse(res["web_used"])
        rp = res["research_plan"]
        self.assertTrue(rp["capability_unavailable"])
        self.assertEqual(rp["state"], "capability_unavailable")
        self.assertEqual(rp["search_calls"], 0)
        self.assertEqual(rp["fetch_calls"], 0)
        self.assertIn("WEB RETRIEVAL WITHHELD", sysmsg)

    def test_chat_records_exact_plan_fields_and_call_counts_search_and_fetch(self):
        policy = _ModelAwarePlanPolicy(decision=DECISION_ACCEPT)
        results = [{"title": "RFC", "url": "https://e.example/rfc",
                    "snippet": "HTTP status notes"}]
        page = {"url": "https://en.wikipedia.org/wiki/HTTP_ETag",
                "title": "HTTP ETag", "text": "ETag header details"}
        with tempfile.TemporaryDirectory() as tmp:
            agent = AutonomousAgent(settings=load_settings(),
                                    root_dir=Path(tmp), history_dir=Path(tmp))
            with patch("harness.jev_policy.policy_for", return_value=policy), \
                 patch("harness.web.search_web", return_value=results) as ms, \
                 patch("harness.web.fetch_url", return_value=page) as mf, \
                 patch("harness.conversation_lifecycle.chat_routed",
                       return_value=(200, self._REPLY)), \
                 patch("harness.conversation_lifecycle.governor_for",
                       return_value=(None, MagicMock())), \
                 patch("harness.conversation_lifecycle.ledger_for",
                       return_value=MagicMock()):
                res_search = agent._handle_conversation(
                    "search for HTTP ETag semantics", "sid-415-search", web=True)
                res_fetch = agent._handle_conversation(
                    "Summarize https://en.wikipedia.org/wiki/HTTP_ETag briefly",
                    "sid-415-fetch", web=True)
        ms.assert_called_once()
        mf.assert_called_once()
        rps = res_search["research_plan"]
        self.assertEqual(rps["state"], "accepted")
        self.assertEqual(rps["jev_model"], "jev-1.14.0")
        self.assertTrue(rps["consent_id"].endswith(":research-plan"))
        self.assertEqual(rps["active_capabilities"], ["fetch", "search"])
        self.assertFalse(rps["capability_unavailable"])
        self.assertEqual(rps["search_calls"], 1)
        self.assertEqual(rps["fetch_calls"], 0)
        self.assertEqual(len(rps["queries"]), 1)
        rpf = res_fetch["research_plan"]
        self.assertEqual(rpf["search_calls"], 0)
        self.assertEqual(rpf["fetch_calls"], 1)
        self.assertEqual(rpf["queries"][0]["kind"], "fetch")

    def test_saved_plan_reuse_and_declined_keep_call_counts_consistent(self):
        prompt = "What changed in HTTP/3?"
        policy = _ModelAwarePlanPolicy(decision=DECISION_ACCEPT)
        plan, approval, first = decide_research_plan(
            prompt, policy=policy, request_id="req-reuse-415",
            now=1000.0)
        self.assertIsNotNone(approval)
        reused_plan, reused_approval, second = decide_research_plan(
            prompt, policy=policy, request_id="req-reuse-415", now=1010.0,
            saved_plan={
                "plan_hash": first["plan_hash"],
                "receipt": approval.payload(),
            })
        self.assertEqual(reused_plan.hash(), plan.hash())
        self.assertTrue(reused_approval.native)
        self.assertTrue(second["reused"])
        self.assertEqual(second["consent_id"], "req-reuse-415:research-plan")

        declined = _ModelAwarePlanPolicy(decision=DECISION_DECLINE)
        _p, dec_app, dec_rec = decide_research_plan(
            prompt, policy=declined, request_id="req-dec-415")
        self.assertIsNone(dec_app)
        self.assertEqual(dec_rec["state"], "declined")
        self.assertEqual(dec_rec["search_calls"], 0)
        self.assertEqual(dec_rec["fetch_calls"], 0)

    def test_ui_app_renders_research_plan_gate_and_capability_unavailable(self):
        src = _UI_APP.read_text(encoding="utf-8")
        self.assertIn('ev.type === "research_plan_gate"', src)
        self.assertIn("capability_unavailable", src)
        self.assertIn("research-plan-receipt", src)

    def test_hourglass_request_forwards_web_capabilities_and_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent = AutonomousAgent(settings=load_settings(),
                                    root_dir=root, history_dir=root)
            page = {"url": "https://en.wikipedia.org/wiki/HTTP_ETag",
                    "title": "HTTP ETag", "text": "ETag header details"}

            class _HourglassPolicy(_ModelAwarePlanPolicy):
                def evaluate_route(self, prompt, *, context=None, site=None,
                                   task_id=None, **kwargs):
                    from types import SimpleNamespace
                    return SimpleNamespace(answers={}), {
                        "strategy": "web-research",
                        "choice": "web-research",
                        "native": True,
                        "cost": 0.0,
                    }

                def evaluate_answer(self, prompt, answer, context, *,
                                    site="answer", task_id=None):
                    from harness.jev import JevEvaluationResult
                    res = JevEvaluationResult(
                        verdict="pass", confidence=0.95, supported=0.95,
                        answers={"answer_sufficient": {"type": "noul",
                                                       "noul": 0.95}},
                        reasons=[], cost=0.0, is_fallback=False,
                        model="jev-1.14.0")
                    return res, {
                        "native": True, "cost": 0.0,
                        "verdict": "pass", "supported": 0.95,
                        "confidence": 0.95, "answer_sufficient": 0.95,
                        "iteration_required": False,
                        "plan_required": False, "model": "jev-1.14.0",
                    }

            policy = _HourglassPolicy()
            with patch("harness.hourglass_lifecycle.policy_for",
                       return_value=policy), \
                 patch("harness.hourglass_lifecycle.governor_for",
                       return_value=(None, MagicMock())), \
                 patch("harness.hourglass_lifecycle.ledger_for",
                       return_value=MagicMock()), \
                 patch("harness.web.fetch_url", return_value=page) as mf, \
                 patch("harness.web.search_web") as ms, \
                 patch("harness.hourglass_lifecycle.render_site_evidence",
                       side_effect=AssertionError("skip browser")), \
                 patch("harness.hourglass_lifecycle.chat_routed",
                       return_value=(200, self._REPLY)), \
                 patch("harness.hourglass_lifecycle.save_chat_turn"):
                agent.web_capabilities = ()
                no_cap = agent.run_hourglass_request(
                    "What is HTTP ETag?", session_id="hg-415-nocap",
                    web=True)
                self.assertEqual(no_cap["research_plan"]["state"],
                                 "capability_unavailable")
                self.assertTrue(no_cap["research_plan"]["capability_unavailable"])
                self.assertEqual(no_cap["research_plan"]["fetch_calls"], 0)
                mf.assert_not_called()
                ms.assert_not_called()

                agent.web_capabilities = ("fetch",)
                fetched = agent.run_hourglass_request(
                    "Summarize https://en.wikipedia.org/wiki/HTTP_ETag",
                    session_id="hg-415-fetch", web=True)
                mf.assert_called_once()
                self.assertEqual(fetched["research_plan"]["state"], "accepted")
                self.assertEqual(fetched["research_plan"]["fetch_calls"], 1)
                self.assertEqual(fetched["research_plan"]["search_calls"], 0)


    def test_url_prompts_do_not_bypass_research_plan_into_simple_answer(self):
        from harness.simple_request import is_simple_answer_request

        url_prompt = (
            "Summarize https://en.wikipedia.org/wiki/HTTP_ETag in two sentences."
        )
        self.assertFalse(is_simple_answer_request(url_prompt, intent="conversation"))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent = AutonomousAgent(settings=load_settings(),
                                    root_dir=root, history_dir=root)
            page = {"url": "https://en.wikipedia.org/wiki/HTTP_ETag",
                    "title": "HTTP ETag", "text": "ETag header details"}

            class _HourglassPolicy(_ModelAwarePlanPolicy):
                def evaluate_route(self, prompt, *, context=None, site=None,
                                   task_id=None, **kwargs):
                    from types import SimpleNamespace
                    return SimpleNamespace(answers={}), {
                        "strategy": "web-research",
                        "choice": "web-research",
                        "native": True,
                        "cost": 0.0,
                    }

                def evaluate_answer(self, prompt, answer, context, *,
                                    site="answer", task_id=None):
                    from harness.jev import JevEvaluationResult
                    res = JevEvaluationResult(
                        verdict="pass", confidence=0.95, supported=0.95,
                        answers={"answer_sufficient": {"type": "noul",
                                                       "noul": 0.95}},
                        reasons=[], cost=0.0, is_fallback=False,
                        model="jev-1.14.0")
                    return res, {
                        "native": True, "cost": 0.0,
                        "verdict": "pass", "supported": 0.95,
                        "confidence": 0.95, "answer_sufficient": 0.95,
                        "iteration_required": False,
                        "plan_required": False, "model": "jev-1.14.0",
                    }

            policy = _HourglassPolicy()
            with patch.object(agent, "_live_jev_available", return_value=True), \
                 patch.object(agent, "run_simple_request",
                              side_effect=AssertionError("URL prompt bypassed web")), \
                 patch("harness.hourglass_lifecycle.policy_for",
                       return_value=policy), \
                 patch("harness.hourglass_lifecycle.governor_for",
                       return_value=(None, MagicMock())), \
                 patch("harness.hourglass_lifecycle.ledger_for",
                       return_value=MagicMock()), \
                 patch("harness.web.fetch_url", return_value=page) as mf, \
                 patch("harness.web.search_web") as ms, \
                 patch("harness.hourglass_lifecycle.render_site_evidence",
                       side_effect=AssertionError("skip browser")), \
                 patch("harness.hourglass_lifecycle.chat_routed",
                       return_value=(200, self._REPLY)), \
                 patch("harness.hourglass_lifecycle.save_chat_turn"):
                res = agent.run_prompt(
                    url_prompt, session_id="rp-url-415",
                    force_conversation=True, web=True)
            mf.assert_called_once()
            ms.assert_not_called()
            self.assertEqual(res["research_plan"]["state"], "accepted")
            self.assertEqual(res["research_plan"]["fetch_calls"], 1)
            self.assertTrue(res["web_used"])


if __name__ == "__main__":
    unittest.main()
