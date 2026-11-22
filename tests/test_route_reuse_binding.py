"""#344: a saved native route decision is bound to the request it judged.

The recorded remainder was a resumed checkpoint whose saved ``route_preflight``
was reused for a changed request: the old routing judgment (including a native
web-research or answer choice) was inherited by a turn nothing had routed. The
binding here is the routing receipt that exists in the checkpoint -- what was
chosen, whether it was native, and the request it was chosen for -- plus, since
#342 landed the plan owner, the accepted ResearchPlan hash and the native
receipt that approved it. A checkpoint written before plan binding keeps its
request-only binding; one that records a plan cannot be reused without that
same plan and its accepting native receipt.
"""
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from harness.agent import AutonomousAgent
from harness.config import load_settings
from harness.hourglass_lifecycle import (
    HourglassLifecycleMixin,
    _request_identity,
)
from harness.research_plan import (
    PlanApproval,
    PlanQuery,
    ResearchPlan,
    request_hash_for,
)


class _Holder(HourglassLifecycleMixin):
    def __init__(self, root_dir=None):
        self.root_dir = root_dir


def _checkpoint(prompt="What is 2 + 2?", route=None, identity=None):
    checkpoint = {
        "route": "hourglass",
        "status": "interrupted",
        "stage": "route",
        "prompt": prompt,
        "context": "saved context",
        "context_files": [],
        "context_tokens": 5,
        "file_hashes": {},
        "workspace_root": "",
        "context_updated_at": time.time(),
        "known_cost": 0.0,
        "unknown_liability": 0.0,
        "usage_unknown": False,
        "next_round": 1,
        "rounds": [],
    }
    if route is not None:
        checkpoint["route_preflight"] = route
    if identity is not None:
        checkpoint["route_request_prompt"] = identity
    return checkpoint


_WEB_ROUTE = {"source": "jev_request_workflow", "choice": "web-research",
              "native": True, "cost": 0.002}


def _plan(query="Rust 1.84 release notes"):
    prompt = "What changed in the Rust 1.84 release?"
    return ResearchPlan(
        goal=prompt, request_id="req-344",
        request_hash=request_hash_for("req-344", prompt),
        queries=(PlanQuery("q1", query, "read the changelog"),),
        domains=("blog.rust-lang.org",), freshness="last 30 days",
        evidence_requirements=("official changelog",),
        max_results=3, max_sources=3, timeout_s=10.0,
        max_tokens=2000, max_spend_usd=0.01,
        capabilities=("search",))


def _receipt(plan, *, decision="accept", native=True, **overrides):
    receipt = {"decision": decision, "native": native,
               "plan_hash": plan.hash(), "request_hash": plan.request_hash,
               "revision": plan.revision, "consent_id": "consent-344"}
    receipt.update(overrides)
    return receipt


