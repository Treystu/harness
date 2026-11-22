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
from harness.jev import JevEvaluationResult
from harness.jev_policy import (
    RESULT_REJECTED,
    RESULT_RELEVANT,
    RESULT_UNCERTAIN,
    RESULT_UNREVIEWED,
    policy_for,
    result_verdict,
)
from harness.ledger import AutonomyLedger
from harness.spend import SpendGovernor
from harness.web import apply_result_review, source_label
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
            with mock.patch(
                    "harness.conversation_lifecycle.gather_web_context",
                    return_value=copy.deepcopy(_results()[:1])):
                context, _files, _brief, sources = \
                    agent._hourglass_request_context(
                        "what is alpha beta?", web=True, workspace=False,
                        jev_policy=reviewer)
        self.assertIn("EVIDENCE REVIEW:", context)
        self.assertIn("spend limit", context)
        # No WEB EVIDENCE body and no source URL reached the model.
        self.assertNotIn("WEB EVIDENCE", context)
        self.assertNotIn("https://a.test/1", context)
        self.assertFalse([s for s in sources if s.get("ok")])


if __name__ == "__main__":
    unittest.main()
