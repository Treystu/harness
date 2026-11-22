"""#342: hermetic acceptance for the shared research plan and its review.

Every negative case asserts the only thing that matters for the issue's
contract: zero search calls and zero fetch calls. No test touches a public
network -- search, fetch and the Jev transport are all injected doubles.
"""
import os
import tempfile
import unittest

from harness.config import load_settings
from harness.errors import HarnessError
from harness.jev import JevEvaluationResult
from harness.jev_policy import policy_for
from harness.ledger import AutonomyLedger
from harness.research_plan import (
    DECISION_ACCEPT,
    DECISION_DECLINE,
    DECISION_UNAVAILABLE,
    PlanApproval,
    PlanQuery,
    ResearchPlan,
    approval_from_judgment,
    execute_plan,
    goal_from_prompt,
    only_quoted,
    request_hash_for,
    validate_plan,
)
from harness.spend import SpendGovernor
from harness.web import gather_web_context
from tests._fake import FakeTransport

PROMPT = "What changed in the Rust 1.84 release?"
REQUEST_ID = "req-342"


def _noul(value):
    return {"type": "noul", "noul": value}


def _choice(name, confidence=0.9):
    return {"type": "choice", "choice": name, "confidence": confidence,
            "probabilities": {name: confidence, "revise": 0.05,
                              "decline": 0.05}}


def _plan(prompt=PROMPT, request_id=REQUEST_ID, **overrides):
    fields = {
        "goal": goal_from_prompt(prompt),
        "request_id": request_id,
        "request_hash": request_hash_for(request_id, prompt),
        "queries": (PlanQuery("q1", "Rust 1.84 release notes",
                              "read the changelog"),),
        "domains": ("blog.rust-lang.org",),
        "freshness": "last 30 days",
        "evidence_requirements": ("official changelog",),
        "max_results": 3,
        "max_sources": 3,
        "timeout_s": 10.0,
        "max_tokens": 2000,
        "max_spend_usd": 0.01,
        "capabilities": ("search", "fetch"),
    }
    fields.update(overrides)
    return ResearchPlan(**fields)


def _approval(plan, **judgment):
    base = {"decision": DECISION_ACCEPT, "native": True, "confidence": 0.9,
            "query_verdicts": [True] * len(plan.queries)}
    base.update(judgment)
    return approval_from_judgment(plan, base)


class _Network:
    """Counted doubles: nothing here can reach the internet."""

    def __init__(self, search_results=None, page_text="release notes body"):
        self.searches = []
        self.fetches = []
        self.search_results = search_results if search_results is not None else [
            {"url": "https://blog.rust-lang.org/1.84", "title": "Rust 1.84",
             "snippet": "the release notes"},
        ]
        self.page_text = page_text

    def search(self, query):
        self.searches.append(query)
        return list(self.search_results)

    def fetch(self, url):
        self.fetches.append(url)
        return {"url": url, "title": "page", "text": self.page_text}

    def run(self, plan, approval, *, prompt=PROMPT,
            request_id=REQUEST_ID, capabilities=("search", "fetch")):
        return execute_plan(
            plan, approval, request_id=request_id, prompt=prompt,
            capabilities=capabilities, search_fn=self.search,
            fetch_fn=self.fetch)


class PlanIdentityTests(unittest.TestCase):
    def test_goal_excludes_quoted_traces_code_and_gate_prose(self):
        prompt = (
            "How do I rotate a deploy key?\n\n"
            "Trace:\n```\nfetch https://entire.io returned 0 chars\n```\n"
            "> iterate until jev feasibility 10 same plan completeness\n"
            'The log said "every gate phrase is quoted here".')
        goal = goal_from_prompt(prompt)
        self.assertIn("rotate a deploy key", goal)
        self.assertNotIn("entire.io", goal)
        self.assertNotIn("jev feasibility", goal)
        self.assertNotIn("gate phrase", goal)
        self.assertTrue(only_quoted("entire.io", prompt))

    def test_hash_is_stable_and_covers_every_compared_field(self):
        plan = _plan()
        self.assertEqual(plan.hash(), _plan().hash())
        self.assertNotEqual(plan.hash(), plan.revised().hash())
        self.assertNotEqual(
            plan.hash(),
            _plan(queries=(PlanQuery("q1", "Rust 1.85 release notes",
                                     "read the changelog"),)).hash())

    def test_request_binding_uses_the_verbatim_request(self):
        plan = _plan()
        self.assertTrue(validate_plan(
            plan, request_id=REQUEST_ID, prompt=PROMPT,
            capabilities=("search",), approval=_approval(plan)).ok)
        changed = validate_plan(
            plan, request_id=REQUEST_ID, prompt=PROMPT + " Also 1.83.",
            capabilities=("search",), approval=_approval(plan))
        self.assertFalse(changed.ok)
        self.assertEqual(changed.code, "request_hash")