class SavedRouteBindingTests(unittest.TestCase):
    def setUp(self):
        self.holder = _Holder()

    def test_same_request_reuses_the_saved_route_decision(self):
        cp = _checkpoint(route=dict(_WEB_ROUTE))
        self.assertEqual(
            self.holder._saved_route_decision_reusable(
                cp, "What is 2 + 2?"),
            (True, "reusable"))

    def test_changed_request_cannot_inherit_saved_native_routing(self):
        cp = _checkpoint(route=dict(_WEB_ROUTE))
        reusable, reason = self.holder._saved_route_decision_reusable(
            cp, "What are the ocean tides today")
        self.assertFalse(reusable)
        self.assertEqual(reason, "request-changed")

    def test_binding_uses_the_recorded_request_not_the_saved_prompt(self):
        # A checkpoint can carry a new prompt while its route receipt still
        # belongs to the request that produced it.
        cp = _checkpoint(prompt="What are the ocean tides today",
                         route=dict(_WEB_ROUTE),
                         identity="What is 2 + 2?")
        self.assertFalse(self.holder._saved_route_decision_reusable(
            cp, "What are the ocean tides today")[0])
        self.assertTrue(self.holder._saved_route_decision_reusable(
            cp, "What is 2 + 2?")[0])

    def test_identity_ignores_case_and_whitespace(self):
        cp = _checkpoint(route=dict(_WEB_ROUTE),
                         identity="  what IS 2 + 2? ")
        self.assertTrue(self.holder._saved_route_decision_reusable(
            cp, "What is 2 + 2?")[0])
        self.assertEqual(_request_identity("  What IS 2 + 2? "),
                         _request_identity("what is 2 + 2?"))

    def test_no_saved_route_is_not_reused(self):
        cp = _checkpoint(prompt="What is 2 + 2?")
        self.assertEqual(
            self.holder._saved_route_decision_reusable(cp, "What is 2 + 2?"),
            (False, "no-saved-route"))
        cp["route_preflight"] = {}
        self.assertEqual(
            self.holder._saved_route_decision_reusable(cp, "What is 2 + 2?"),
            (False, "no-saved-route"))

    def test_missing_request_identity_fails_closed(self):
        cp = _checkpoint(route=dict(_WEB_ROUTE),
                         identity="What is 2 + 2?")
        del cp["prompt"]
        del cp["route_request_prompt"]
        self.assertEqual(
            self.holder._saved_route_decision_reusable(cp, "What is 2 + 2?"),
            (False, "route-request-unknown"))
        cp["prompt"] = "   "
        self.assertEqual(
            self.holder._saved_route_decision_reusable(cp, "What is 2 + 2?"),
            (False, "route-request-unknown"))


def _settings():
    settings = load_settings()
    settings.jev_api_key = None
    settings.jev_disabled = True
    settings.allow_escalation = False
    settings.hourglass_confirm = False
    settings.hourglass_isolate = False
    settings.hourglass_parallel = False
    return settings


def _envelope():
    return {
        "native": True, "is_fallback": False, "verdict": "pass",
        "confidence": {"observed": 0.95}, "supported": 0.95, "reasons": [],
    }


def _policy(answer="2 + 2 = 4"):
    policy = MagicMock()
    policy.evaluate_answer.return_value = (
        SimpleNamespace(verdict="pass", is_fallback=False, confidence=0.95),
        {"cost": 0.001, "answer_sufficient": 0.95,
         "iteration_required": False, "plan_required": False},
    )
    policy.evaluate_request_workflow.return_value = (
        SimpleNamespace(answers={"workflow_tier": {"choice": "answer"}},
                        is_fallback=False),
        {"cost": 0.0},
    )
    return policy


