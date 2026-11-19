"""Stage composition and budget owner: per-stage ceilings, composition and outcomes.

Owner split per #308: one owner for plan policy and stage-budget decisions --
composition, the narrowing ceiling per stage, the state view, the declared
outcome and the planning ladder. Wanted-stage selection lives in
plan_context because recondense evidence decides it."""
from typing import Any, Dict, List, Optional, Sequence

from .dag import TaskDAG
from .errors import HarnessError
from .token_budget import TokenBudget


from .plan_contracts import (MAX_DEFER_REASON_CHARS, MAX_EVIDENCE_QUESTIONS, MAX_EVIDENCE_QUESTION_CHARS, MAX_EVIDENCE_REQUEST_CHARS, MIN_ROUND_TOKENS, MIN_STAGE_INPUT_TOKENS, MIN_STAGE_OUTPUT_TOKENS, OUTCOME_DEFER, OUTCOME_EVIDENCE_REQUEST, OUTCOME_PLAN, OUTCOME_SUFFICIENT, PLANNING_SHRINK, PLAN_OUTCOMES, STAGE_INPUT_DECAY, STAGE_ORDER, STAGE_OUTPUT_DECAY, STATE_COMPLETED, STATE_PENDING, STATE_SKIPPED)

from .plan_context import resolve_stages


def _narrow(previous: int, factor: float, floor: int) -> int:
    """The next stage's ceiling: strictly smaller, never larger."""
    nxt = int(previous * factor)
    if nxt >= previous:
        nxt = previous - 1
    if previous < floor:
        return max(1, nxt)
    return max(floor, nxt)

def compose_stages(*, budget, declared: Optional[Sequence[str]] = None,
                   supplied_brief: bool = False, supplied_plan: bool = False,
                   brief_tokens: Optional[int] = None,
                   brief: Optional[Dict[str, Any]] = None,
                   reader=None,
                   touched_paths=None,
                   gate_failures=None,
                   freshness=None) -> Dict[str, Any]:
    """Compose the run's stages against ONE ``TokenBudget`` (HV-3).

    ``budget`` is the run's own budget object -- composition never invents an
    allowance, it only asks each stage to narrow the one above it, which is
    what makes "a stage cannot raise its own limits" a structural property
    rather than a promise. Successive stages get strictly smaller ceilings,
    and when the caller measured the curated brief it just produced
    (``brief_tokens``) each later stage is additionally capped at that brief,
    so planning is preflighted against the evidence it will actually read.

    Returns the stage list, the bypassed stages with their reasons, and each
    stage's child budget, so a caller reserves from exactly the right one.
    """
    if budget is None:
        raise HarnessError(
            "stage composition needs the run's TokenBudget; it does not "
            "create one (harness/token_budget.py is the one owner)")
    selection = resolve_stages(declared, supplied_brief=supplied_brief,
                               supplied_plan=supplied_plan, brief=brief,
                               reader=reader, touched_paths=touched_paths,
                               gate_failures=gate_failures,
                               freshness=freshness)
    if brief_tokens is not None:
        brief_tokens = int(brief_tokens)
        if brief_tokens < 0:
            raise HarnessError(
                "brief_tokens cannot be negative: {0}".format(brief_tokens))

    stages: List[Dict[str, Any]] = []
    prev_in = budget.max_input_tokens
    prev_out = budget.max_output_tokens
    for stage in selection["stages"]:
        if not stages:
            # The first stage inherits the run's own ceilings; it is the
            # parent, so it cannot exceed them by construction.
            want_in, want_out = prev_in, prev_out
        else:
            want_in = _narrow(prev_in, STAGE_INPUT_DECAY,
                              MIN_STAGE_INPUT_TOKENS)
            want_out = _narrow(prev_out, STAGE_OUTPUT_DECAY,
                               MIN_STAGE_OUTPUT_TOKENS)
            if brief_tokens is not None:
                # Plan over the brief that exists, not over a guess of it.
                want_in = min(want_in,
                              max(brief_tokens, MIN_STAGE_INPUT_TOKENS))
        if want_in > prev_in or want_out > prev_out:
            raise HarnessError(
                "stage {0!r} asked for ({1}, {2}) above its own ceiling "
                "({3}, {4}); a stage may not raise its own limits"
                .format(stage, want_in, want_out, prev_in, prev_out))
        child = budget.stage(stage, max_input_tokens=want_in,
                             max_output_tokens=want_out)
        stages.append({"stage": stage, "budget": child,
                       "max_input_tokens": want_in,
                       "max_output_tokens": want_out})
        prev_in, prev_out = want_in, want_out

    composed = {"stages": stages, "bypassed": selection["bypassed"],
                "denied": selection["denied"],
                "declared": selection["declared"],
                "run_budget": budget.label}
    if "recondense" in selection:
        # The decision rides with the composition, so "did this run re-condense,
        # and why" is answerable from the envelope alone.
        composed["recondense"] = selection["recondense"]
    return composed