class PlanValidationTests(unittest.TestCase):
    def _rejects(self, plan, code, *, approval=None, prompt=PROMPT,
                 capabilities=("search", "fetch")):
        check = validate_plan(
            plan, request_id=REQUEST_ID, prompt=prompt,
            capabilities=capabilities,
            approval=approval if approval is not None else _approval(plan))
        self.assertFalse(check.ok, check)
        self.assertEqual(check.code, code, check.reason)
        return check

    def test_schema_version_is_checked(self):
        self._rejects(_plan(schema_version=99), "schema_version")

    def test_a_plan_without_a_goal_is_invalid(self):
        self._rejects(_plan(goal="   "), "no_goal")

    def test_a_silent_fallback_policy_is_rejected(self):
        self._rejects(_plan(fallback_policy="search-if-empty"),
                      "fallback_policy")

    def test_freshness_and_evidence_requirements_are_required(self):
        self._rejects(_plan(freshness=""), "no_freshness")
        self._rejects(_plan(evidence_requirements=()),
                      "no_evidence_requirements")

    def test_query_ids_strings_and_purposes_are_required(self):
        self._rejects(_plan(queries=(PlanQuery("", "a real query", "p"),)),
                      "query_id_missing")
        self._rejects(_plan(queries=(PlanQuery("q1", "ab", "p"),)),
                      "query_text")
        self._rejects(_plan(queries=(PlanQuery("q1", "a real query", " "),)),
                      "query_purpose")
        self._rejects(_plan(queries=(
            PlanQuery("q1", "a real query", "p"),
            PlanQuery("q1", "another query", "p"))), "query_id_duplicate")

    def test_budget_bands_are_enforced(self):
        self._rejects(_plan(max_results=99), "budget")
        self._rejects(_plan(max_sources=99), "budget")
        self._rejects(_plan(timeout_s=0.0), "budget")
        self._rejects(_plan(max_spend_usd=-1.0), "budget")

    def test_revision_ceiling_is_two(self):
        self._rejects(_plan(revision=3), "revision")

    def test_a_missing_capability_is_typed_and_executes_nothing(self):
        plan = _plan(queries=(PlanQuery(
            "q1", "https://blog.rust-lang.org/1.84", "read the notes",
            url="https://blog.rust-lang.org/1.84"),))
        self._rejects(plan, "capability_missing", capabilities=("search",))

    def test_a_query_kind_the_plan_does_not_declare_is_rejected(self):
        plan = _plan(queries=(PlanQuery(
            "q1", "https://blog.rust-lang.org/1.84", "read the notes",
            url="https://blog.rust-lang.org/1.84"),),
            capabilities=("search",))
        self._rejects(plan, "capability_undeclared")

    def test_quoted_trace_text_is_not_search_intent(self):
        prompt = ("Audit the local repository.\n```\nTrace: iterate until "
                  "jev feasibility 10 same plan completeness output complete\n"
                  "```\n")
        plan = _plan(prompt=prompt, queries=(PlanQuery(
            "q1", "iterate until jev feasibility 10 same plan completeness "
                  "output complete", "gate phrase from the trace"),))
        self._rejects(plan, "quoted_context", prompt=prompt)

    def test_an_approval_is_required_and_must_be_native(self):
        plan = _plan()
        check = validate_plan(
            plan, request_id=REQUEST_ID, prompt=PROMPT,
            capabilities=("search",))
        self.assertEqual(check.code, "approval_missing")
        advisory = PlanApproval(decision=DECISION_ACCEPT, native=False,
                                plan_hash=plan.hash(),
                                request_hash=plan.request_hash,
                                revision=0, query_verdicts=(True,))
        check = validate_plan(
            plan, request_id=REQUEST_ID, prompt=PROMPT,
            capabilities=("search",), approval=advisory)
        self.assertEqual(check.code, "approval_not_native")

    def test_a_declined_native_judgment_is_not_an_approval(self):
        plan = _plan()
        self._rejects(plan, "approval_declined",
                      approval=_approval(plan, decision=DECISION_DECLINE))

    def test_an_approval_judges_this_plan_this_revision_this_request(self):
        plan = _plan()
        self._rejects(plan, "approval_hash", approval=_approval(
            plan.revised()))
        self._rejects(plan, "approval_revision", approval=PlanApproval(
            decision=DECISION_ACCEPT, native=True, plan_hash=plan.hash(),
            request_hash=plan.request_hash, revision=1,
            query_verdicts=(True,)))
        self._rejects(plan, "approval_request", approval=PlanApproval(
            decision=DECISION_ACCEPT, native=True, plan_hash=plan.hash(),
            request_hash="other", revision=0, query_verdicts=(True,)))

    def test_an_incomplete_query_approval_is_not_an_approval(self):
        plan = _plan()
        self._rejects(plan, "approval_incomplete",
                      approval=_approval(plan, query_verdicts=[]))
        self._rejects(plan, "approval_incomplete",
                      approval=_approval(plan, query_verdicts=[False]))

    def test_stale_consent_cannot_run_a_plan(self):
        plan = _plan()
        approval = _approval(plan)
        approval = PlanApproval(**{**approval.payload(), "expires_at": 10.0})
        check = validate_plan(
            plan, request_id=REQUEST_ID, prompt=PROMPT,
            capabilities=("search",), approval=approval, now=11.0)
        self.assertEqual(check.code, "consent_stale")