class RouteReuseThroughTheAdapterTests(unittest.TestCase):
    def test_changed_request_routes_again_instead_of_inheriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent = AutonomousAgent(settings=_settings(), history_dir=root)
            session_id = "changed-request-route"
            checkpoint = _checkpoint(route=dict(_WEB_ROUTE))
            policy = _policy()
            answers = []
            changed_prompt = "Explain how a bicycle stays upright while moving"

            with patch("harness.hourglass_lifecycle.governor_for",
                       return_value=("key", MagicMock())), \
                 patch("harness.hourglass_lifecycle.ledger_for",
                       return_value=MagicMock()), \
                 patch("harness.hourglass_lifecycle.policy_for",
                       return_value=policy), \
                 patch.object(
                     agent, "_hourglass_request_context",
                     return_value=("rebuilt context", {},
                                   SimpleNamespace(estimated_tokens=5), [])), \
                 patch.object(
                     agent, "_hourglass_answer_once",
                     side_effect=lambda *a, **k: (
                         answers.append(k.get("web")) or {
                             "answer": "tides rise and fall", "model": "cheap",
                             "cost": 0.002})), \
                 patch.object(agent, "_jev_answer_envelope",
                              return_value=_envelope()):
                result = agent.run_hourglass_request(
                    changed_prompt, session_id=session_id, max_rounds=1,
                    resume_state=checkpoint)

            self.assertEqual(result["status"], "ok")
            policy.evaluate_request_workflow.assert_called_once()
            # The saved web-research routing does not ride into an answer
            # turn: the fresh route decided, and the answer ran without web.
            self.assertEqual(answers, [False])
            # The persisted routing record now belongs to the new request and
            # names the fresh decision, not the inherited one.
            saved = agent.lifecycle.load(session_id)["data"]
            self.assertEqual(saved["route_request_prompt"], changed_prompt)
            self.assertEqual(saved["route_preflight"]["source"],
                             "jev_request_workflow")
            self.assertEqual(saved["route_preflight"]["choice"], "answer")

    def test_unchanged_request_keeps_the_saved_route_without_paying_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent = AutonomousAgent(settings=_settings(), history_dir=root)
            session_id = "unchanged-request-route"
            checkpoint = _checkpoint(
                route={"source": "jev_request_workflow",
                       "choice": "answer", "native": True, "cost": 0.002})
            policy = _policy()

            with patch("harness.hourglass_lifecycle.governor_for",
                       return_value=("key", MagicMock())), \
                 patch("harness.hourglass_lifecycle.ledger_for",
                       return_value=MagicMock()), \
                 patch("harness.hourglass_lifecycle.policy_for",
                       return_value=policy), \
                 patch.object(
                     agent, "_hourglass_request_context",
                     side_effect=AssertionError("saved context was lost")), \
                 patch.object(
                     agent, "_hourglass_answer_once",
                     return_value={"answer": "2 + 2 = 4", "model": "cheap",
                                   "cost": 0.002}), \
                 patch.object(agent, "_jev_answer_envelope",
                              return_value=_envelope()):
                result = agent.run_hourglass_request(
                    "What is 2 + 2?", session_id=session_id, max_rounds=1,
                    resume_state=checkpoint)

            self.assertEqual(result["status"], "ok")
            policy.evaluate_request_workflow.assert_not_called()

    def _run_bound(self, agent, session_id, checkpoint, prompt, **extra):
        with patch("harness.hourglass_lifecycle.governor_for",
                   return_value=("key", MagicMock())), \
             patch("harness.hourglass_lifecycle.ledger_for",
                   return_value=MagicMock()), \
             patch("harness.hourglass_lifecycle.policy_for",
                   return_value=_policy()), \
             patch.object(
                 agent, "_hourglass_request_context",
                 return_value=("rebuilt context", {},
                               SimpleNamespace(estimated_tokens=5), [])), \
             patch.object(
                 agent, "_hourglass_answer_once",
                 return_value={"answer": "notes say so", "model": "cheap",
                               "cost": 0.002}), \
             patch.object(agent, "_jev_answer_envelope",
                          return_value=_envelope()):
            return agent.run_hourglass_request(
                prompt, session_id=session_id, max_rounds=1,
                resume_state=checkpoint, **extra)

    def test_the_accepted_plan_is_persisted_with_its_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = AutonomousAgent(settings=_settings(),
                                    history_dir=Path(tmp))
            plan = _plan()
            approval = PlanApproval(
                decision="accept", native=True, plan_hash=plan.hash(),
                request_hash=plan.request_hash, revision=0,
                consent_id="consent-344")
            prompt = "What changed in the Rust 1.84 release?"
            self._run_bound(agent, "plan-write", None, prompt,
                            research_plan=plan, plan_approval=approval)
            saved = agent.lifecycle.load("plan-write")["data"]
            self.assertEqual(saved["approved_plan_hash"], plan.hash())
            self.assertEqual(saved["plan_approval"]["decision"], "accept")
            self.assertTrue(saved["plan_approval"]["native"])
            self.assertEqual(saved["plan_approval"]["consent_id"],
                             "consent-344")

    def test_a_changed_plan_routes_again_instead_of_inheriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = AutonomousAgent(settings=_settings(),
                                    history_dir=Path(tmp))
            first = _plan()
            prompt = "What changed in the Rust 1.84 release?"
            checkpoint = _checkpoint(prompt=prompt, route=dict(_WEB_ROUTE))
            checkpoint["approved_plan_hash"] = first.hash()
            checkpoint["plan_approval"] = _receipt(first)
            policy = _policy()
            with patch("harness.hourglass_lifecycle.governor_for",
                       return_value=("key", MagicMock())), \
                 patch("harness.hourglass_lifecycle.ledger_for",
                       return_value=MagicMock()), \
                 patch("harness.hourglass_lifecycle.policy_for",
                       return_value=policy), \
                 patch.object(
                     agent, "_hourglass_request_context",
                     return_value=("rebuilt context", {},
                                   SimpleNamespace(estimated_tokens=5), [])), \
                 patch.object(
                     agent, "_hourglass_answer_once",
                     return_value={"answer": "notes say so", "model": "cheap",
                                   "cost": 0.002}), \
                 patch.object(agent, "_jev_answer_envelope",
                              return_value=_envelope()):
                agent.run_hourglass_request(
                    prompt, session_id="plan-changed", max_rounds=1,
                    resume_state=checkpoint,
                    research_plan=_plan("Rust 1.85 release notes"))
            policy.evaluate_request_workflow.assert_called()


