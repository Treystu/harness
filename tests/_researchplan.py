"""Accepted research-plan fixtures for the #342 retrieval gate.

The hourglass retrieval seam now requires a plan a native judgment accepted
(``harness.research_plan.validate_plan``). Tests that exercise gathering or
rendering must supply one, exactly as the lifecycle proposer does at runtime;
tests that exercise the refusal path pass nothing.
"""
from harness.research_plan import approval_from_judgment, propose_plan


def accepted_plan(prompt, request_id="req-1", confidence=0.9):
    """Propose a plan for ``prompt`` and band an accepting native judgment."""
    plan, why = propose_plan(prompt, request_id=request_id)
    assert plan is not None, why
    approval = approval_from_judgment(plan, {
        "decision": "accept", "native": True, "confidence": confidence,
        "query_verdicts": [True] * len(plan.queries)})
    return plan, approval


def declined_plan(prompt, request_id="req-1"):
    """A plan whose native judgment declined, with a complete query review."""
    plan, why = propose_plan(prompt, request_id=request_id)
    assert plan is not None, why
    approval = approval_from_judgment(plan, {
        "decision": "decline", "native": True, "confidence": 0.9,
        "query_verdicts": [True] * len(plan.queries)})
    return plan, approval