class PlanExecutionTests(unittest.TestCase):
    def test_accepted_query_is_sent_exactly_once_and_verbatim(self):
        plan = _plan()
        net = _Network()
        execution = net.run(plan, _approval(plan))
        self.assertEqual(execution.state, "executed")
        self.assertEqual(net.searches, ["Rust 1.84 release notes"])
        self.assertEqual(net.fetches, [])
        self.assertEqual(execution.search_calls, 1)
        self.assertEqual(execution.fetch_calls, 0)
        self.assertEqual(execution.queries_sent, ("Rust 1.84 release notes",))
        self.assertTrue(execution.sources[0]["ok"])

    def test_accepted_url_is_fetched_once_and_never_searched(self):
        url = "https://blog.rust-lang.org/1.84"
        plan = _plan(queries=(PlanQuery("q1", url, "read the notes", url=url),))
        net = _Network()
        execution = net.run(plan, _approval(plan))
        self.assertEqual(execution.state, "executed")
        self.assertEqual(net.fetches, [url])
        self.assertEqual(net.searches, [])

    def test_zero_text_page_is_insufficient_evidence_not_a_search(self):
        url = "https://blog.rust-lang.org/1.84"
        plan = _plan(queries=(PlanQuery("q1", url, "read the notes", url=url),))
        net = _Network(page_text="")
        execution = net.run(plan, _approval(plan))
        self.assertEqual(execution.state, "insufficient-evidence")
        self.assertEqual(net.fetches, [url])
        self.assertEqual(net.searches, [])
        self.assertIn("no readable text", execution.reason)

    def test_every_rejection_executes_zero_searches_and_zero_fetches(self):
        plan = _plan()
        cases = [
            ("declined", plan, _approval(plan, decision=DECISION_DECLINE),
             PROMPT, REQUEST_ID, ("search", "fetch")),
            ("unavailable", plan, PlanApproval(
                decision=DECISION_UNAVAILABLE, native=False,
                plan_hash=plan.hash(), request_hash=plan.request_hash,
                revision=0), PROMPT, REQUEST_ID, ("search", "fetch")),
            ("invalid", _plan(schema_version=2), _approval(plan),
             PROMPT, REQUEST_ID, ("search", "fetch")),
            ("unavailable", plan, _approval(plan), PROMPT, REQUEST_ID,
             ("fetch",)),
            ("declined", plan, _approval(plan), PROMPT + " changed",
             REQUEST_ID, ("search", "fetch")),
            ("declined", plan, _approval(plan), PROMPT, "another-request",
             ("search", "fetch")),
        ]
        for expected_state, plan_arg, approval, prompt, request_id, caps in cases:
            net = _Network()
            execution = execute_plan(
                plan_arg, approval, request_id=request_id, prompt=prompt,
                capabilities=caps, search_fn=net.search, fetch_fn=net.fetch)
            self.assertEqual(execution.state, expected_state, execution.reason)
            self.assertEqual(net.searches, [], execution.reason)
            self.assertEqual(net.fetches, [], execution.reason)
            self.assertEqual(execution.search_calls, 0)
            self.assertEqual(execution.fetch_calls, 0)
            self.assertTrue(execution.reason)

    def test_a_provider_failure_is_a_typed_source_not_a_crash(self):
        url = "https://blog.rust-lang.org/1.84"
        plan = _plan(queries=(PlanQuery("q1", url, "read", url=url),))

        def boom(_url):
            raise HarnessError("blocked host")

        execution = execute_plan(
            plan, _approval(plan), request_id=REQUEST_ID, prompt=PROMPT,
            capabilities=("fetch",), search_fn=None, fetch_fn=boom)
        self.assertEqual(execution.fetch_calls, 1)
        self.assertEqual(execution.search_calls, 0)
        self.assertFalse(execution.sources[0]["ok"])
        self.assertIn("blocked host", execution.sources[0]["note"])