class PlanBindingTests(unittest.TestCase):
    """#344: the saved decision is also bound to the accepted plan."""

    def setUp(self):
        self.holder = _Holder()
        self.plan = _plan()
        self.prompt = "What changed in the Rust 1.84 release?"

    def _check(self, plan_fields=None, plan=None, approval=None):
        checkpoint = _checkpoint(prompt=self.prompt, route=_WEB_ROUTE,
                                 identity=self.prompt)
        if plan_fields is not None:
            checkpoint.update(plan_fields)
        return self.holder._saved_route_decision_reusable(
            checkpoint, self.prompt, plan=plan, approval=approval)

    def test_the_same_plan_with_its_native_receipt_is_reusable(self):
        fields = {"approved_plan_hash": self.plan.hash(),
                  "plan_approval": _receipt(self.plan)}
        self.assertEqual(self._check(fields, plan=self.plan),
                         (True, "reusable"))

    def test_a_changed_plan_routes_again(self):
        fields = {"approved_plan_hash": self.plan.hash(),
                  "plan_approval": _receipt(self.plan)}
        self.assertEqual(
            self._check(fields, plan=_plan("Rust 1.85 release notes")),
            (False, "plan-changed"))

    def test_a_missing_live_plan_is_not_reused(self):
        fields = {"approved_plan_hash": self.plan.hash(),
                  "plan_approval": _receipt(self.plan)}
        self.assertEqual(self._check(fields, plan=None),
                         (False, "plan-unknown"))

    def test_a_plan_the_checkpoint_never_saw_is_not_reused(self):
        self.assertEqual(self._check(None, plan=self.plan),
                         (False, "plan-unrecorded"))

    def test_a_checkpoint_without_plan_fields_keeps_request_binding(self):
        self.assertEqual(self._check(None), (True, "reusable"))

    def test_the_receipt_must_exist_and_be_native_and_accepting(self):
        base = {"approved_plan_hash": self.plan.hash()}
        cases = [
            ({}, "plan-receipt-missing"),
            ({"plan_approval": _receipt(self.plan, native=False)},
             "plan-receipt-not-native"),
            ({"plan_approval": _receipt(self.plan, decision="decline")},
             "plan-receipt-declined"),
            ({"plan_approval": _receipt(self.plan, plan_hash="other")},
             "plan-receipt-mismatch"),
        ]
        for fields, expected in cases:
            merged = dict(base)
            merged.update(fields)
            reason = self._check(merged, plan=self.plan)[1]
            self.assertEqual(reason, expected)

    def test_a_live_approval_for_another_plan_is_not_reused(self):
        fields = {"approved_plan_hash": self.plan.hash(),
                  "plan_approval": _receipt(self.plan)}
        other = PlanApproval(decision="accept", native=True,
                            plan_hash="another-plan",
                            request_hash=self.plan.request_hash, revision=0)
        self.assertEqual(self._check(fields, plan=self.plan, approval=other),
                         (False, "plan-approval-mismatch"))


if __name__ == "__main__":
    unittest.main()
