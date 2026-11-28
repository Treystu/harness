"""Accepted research-plan fixtures for the #342 retrieval gate.

The hourglass retrieval seam now requires a plan a native judgment accepted
(``harness.research_plan.validate_plan``). Tests that exercise gathering or
rendering must supply one, exactly as the lifecycle proposer does at runtime;
tests that exercise the refusal path pass nothing.
"""
from types import SimpleNamespace

from harness.research_plan import approval_from_judgment, propose_plan


def accepted_plan(prompt, request_id="req-1", confidence=0.9):
    """Propose a plan for ``prompt`` and band an accepting native judgment."""
    plan, why = propose_plan(prompt, request_id=request_id)
    assert plan is not None, why
    approval = approval_from_judgment(plan, {
        "decision": "accept", "native": True, "confidence": confidence,
        "query_verdicts": [True] * len(plan.queries)})
    return plan, approval


class AcceptingPlanPolicy:
    """A policy double that returns a native accepting plan judgment.

    Lanes that propose their own plan ask this reviewer to judge it. Tests
    that exercise retrieval need that approval to be native: an unkeyed
    reviewer closes the path by design, so the double stands in for the
    reviewer only -- the proposal, the gate and the validation stay real.
    """

    def __init__(self, decision="accept", native=True, confidence=0.9):
        self.decision = decision
        self.native = native
        self.confidence = confidence
        self.calls = []

    def evaluate_research_plan(self, state, **kwargs):
        self.calls.append(dict(state))
        count = len(state.get("queries") or [])
        return SimpleNamespace(answers={}), {
            "cost": 0.0,
            "native": bool(self.native),
            "decision": self.decision,
            "confidence": float(self.confidence),
            "query_verdicts": [True] * count,
        }

    def evaluate_result_relevance(self, prompt, results, *, site, task_id):
        """The same double stands in for the shared result reviewer."""
        return None, {"results": [
            {"url": str(item.get("url") or ""), "verdict": "relevant"}
            for item in results]}


def declined_plan(prompt, request_id="req-1"):
    """A plan whose native judgment declined, with a complete query review."""
    plan, why = propose_plan(prompt, request_id=request_id)
    assert plan is not None, why
    approval = approval_from_judgment(plan, {
        "decision": "decline", "native": True, "confidence": 0.9,
        "query_verdicts": [True] * len(plan.queries)})
    return plan, approval