class _PlanTransport:
    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def post(self, url, key, payload, timeout=45):
        self.calls.append(payload)
        return 200, {"model": "jev-test", "answers": self.answers,
                     "usage": {"input_tokens": 20, "output_tokens": 2}}


def _state(plan):
    return {"goal": plan.goal, "request_id": plan.request_id,
            "freshness": plan.freshness,
            "queries": [{"query_id": q.query_id, "query": q.query,
                         "purpose": q.purpose, "url": q.url}
                        for q in plan.queries]}


class PlanReviewPolicyTests(unittest.TestCase):
    def _policy(self, answers):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        return policy_for(
            load_settings({"jev_api_key": "jev-key"}),
            transport=_PlanTransport(answers),
            governor=SpendGovernor(FakeTransport(), "sk-test", max_cost=0.50),
            ledger=AutonomyLedger(os.path.join(td.name, "ledger.jsonl")))

    def _review(self, policy, plan):
        return policy.evaluate_research_plan(
            _state(plan), plan_hash=plan.hash(),
            request_hash=plan.request_hash)

    def test_a_native_accept_needs_every_query_acknowledged(self):
        plan = _plan()
        policy = self._policy({
            "plan_decision": _choice("accept"),
            "query_0_relevant": _noul(0.93),
        })
        _result, structural = self._review(policy, plan)
        self.assertEqual(structural["decision"], "accept")
        self.assertTrue(structural["native"])
        self.assertEqual(structural["query_verdicts"], [True])
        self.assertEqual(structural["plan_hash"], plan.hash())
        self.assertEqual(structural["request_hash"], plan.request_hash)
        approval = approval_from_judgment(plan, structural)
        self.assertTrue(validate_plan(
            plan, request_id=REQUEST_ID, prompt=PROMPT,
            capabilities=("search",), approval=approval).ok)

    def test_a_query_the_reviewer_rejects_declines_the_plan(self):
        plan = _plan(queries=(
            PlanQuery("q1", "Rust 1.84 release notes", "changelog"),
            PlanQuery("q2", "unrelated gate phrase", "noise")))
        policy = self._policy({
            "plan_decision": _choice("accept"),
            "query_0_relevant": _noul(0.95),
            "query_1_relevant": _noul(0.05),
        })
        _result, structural = self._review(policy, plan)
        self.assertEqual(structural["decision"], "decline")
        self.assertEqual(structural["query_verdicts"], [True, False])
        approval = approval_from_judgment(plan, structural)
        check = validate_plan(
            plan, request_id=REQUEST_ID, prompt=PROMPT,
            capabilities=("search",), approval=approval)
        self.assertEqual(check.code, "approval_declined")

    def test_incomplete_per_query_answers_are_invalid(self):
        plan = _plan()
        policy = self._policy({"plan_decision": _choice("accept")})
        _result, structural = self._review(policy, plan)
        self.assertEqual(structural["decision"], "invalid")
        self.assertIn("incomplete", structural["decision_reason"])

    def test_an_unparseable_decision_is_invalid(self):
        plan = _plan()
        policy = self._policy({
            "plan_decision": {"type": "noul", "noul": 0.9},
            "query_0_relevant": _noul(0.9),
        })
        _result, structural = self._review(policy, plan)
        self.assertEqual(structural["decision"], "invalid")

    def test_unkeyed_never_approves(self):
        settings = load_settings()
        settings.jev_api_key = None
        policy = policy_for(settings)
        plan = _plan()
        _result, structural = self._review(policy, plan)
        self.assertEqual(structural["decision"], "unavailable")
        self.assertFalse(structural["native"])
        self.assertFalse(structural["reviewed"])
        approval = approval_from_judgment(plan, structural)
        self.assertFalse(approval.native)

    def test_a_reviewer_refusal_is_unavailable_not_accept(self):
        plan = _plan()
        policy = self._policy({})
        policy.evaluator.evaluate = lambda state, pack: JevEvaluationResult(
            "fail", 0.0, 0.0, {}, ["evaluator refused"],
            is_fallback=True, model="jev-test",
            fallback_reason="evaluator_refusal")
        _result, structural = self._review(policy, plan)
        self.assertEqual(structural["decision"], "unavailable")
        self.assertTrue(structural["outage"])
        self.assertFalse(structural["native"])

    def test_a_reviewer_transport_error_is_unavailable(self):
        plan = _plan()
        policy = self._policy({})
        def boom(state, pack):
            raise HarnessError("transport down")
        policy.evaluator.evaluate = boom
        _result, structural = self._review(policy, plan)
        self.assertEqual(structural["decision"], "unavailable")
        self.assertIn("transport down", structural["outage_reason"])