def stage_budget(composition: Dict[str, Any], stage: str):
    """The child budget for one stage, or ``None`` when it did not run."""
    for entry in composition.get("stages") or []:
        if entry.get("stage") == stage:
            return entry.get("budget")
    return None

def stage_states(composition: Dict[str, Any]) -> Dict[str, str]:
    """What happened to each declared stage, for every stage in the contract.

    Composition has *resolved* every stage it budgets; it has not *run* it.
    So a stage this owner only allowed for reports ``pending`` and a stage
    that did not compose reports ``skipped``. A selected stage that is
    silently absent from this map is the one thing a composition must never
    produce, so the map always carries all four declared stages.

    ``completed`` is in the declared vocabulary but has no producer here:
    this owner budgets stages, it does not perform them. A caller that
    actually ran a stage reports that through
    ``composition_envelope(..., states=...)``; dispatching a work package is
    ``HV-5``'s contract.
    """
    composed = {entry.get("stage") for entry in composition.get("stages") or []}
    return {stage: (STATE_PENDING if stage in composed else STATE_SKIPPED)
            for stage in STAGE_ORDER}

def composition_envelope(composition: Dict[str, Any], *,
                         states: Optional[Dict[str, str]] = None
                         ) -> Dict[str, Any]:
    """The serialisable view of a composition -- what lands on the envelope.

    The live child budgets stay out of it on purpose: an envelope is written
    to JSON and compared across runs, and a budget object is neither. What
    survives is the decision -- which stages ran, what each was allowed to
    spend, which were bypassed and why, and where each ended up -- which is
    the part a reader of the plan needs in order to believe the run was
    composed rather than defaulted.
    """
    resolved = states if states is not None else stage_states(composition)
    return {
        "run_budget": composition.get("run_budget"),
        "stages": [
            {"stage": entry.get("stage"),
             "max_input_tokens": entry.get("max_input_tokens"),
             "max_output_tokens": entry.get("max_output_tokens"),
             "state": resolved.get(entry.get("stage"), STATE_PENDING)}
            for entry in composition.get("stages") or []
        ],
        "skipped": [name for name, state in resolved.items()
                    if state == STATE_SKIPPED],
        # Caller-reported completions surface here for the same reason
        # `skipped` does. A stage that did not compose is absent from
        # `stages`, so without this list a stage a caller actually ran -- the
        # `context` stage whose brief the caller curated, say -- would land in
        # NO bucket, and "every declared stage sits in exactly one of
        # completed/skipped/pending" is the invariant this envelope keeps.
        "completed": [name for name, state in resolved.items()
                      if state == STATE_COMPLETED
                      and name not in {entry.get("stage")
                                       for entry in composition.get("stages") or []}],
        "bypassed": dict(composition.get("bypassed") or {}),
        "denied_bypass": dict(composition.get("denied") or {}),
        # Added only when a stage actually ran and supplied its evidence: a
        # stable key would have to say *something* for the pre-composition
        # callers that never make this decision, and "no decision" is not the
        # same fact as "no drift".
        **({"recondense": composition["recondense"]}
           if composition.get("recondense") is not None else {}),
    }

