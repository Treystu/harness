"""#660 line 1: the shared web-result reviewer and its admission rule.

A gathered result gets one typed verdict -- relevant, rejected, or uncertain.
Rejected and uncertain results are absent from the evidence handed to the
model, never merely down-ranked. When the reviewer cannot answer at all the
run fails closed (oversight decision 7078539288): every result is withheld and
the outage is disclosed, so nothing unreviewed is admitted as reviewed.
"""
import copy
import os
import tempfile
import unittest
from unittest import mock

from harness.config import load_settings
from harness.conversation_lifecycle import ConversationLifecycleMixin
from harness.errors import HarnessError, ProviderUsageUnknown, ToolCancelled
from harness.jev import JevEvaluationResult
from tests._researchplan import accepted_plan

from harness.jev_policy import (
    RESULT_REJECTED,
    RESULT_RELEVANT,
    RESULT_UNCERTAIN,
    RESULT_UNREVIEWED,
    policy_for,
    result_verdict,
)
from harness.ledger import AutonomyLedger
from harness.provider_errors import ProviderSpendLimitError
from harness.spend import SpendGovernor
from harness.web import apply_result_review, gather_web_context, source_label
from tests._fake import FakeTransport


def _noul(value):
    return {"type": "noul", "noul": value}


class _ResultTransport:
    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def post(self, url, key, payload, timeout=45):
        self.calls.append(payload)
        return 200, {
            "model": "jev-test",
            "answers": self.answers,
            "usage": {"input_tokens": 20, "output_tokens": 2},
        }


def _results():
    return [
        {"kind": "search", "ok": True, "evidence": "snippet",
         "url": "https://a.test/1", "title": "one", "text": "alpha beta"},
        {"kind": "search", "ok": True, "evidence": "snippet",
         "url": "https://a.test/2", "title": "two", "text": "gamma"},
        {"kind": "fetch", "ok": True, "evidence": "rendered",
         "url": "https://a.test/3", "title": "three", "text": "delta"},
    ]


class _FakeReviewer:
    """Duck-typed reviewer: the admission rule is what these tests pin."""

    keyed = True

    def __init__(self, verdicts, *, outage=False, reason=""):
        self.verdicts = verdicts
        self.outage = outage
        self.reason = reason
        self.calls = []

    def evaluate_result_relevance(self, prompt, results, *, site, task_id):
        self.calls.append({"prompt": prompt, "results": list(results),
                           "site": site, "task_id": task_id})
        return None, {"results": [
            {"url": str(item.get("url") or ""), "verdict": verdict,
             "probability": None, "reason": "scripted"}
            for item, verdict in zip(results, self.verdicts)],
            "reviewed": not self.outage, "outage": self.outage,
            "outage_reason": self.reason}