class GatherPlanPathTests(unittest.TestCase):
    def test_the_plan_path_sends_only_the_approved_exact_query(self):
        plan = _plan()
        net = _Network()
        sources = gather_web_context(
            PROMPT, plan=plan, approval=_approval(plan), request_id=REQUEST_ID,
            search_web_fn=net.search, fetch_url_fn=net.fetch,
            find_urls_fn=lambda _p: ["https://evil.test/page here"],
            extract_query_fn=lambda _p: "invented query")
        self.assertEqual(net.searches, ["Rust 1.84 release notes"])
        self.assertEqual(net.fetches, [])
        self.assertTrue(sources and sources[0]["ok"])

    def test_an_unapproved_plan_touches_network_nowhere(self):
        plan = _plan()
        net = _Network()
        sources = gather_web_context(
            PROMPT, plan=plan, approval=None, request_id=REQUEST_ID,
            search_web_fn=net.search, fetch_url_fn=net.fetch)
        self.assertEqual(net.searches, [])
        self.assertEqual(net.fetches, [])
        self.assertEqual(sources, [])

    def test_the_legacy_path_still_runs_without_a_plan(self):
        net = _Network()
        sources = gather_web_context(
            "Rust 1.84 release notes", search_web_fn=net.search,
            fetch_url_fn=net.fetch,
            find_urls_fn=lambda _p: [],
            extract_query_fn=lambda p: p)
        self.assertEqual(net.searches, ["Rust 1.84 release notes"])
        self.assertTrue(sources)


if __name__ == "__main__":
    unittest.main()