def plan_outcome(kind: str, *, plan: Optional[Dict[str, Any]] = None,
                 questions: Optional[Sequence[str]] = None,
                 reason: Optional[str] = None) -> Dict[str, Any]:
    """The planning waist's terminal contract, fail-closed on every branch.

    Planning either stops (``sufficient``), emits a validated bounded plan,
    asks a bounded evidence request, or defers honestly. A plan is validated
    by ``dag.TaskDAG`` -- the one owner -- so composition cannot bless a DAG
    the executor would reject. A defer must say why: a silent empty plan is
    not an outcome, it is a swallowed failure.

    This is the *validator* the waist emits through. :func:`run_planning`
    routes its own terminal branches back through here, so these bounds are
    live on a real run rather than a contract nothing calls.
    """
    outcome = str(kind or "").strip().lower()
    if outcome not in PLAN_OUTCOMES:
        raise HarnessError(
            "unknown planning outcome {0!r}; the waist may only stop, plan, "
            "request evidence, or defer".format(kind))
    if outcome == OUTCOME_SUFFICIENT:
        return {"outcome": OUTCOME_SUFFICIENT}
    if outcome == OUTCOME_PLAN:
        if not isinstance(plan, dict) or not plan.get("nodes"):
            raise HarnessError(
                "a plan outcome must carry a non-empty plan; an empty plan is "
                "a defer with a reason, not a plan")
        dag = TaskDAG.from_dict(plan)  # validates; raises on a bad DAG
        return {"outcome": OUTCOME_PLAN, "plan": dag.to_dict()}
    if outcome == OUTCOME_EVIDENCE_REQUEST:
        asked = [str(q or "").strip() for q in (questions or [])]
        asked = [q for q in asked if q]
        if not asked:
            raise HarnessError(
                "an evidence request must actually ask something; use a defer "
                "with a reason when there is nothing to ask about")
        if len(asked) > MAX_EVIDENCE_QUESTIONS:
            raise HarnessError(
                "evidence request asks {0} questions, over the bound of {1}"
                .format(len(asked), MAX_EVIDENCE_QUESTIONS))
        for question in asked:
            if len(question) > MAX_EVIDENCE_QUESTION_CHARS:
                raise HarnessError(
                    "evidence question is {0} chars, over the bound of {1}"
                    .format(len(question), MAX_EVIDENCE_QUESTION_CHARS))
        if sum(len(q) for q in asked) > MAX_EVIDENCE_REQUEST_CHARS:
            raise HarnessError(
                "evidence request is over its total character bound")
        return {"outcome": OUTCOME_EVIDENCE_REQUEST, "questions": asked}
    why = str(reason or "").strip()
    if not why:
        raise HarnessError(
            "a defer must state why it deferred; an unexplained defer is a "
            "silent failure")
    if len(why) > MAX_DEFER_REASON_CHARS:
        raise HarnessError(
            "defer reason is {0} chars, over the bound of {1}"
            .format(len(why), MAX_DEFER_REASON_CHARS))
    return {"outcome": OUTCOME_DEFER, "reason": why}

def planning_ladder(stage_budget, *, rounds=2, shrink=PLANNING_SHRINK):
    """Successively narrower budgets for successive planning rounds.

    Each entry is a child of the previous one, so the ladder is structurally
    unable to widen: :class:`~harness.token_budget.TokenBudget` refuses a
    child whose maxima exceed its parent's. A shrink at or above 1.0 is
    refused outright -- a "decreasing" ladder that may hold still is a budget
    that quietly re-widened -- and the ladder stops as soon as a round would
    fall below :data:`MIN_ROUND_TOKENS`, because a request that small cannot
    be asked anything.
    """
    if not isinstance(stage_budget, TokenBudget):
        raise HarnessError("a planning ladder needs a TokenBudget stage")
    if rounds < 1:
        raise HarnessError("a planning ladder needs at least one round")
    if not 0 < shrink < 1:
        raise HarnessError(
            "planning shrink must narrow the ladder (0 < shrink < 1); got "
            "{0!r}".format(shrink))
    ladder = [stage_budget]
    while len(ladder) < rounds:
        previous = ladder[-1]
        nxt = int(previous.max_input_tokens * shrink)
        if nxt < MIN_ROUND_TOKENS or nxt >= previous.max_input_tokens:
            break
        ladder.append(previous.stage(
            "planning-round-{0}".format(len(ladder) + 1),
            max_input_tokens=nxt))
    return ladder