class ReviewerPolicyTests(unittest.TestCase):
    def _keyed(self, answers):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        transport = _ResultTransport(answers)
        policy = policy_for(
            load_settings({"jev_api_key": "jev-key"}), transport=transport,
            governor=SpendGovernor(FakeTransport(), "sk-test", max_cost=0.50),
            ledger=AutonomyLedger(os.path.join(td.name, "ledger.jsonl")))
        return policy, transport

    def test_bands_are_typed_on_the_probability(self):
        self.assertEqual(result_verdict(0.95), RESULT_RELEVANT)
        self.assertEqual(result_verdict(0.70), RESULT_RELEVANT)
        self.assertEqual(result_verdict(0.50), RESULT_UNCERTAIN)
        self.assertEqual(result_verdict(0.30), RESULT_REJECTED)
        self.assertEqual(result_verdict(None), RESULT_UNCERTAIN)

    def test_every_result_carries_a_typed_verdict_with_its_reason(self):
        policy, _transport = self._keyed({
            "result_0_relevant": _noul(0.91),
            "result_1_relevant": _noul(0.50),
            "result_2_relevant": _noul(0.07),
        })
        _result, structural = policy.evaluate_result_relevance(
            "alpha beta", _results(), site="web-results")
        verdicts = structural["results"]
        self.assertEqual([v["verdict"] for v in verdicts],
                         [RESULT_RELEVANT, RESULT_UNCERTAIN, RESULT_REJECTED])
        self.assertEqual([v["url"] for v in verdicts],
                         ["https://a.test/1", "https://a.test/2",
                          "https://a.test/3"])
        self.assertTrue(all(v["reason"] for v in verdicts))
        self.assertTrue(structural["reviewed"])
        self.assertFalse(structural["outage"])

    def test_a_missing_answer_is_uncertain_not_admission(self):
        policy, _transport = self._keyed({})
        # A live reviewer that answers only some of the pack: the unanswered
        # results must not borrow the answered one's verdict.
        policy.evaluator.evaluate = lambda state, pack: JevEvaluationResult(
            "pass", 0.0, 1.0,
            {"result_0_relevant": {"type": "noul", "noul": 0.92}},
            ["partial answer"], model="jev-test")
        _result, structural = policy.evaluate_result_relevance(
            "alpha beta", _results(), site="web-results")
        verdicts = [v["verdict"] for v in structural["results"]]
        self.assertEqual(verdicts[0], RESULT_RELEVANT)
        self.assertEqual(verdicts[1], RESULT_UNCERTAIN)
        self.assertIn("no answer", structural["results"][1]["reason"])

    def test_a_reviewer_refusal_is_an_outage_not_an_admission(self):
        policy, _transport = self._keyed({})
        policy.evaluator.evaluate = lambda state, pack: JevEvaluationResult(
            "fail", 0.0, 0.0, {}, ["evaluator refused"],
            is_fallback=True, model="jev-test",
            fallback_reason="evaluator_refusal")
        _result, structural = policy.evaluate_result_relevance(
            "alpha beta", _results(), site="web-results")
        self.assertTrue(structural["outage"])
        self.assertFalse(structural["reviewed"])
        self.assertEqual(structural["outage_reason"], "evaluator_refusal")
        self.assertEqual([v["verdict"] for v in structural["results"]],
                         [RESULT_UNREVIEWED] * 3)

    def test_unkeyed_admits_and_names_the_method_it_used(self):
        settings = load_settings()
        settings.jev_api_key = None
        policy = policy_for(settings)
        _result, structural = policy.evaluate_result_relevance(
            "verify the claim", _results(), site="web-results")
        verdicts = [v["verdict"] for v in structural["results"]]
        self.assertEqual(verdicts, [RESULT_RELEVANT] * 3)
        for verdict in structural["results"]:
            self.assertIn("no native reviewer", verdict["reason"])
        self.assertEqual(_result.fallback_reason, "reviewer_unkeyed")
        self.assertTrue(structural["reviewed"])


class ReviewerFailureTests(unittest.TestCase):
    """Every way the reviewer can fail, and what admission does about it."""

    def _policy(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        policy = policy_for(
            load_settings({"jev_api_key": "jev-key"}),
            transport=_ResultTransport({}),
            governor=SpendGovernor(FakeTransport(), "sk-test", max_cost=0.50),
            ledger=AutonomyLedger(os.path.join(td.name, "ledger.jsonl")))
        return policy

    def test_no_results_is_an_honest_empty_review(self):
        policy = self._policy()
        result, structural = policy.evaluate_result_relevance(
            "anything", [], site="web-results")
        self.assertEqual(structural["results"], [])
        self.assertFalse(structural["reviewed"])
        self.assertFalse(structural["outage"])
        self.assertEqual(result.fallback_reason, "no_results")

    def test_a_budget_refusal_is_recorded_and_fails_closed(self):
        policy = self._policy()

        def refuse(state, pack):
            raise HarnessError("budget exhausted")

        policy.evaluator.evaluate = refuse
        _result, structural = policy.evaluate_result_relevance(
            "alpha beta", _results(), site="web-results")
        self.assertTrue(structural["outage"])
        self.assertIn("budget exhausted", structural["outage_reason"])
        self.assertEqual([v["verdict"] for v in structural["results"]],
                         [RESULT_UNREVIEWED] * 3)
        refusals = [event for event in policy.ledger.entries()
                    if event["event"] == "jev_refusal"]
        self.assertEqual(len(refusals), 1)

    def test_a_provider_spend_limit_is_an_outage_not_an_exception(self):
        policy = self._policy()

        def limit(state, pack):
            raise ProviderSpendLimitError("credits exhausted", http_status=402)

        policy.evaluator.evaluate = limit
        _result, structural = policy.evaluate_result_relevance(
            "alpha beta", _results(), site="web-results")
        self.assertTrue(structural["outage"])
        self.assertEqual([v["verdict"] for v in structural["results"]],
                         [RESULT_UNREVIEWED] * 3)

    def test_a_cancel_still_propagates(self):
        policy = self._policy()

        def cancel(state, pack):
            raise ToolCancelled("cancelled by user")

        policy.evaluator.evaluate = cancel
        with self.assertRaises(ToolCancelled):
            policy.evaluate_result_relevance(
                "alpha beta", _results(), site="web-results")

    def test_unknown_usage_still_propagates(self):
        policy = self._policy()

        def lost(state, pack):
            raise ProviderUsageUnknown("usage response lost")

        policy.evaluator.evaluate = lost
        with self.assertRaises(ProviderUsageUnknown):
            policy.evaluate_result_relevance(
                "alpha beta", _results(), site="web-results")


class ResultAdmissionTests(unittest.TestCase):
    def _review(self, reviewer, sources):
        with mock.patch("harness.web.emit") as emitted:
            out = apply_result_review("alpha beta", sources, reviewer)
        return out, emitted

    def test_rejected_and_uncertain_results_are_absent_from_the_evidence(self):
        reviewer = _FakeReviewer(
            [RESULT_RELEVANT, RESULT_UNCERTAIN, RESULT_REJECTED])
        out, emitted = self._review(reviewer, _results())
        self.assertEqual([s["url"] for s in out], ["https://a.test/1"])
        excluded = [call for call in emitted.call_args_list
                    if call.args and call.args[0] == "web_result_excluded"]
        self.assertEqual([call.kwargs["verdict"] for call in excluded],
                         [RESULT_UNCERTAIN, RESULT_REJECTED])
        # The verdict rides on the admitted source for the run record.
        self.assertEqual(out[0]["review"]["verdict"], RESULT_RELEVANT)

    def test_exclusion_keeps_the_snippet_versus_rendered_label(self):
        reviewer = _FakeReviewer([RESULT_RELEVANT, RESULT_REJECTED,
                                  RESULT_RELEVANT])
        out, _emitted = self._review(reviewer, _results())
        self.assertEqual([source_label(s) for s in out],
                         ["search snippet", "fetch rendered page"])

    def test_a_page_named_by_the_request_is_admitted_by_naming(self):
        sources = _results()
        sources[0]["pinned"] = True
        reviewer = _FakeReviewer([RESULT_REJECTED, RESULT_REJECTED])
        out, _emitted = self._review(reviewer, sources)
        self.assertEqual([s["url"] for s in out], ["https://a.test/1"])
        self.assertEqual(out[0]["review"]["verdict"], RESULT_RELEVANT)
        self.assertEqual(out[0]["review"]["reason"], "named by the request")
        # Only the unpinned results were sent to the reviewer.
        self.assertEqual([r["url"] for r in reviewer.calls[0]["results"]],
                         ["https://a.test/2", "https://a.test/3"])

    def test_a_reviewer_outage_withholds_everything_and_discloses_it(self):
        reviewer = _FakeReviewer([], outage=True, reason="transport error")
        out, emitted = self._review(reviewer, _results())
        self.assertFalse([s for s in out if s.get("ok")])
        marker = [s for s in out if s.get("kind") == "reviewer"]
        self.assertEqual(len(marker), 1)
        self.assertIn("transport error", marker[0]["note"])
        self.assertIn("withheld", marker[0]["note"])
        excluded = [call for call in emitted.call_args_list
                    if call.args and call.args[0] == "web_result_excluded"]
        self.assertEqual([call.kwargs["verdict"] for call in excluded],
                         [RESULT_UNREVIEWED] * 3)
        names = [call.args[0] for call in emitted.call_args_list
                 if call.args]
        self.assertIn("web_result_review_outage", names)

    def test_a_failed_only_gather_has_nothing_to_review(self):
        sources = [{"kind": "search", "ok": False, "note": "offline"}]
        out, emitted = self._review(_FakeReviewer([]), sources)
        self.assertEqual(out, sources)
        emitted.assert_not_called()

    def test_a_named_only_gather_needs_no_review(self):
        sources = _results()[:1]
        sources[0]["pinned"] = True
        reviewer = _FakeReviewer([])
        out, _emitted = self._review(reviewer, sources)
        self.assertEqual(out, sources)
        self.assertEqual(reviewer.calls, [])
        self.assertEqual(sources[0]["review"]["verdict"], RESULT_RELEVANT)

    def test_a_policy_without_the_reviewer_is_reported_and_passes(self):
        out, emitted = self._review(object(), _results())
        self.assertEqual(len(out), 3)
        unavailable = [call for call in emitted.call_args_list
                       if call.args and call.args[0] == "web_result_review_unavailable"]
        self.assertEqual(unavailable[0].kwargs["reason"], "reviewer_absent")

    def test_a_reviewer_that_raises_fails_closed(self):
        class Boom:
            def evaluate_result_relevance(self, *a, **k):
                raise RuntimeError("kaboom")

        out, _emitted = self._review(Boom(), _results())
        self.assertFalse([s for s in out if s.get("ok")])
        marker = [s for s in out if s.get("kind") == "reviewer"]
        self.assertIn("kaboom", marker[0]["note"])

    def test_a_cancel_inside_the_reviewer_still_propagates(self):
        class Cancel:
            def evaluate_result_relevance(self, *a, **k):
                raise ToolCancelled("cancelled during review")

        with self.assertRaises(ToolCancelled):
            apply_result_review("alpha beta", _results(), Cancel())

    def test_a_reviewer_that_cannot_be_built_never_kills_the_chat(self):
        from pathlib import Path
        from harness.agent import AutonomousAgent
        with tempfile.TemporaryDirectory() as tmp:
            agent = AutonomousAgent(settings=load_settings(), root_dir=Path(tmp),
                                    history_dir=Path(tmp))
            reply = {"choices": [{"message": {"content": "answer"}}],
                     "usage": {"cost": 0.0}}
            with mock.patch("harness.jev_policy.policy_for",
                            side_effect=RuntimeError("no governor")), \
                 mock.patch("harness.conversation_lifecycle.gather_web_context",
                            return_value=[]), \
                 mock.patch("harness.conversation_lifecycle.chat_routed",
                            return_value=(200, reply)), \
                 mock.patch("harness.conversation_lifecycle.governor_for",
                            return_value=(None, mock.MagicMock())), \
                 mock.patch("harness.conversation_lifecycle.ledger_for",
                            return_value=mock.MagicMock()):
                result = agent._handle_conversation(
                    "what is new?", "rev-no-policy", web=True)
        self.assertEqual(result.get("status"), "ok")

    def test_a_short_verdict_list_leaves_the_rest_unreviewed(self):
        out, _emitted = self._review(
            _FakeReviewer([RESULT_RELEVANT]), _results())
        self.assertEqual([s["url"] for s in out], ["https://a.test/1"])

    def test_a_prompt_url_fetch_is_marked_named(self):
        sources = gather_web_context(
            "read https://a.test/x", allowed_hosts=frozenset({"a.test"}),
            fetch_url_fn=lambda url, **kw: {"url": url, "title": "t",
                                            "text": "body"},
            search_web_fn=lambda q: [],
            find_urls_fn=lambda p: ["https://a.test/x"],
            extract_query_fn=lambda p: "")
        self.assertTrue(sources[0]["ok"])
        self.assertTrue(sources[0]["pinned"])

    def test_the_conversation_evidence_block_discloses_a_reviewer_outage(self):
        from pathlib import Path
        from harness.agent import AutonomousAgent
        with tempfile.TemporaryDirectory() as tmp:
            agent = AutonomousAgent(settings=load_settings(), root_dir=Path(tmp),
                                    history_dir=Path(tmp))
            marker = [{"kind": "reviewer", "ok": False,
                       "note": "reviewer down"}]
            reply = {"choices": [{"message": {"content": "answer"}}],
                     "usage": {"cost": 0.0}}
            with mock.patch("harness.conversation_lifecycle.gather_web_context",
                            return_value=marker), \
                 mock.patch("harness.conversation_lifecycle.chat_routed",
                            return_value=(200, reply)) as chat, \
                 mock.patch("harness.conversation_lifecycle.governor_for",
                            return_value=(None, mock.MagicMock())), \
                 mock.patch("harness.conversation_lifecycle.ledger_for",
                            return_value=mock.MagicMock()):
                result = agent._handle_conversation(
                    "what is new?", "rev-outage", web=True)
        self.assertEqual(result.get("status"), "ok")
        call = chat.call_args
        messages = call.kwargs.get("messages")
        if messages is None:
            messages = call.args[3]
        self.assertTrue(any("EVIDENCE REVIEW: reviewer down" in m["content"]
                            for m in messages if m["role"] == "system"))

    def test_without_a_reviewer_the_sources_pass_and_the_run_says_so(self):
        sources = _results()
        out, emitted = self._review(None, sources)
        self.assertEqual(out, sources)
        self.assertIn("web_result_review_unavailable",
                      [call.args[0] for call in emitted.call_args_list
                       if call.args])

    def test_one_shared_point_admits_for_both_retrieval_paths(self):
        from harness.agent import AutonomousAgent
        agent = AutonomousAgent(settings=load_settings(), root_dir=None)
        self.assertIs(getattr(agent, "_gather_web_context").__func__,
                      ConversationLifecycleMixin._gather_web_context)
        reviewer = _FakeReviewer(
            [RESULT_RELEVANT, RESULT_REJECTED, RESULT_REJECTED])
        with mock.patch("harness.conversation_lifecycle.gather_web_context",
                        return_value=copy.deepcopy(_results())):
            out = agent._gather_web_context("alpha beta", [],
                                            jev_policy=reviewer,
                                            task_id="sess-1")
        self.assertEqual([s["url"] for s in out], ["https://a.test/1"])
        self.assertEqual(reviewer.calls[0]["task_id"], "sess-1")

    def test_the_hourglass_evidence_block_discloses_a_reviewer_outage(self):
        from pathlib import Path
        from harness.agent import AutonomousAgent
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent = AutonomousAgent(settings=load_settings(), root_dir=root,
                                    history_dir=root)
            reviewer = _FakeReviewer([], outage=True, reason="spend limit")
            prompt = "what is alpha beta?"
            plan, approval = accepted_plan(prompt)
            with mock.patch(
                    "harness.conversation_lifecycle.gather_web_context",
                    return_value=copy.deepcopy(_results()[:1])):
                context, _files, _brief, sources = \
                    agent._hourglass_request_context(
                        prompt, web=True, workspace=False,
                        jev_policy=reviewer, plan=plan, approval=approval,
                        request_id="req-1")
        self.assertIn("EVIDENCE REVIEW:", context)
        self.assertIn("spend limit", context)
        # No WEB EVIDENCE body and no source URL reached the model.
        self.assertNotIn("WEB EVIDENCE", context)
        self.assertNotIn("https://a.test/1", context)
        self.assertFalse([s for s in sources if s.get("ok")])


if __name__ == "__main__":
    unittest.main()
