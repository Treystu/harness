import hashlib
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from .brief import (
    MAX_TOTAL_WINDOW_CHARS,
    build_brief,
    estimate_brief_tokens,
    render_brief,
    validate_brief,
)
from .capability import load_profiles, source_budget_for
from .chat import governed_text
from .condenser import distill_context
from .config import CAPABILITIES_PATH, DEFAULT_APPLY_MAX_TOKENS, ESCALATION_POOL_FREE, ESCALATION_POOL_PAID, FREE_JUDGE
from .dag import DAGNode, TaskDAG
from .errors import HarnessError
from .output import eprint
from .prompts import MAX_FILE_LINES
from .repo_scope import discover_verification_gate
from .sliding_scale import resolve_frontier_model, resolve_sliding_scale_route
from .tokens import estimate_prompt_tokens
from .token_budget import TokenBudget
from .validation import MAX_INSTRUCTION_CHARS
from .jev_packs import build_context_pack
from .jev_policy import JevPolicy

from .plan_decompose import (_salvage_decomposition, decompose_via_llm, decomposition_repair_record)

from .plan_contracts import (MAX_EVIDENCE_QUESTIONS, MAX_WAIST_ROUNDS, OUTCOME_DEFER, OUTCOME_EVIDENCE_REQUEST, OUTCOME_PLAN, OUTCOME_SUFFICIENT, PLAN_OUTCOMES, STAGE_CONTEXT, STAGE_PLANNING, STATE_COMPLETED, STATE_SKIPPED, WAIST_MAX_TOKENS)

from .plan_context import _WINDOW_SEARCH_FLOOR

from .plan_stages import (compose_stages, composition_envelope, plan_outcome, planning_ladder, stage_states)

from .plan_consensus import confirm_plan, plan_consensus, plan_task


# Compatibility surface (#308 owner split): these names now live in their owner
# modules; callers outside the plan lane still import them from harness.waist.
# The tuple below is the declaration that keeps that surface deliberate.
from .plan_contracts import (HOURGLASS_DEFAULT_STAGES, MIN_ROUND_TOKENS, MIN_STAGE_INPUT_TOKENS, STAGE_BYPASS_REASONS, STAGE_EXECUTION, STAGE_ORDER, STAGE_STATES, STAGE_VERIFICATION, STATE_PENDING)
from .plan_context import (RECONDENSE_EXECUTED_OVERLAP, RECONDENSE_GATE_FAILURE, RECONDENSE_PIN_DRIFT, RECONDENSE_REASONS, RECONDENSE_TRIGGERS, brief_covered_paths, compose_arguments, intake_brief, recondense_decision, resolve_stages)
from .plan_decompose import (_json_object_candidates, _parse_json_object, _repair_truncated_json, build_decomposition_prompt, heuristic_decompose_goal, parse_decomposition_response)
from .plan_consensus import (_waist_window_request, build_waist_prompt, parse_plan_consensus, parse_waist_verdict, plan_task_id, read_window)
from .plan_stages import (stage_budget)
_COMPAT_308 = (
    HOURGLASS_DEFAULT_STAGES,
    MIN_ROUND_TOKENS,
    MIN_STAGE_INPUT_TOKENS,
    STAGE_BYPASS_REASONS,
    STAGE_EXECUTION,
    STAGE_ORDER,
    STAGE_STATES,
    STAGE_VERIFICATION,
    STATE_PENDING,
    RECONDENSE_EXECUTED_OVERLAP,
    RECONDENSE_GATE_FAILURE,
    RECONDENSE_PIN_DRIFT,
    RECONDENSE_REASONS,
    RECONDENSE_TRIGGERS,
    brief_covered_paths,
    compose_arguments,
    intake_brief,
    recondense_decision,
    resolve_stages,
    _json_object_candidates,
    _parse_json_object,
    _repair_truncated_json,
    build_decomposition_prompt,
    heuristic_decompose_goal,
    parse_decomposition_response,
    _waist_window_request,
    build_waist_prompt,
    parse_plan_consensus,
    parse_waist_verdict,
    plan_task_id,
    read_window,
    stage_budget,
)

DECOMPOSE_MAX_TOKENS = 1024
MAX_BRIEF_FILES = 12


def single_pass_output_tokens(max_tokens: Optional[int] = None) -> int:
    """The output budget ONE model pass really has for a node.

    The lane's pinned ``max_tokens`` when it has one, otherwise the apply
    lane's own default (``config.DEFAULT_APPLY_MAX_TOKENS`` -- the exact
    number ``apply_edit`` falls back to). Chunking measures against this
    budget instead of inventing one of its own.
    """
    try:
        pinned = int(max_tokens)
    except (TypeError, ValueError):
        pinned = 0
    return pinned if pinned > 0 else DEFAULT_APPLY_MAX_TOKENS


def _split_text(text: str, limit: int) -> List[str]:
    """Greedy word-boundary split into pieces of at most ``limit`` chars.

    Nothing is lost or duplicated: every piece concatenates back to the
    original (inter-word whitespace is preserved; only the whitespace at a
    break point is trimmed). A single unbreakable token longer than the
    limit is hard-split, so the bound always holds.
    """
    limit = max(1, int(limit))
    parts: List[str] = []
    current = ""
    for token in re.findall(r"\S+\s*", text):
        while len(token) > limit:
            if current:
                parts.append(current.rstrip())
                current = ""
            parts.append(token[:limit])
            token = token[limit:]
        if current and len(current) + len(token) > limit:
            parts.append(current.rstrip())
            current = ""
        current += token
    if current.strip():
        parts.append(current.rstrip())
    return parts or [text]


def _target_text(root: Optional[str], rel: str) -> Optional[str]:
    """The target file's text from the plan lane's tree (None if unreadable)."""
    path = rel if os.path.isabs(rel) else os.path.join(root or os.getcwd(), rel)
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def _passes_to_read(text: str, source_tokens: int) -> int:
    """How many passes are needed to even READ one target in full.

    This is the only file-size reason to split: when one pass cannot hold
    the file's source. A file that is merely larger than the rewrite cap is
    NOT split -- a bounded-hunk (diff) edit emits only what it changes, so
    it fits one pass. A budget of 0 means UNMEASURED (the rung's declared
    context is unknown), and an unmeasured rung is never given an invented
    limit: nothing is split on the file axis.
    """
    if source_tokens <= 0:
        return 1
    return max(1, math.ceil(estimate_prompt_tokens(text) / source_tokens))


def rung_read_budgets(plan_result: Dict[str, Any],
                      profiles: Optional[Dict[str, Any]] = None
                      ) -> Dict[str, int]:
    """Per-node source-read budget from each node's OWN routing rung.

    The rung is the model the node will actually run on, so its declared
    context (via the capability registry -- offline cache, no fetch) bounds
    what one pass can read. An unknown rung yields 0 (unmeasured), and the
    chunk policy then leaves the file axis alone rather than guessing.
    """
    if profiles is None:
        profiles, _ = load_profiles(CAPABILITIES_PATH)
    budgets: Dict[str, int] = {}
    for detail in plan_result.get("nodes", ()):
        if not isinstance(detail, dict):
            continue
        route = detail.get("route")
        ladder = route.get("ladder") if isinstance(route, dict) else None
        head = str(ladder[0]).strip() if ladder else ""
        profile = profiles.get(head) if head else None
        context = getattr(profile, "context_length", None)
        budgets[str(detail.get("node_id") or "")] = (
            source_budget_for(context) if context else 0)
    return budgets


def _line_ranges(line_count: int, passes: int) -> List[tuple]:
    """Contiguous 1-based line ranges covering the file in EXACTLY ``passes``
    slices.

    The count is fixed by the final chunk count, which can exceed what the
    file's own size implies (a long instruction split over a small file), so
    the tail is padded: the extra passes share the last slice rather than
    leaving a chunk with no range to name.
    """
    passes = max(1, int(passes))
    per = max(1, math.ceil(line_count / passes)) if line_count else 1
    ranges: List[tuple] = []
    start = 1
    while start <= line_count:
        end = min(line_count, start + per - 1)
        ranges.append((start, end))
        start = end + 1
    while len(ranges) < passes:
        ranges.append(ranges[-1] if ranges else (1, 1))
    return ranges[:passes]


def chunk_oversized_nodes(
    dag: TaskDAG,
    *,
    root: Optional[str] = None,
    max_tokens: Optional[int] = None,
    max_lines: int = MAX_FILE_LINES,
    source_tokens=None,
) -> TaskDAG:
    """Split nodes that cannot fit ONE model pass into ordered chunks.

    ONE owner of the chunking policy, and it lives in the plan lane so no
    lane can drift from it. Work is chunked only when one pass genuinely
    cannot do it:

    * the instruction is longer than the apply validation ceiling
      (``validation.MAX_INSTRUCTION_CHARS`` -- such a request could never be
      sent, so it must become several requests), or
    * one pass cannot even READ the target (more estimated tokens than the
      pass's quoted-source budget, ``capability.source_budget_for``; a node
      whose rung declares no context is left alone -- see ``source_tokens``).

    A target past the engine's whole-file rewrite cap (``max_lines``) -- or
    one whose rewrite could not fit the pass's output budget at all -- is
    NOT split: it becomes ONE node carrying the ``backend="diff"`` hint, so
    the pass emits bounded hunks instead of a whole-file rewrite and the
    small edit stays a single call.

    A split node becomes ``max(axes)`` chunks, each inside budget, chained
    in order so the existing DAG dispatch runs them one pass at a time;
    every dependent of the original node now depends on its last chunk, so
    the graph stays acyclic and correctly ordered.

    ``source_tokens`` is the measured read budget: either one int for every
    node, or a ``{node_id: tokens}`` mapping (the plan lane passes each
    node's own rung budget); 0 or a missing entry means unmeasured.

    Returns the SAME dag object when nothing needs splitting, so ordinary
    plans take no detour through this policy.
    """
    if not dag.nodes:
        return dag
    output_tokens = single_pass_output_tokens(max_tokens)

    def budget_for(node_id: str) -> int:
        if isinstance(source_tokens, dict):
            return int(source_tokens.get(node_id) or 0)
        return int(source_tokens or 0)

    chunked: Dict[str, List[DAGNode]] = {}
    replacements: Dict[str, str] = {}
    single_pass_hints: Dict[str, str] = {}
    for node_id, node in dag.nodes.items():
        target = node.target_files[0] if node.target_files else None
        text = _target_text(root, target) if target else None
        line_count = len(text.splitlines()) if text is not None else 0
        passes = 1
        ranges: List[tuple] = []
        if text is not None:
            file_tokens = estimate_prompt_tokens(text)
            # A rewrite that cannot fit one pass is solved by emitting bounded
            # hunks, not by splitting: each range pass would still emit the
            # whole file, so splitting would only add calls.
            if (line_count > max_lines or file_tokens > output_tokens) \
                    and not node.backend:
                single_pass_hints[node_id] = "diff"
            # Splitting is for what one pass cannot read at all.
            passes = _passes_to_read(text, budget_for(node_id))
            if passes > 1:
                ranges = _line_ranges(line_count, passes)

        # Both axes must fit the same chunk set: grow the count until the
        # instruction (split at word boundaries) plus the longest slice
        # marker a chunk will carry stays inside MAX_INSTRUCTION_CHARS.
        while True:
            budget = max(1, MAX_INSTRUCTION_CHARS
                         - len(_slice_marker(passes, ranges, target)))
            if len(_split_text(node.instruction, budget)) <= passes:
                break
            passes += 1
            ranges = _line_ranges(line_count, passes) if line_count else []
        if passes <= 1:
            continue

        budget = max(1, MAX_INSTRUCTION_CHARS
                     - len(_slice_marker(passes, ranges, target)))
        parts = _split_text(node.instruction, budget)
        # Range passes edit bounded hunks of a file that no single pass can
        # hold; instruction-only passes keep the node's own backend.
        backend = (node.backend or single_pass_hints.get(node_id)
                   or ("diff" if line_count > max_lines else None))
        chunks: List[DAGNode] = []
        for index in range(1, passes + 1):
            part = parts[((index - 1) * len(parts)) // passes]
            chunks.append(DAGNode(
                node_id=f"{node_id}.{index}",
                instruction=part + _slice_marker(passes, ranges, target, index),
                target_files=node.target_files,
                dependencies=((f"{node_id}.{index - 1}",) if index > 1
                              else node.dependencies),
                local_gate=node.local_gate,
                complexity_tier=node.complexity_tier,
                backend=backend,
            ))
        chunked[node_id] = chunks
        replacements[node_id] = chunks[-1].node_id

    if not chunked and not single_pass_hints:
        return dag

    nodes: Dict[str, DAGNode] = {}
    for node_id, node in dag.nodes.items():
        if node_id in chunked:
            for chunk in chunked[node_id]:
                nodes[chunk.node_id] = chunk
            continue
        deps = tuple(replacements.get(dep, dep) for dep in node.dependencies)
        backend = node.backend or single_pass_hints.get(node_id)
        if deps == node.dependencies and backend == node.backend:
            nodes[node_id] = node
            continue
        nodes[node_id] = DAGNode(
            node_id=node.node_id,
            instruction=node.instruction,
            target_files=node.target_files,
            dependencies=deps,
            local_gate=node.local_gate,
            complexity_tier=node.complexity_tier,
            backend=backend,
        )
    return TaskDAG(nodes=nodes)


def _slice_marker(passes: int, ranges: List[tuple], target,
                  index: Optional[int] = None) -> str:
    """The slice marker a chunk carries (and the string the budget reserves).

    Called with ``index=None`` it returns the LONGEST marker the split will
    need, so reserving its length keeps every instruction plus marker within
    the apply validation ceiling.
    """
    position = index if index is not None else passes
    marker = f"\n\n[pass {position}/{passes}"
    if ranges and target:
        start, end = ranges[position - 1]
        marker += f"; apply ONLY {target} lines {start}-{end} of {ranges[-1][1]}"
    return marker + "]"


























def _call_worst_case(governor, model, max_tokens) -> float:
    """Worst-case dollar cost of ONE bounded chat call on ``model``.

    Completion-side only (prompt tokens are typically small relative to the
    pinned output budget for plan-lane calls). Free / unpriceable models
    contribute $0.0 -- the node ceilings still bind the run.
    """
    if governor is None or not model:
        return 0.0
    try:
        pricing = governor.fetch_pricing([model])
        _pp, cp = pricing[model]
    except Exception:
        return 0.0
    try:
        return max(0.0, float(max_tokens) * float(cp))
    except (TypeError, ValueError):
        return 0.0


def composed_worst_case(
    plan_result: Dict[str, Any],
    *,
    governor=None,
    decompose_llm: bool = False,
    confirm: bool = False,
    decompose_model: Optional[str] = None,
    frontier_model: Optional[str] = None,
    use_free: bool = True,
    allow_escalation: bool = False,
    plan_consensus: bool = False,
    incurred_stages: Optional[Sequence[str]] = None,
    planning_spent: Optional[float] = None,
) -> Dict[str, Any]:
    """Composed pyramid ceiling over remaining unincurred work (#346).

    ONE owner of the pre-execute worst-case budget. Stages listed in
    ``incurred_stages`` (``"decompose"``, ``"consensus"``, ``"waist"``) have
    already completed and deducted their actual/reserved cost from
    ``governor.remaining()``, so only not-yet-incurred future liability is
    compared against ``governor.remaining()``. Called before spend when a
    governor is present; if remaining liability exceeds
    ``governor.remaining()`` the plan lane REFUSES instead of dispatching
    into an unfunded pyramid.
    """
    node_ceiling = 0.0
    try:
        node_ceiling = float(plan_result.get("total_cost_ceiling") or 0.0)
    except (TypeError, ValueError):
        node_ceiling = 0.0
    if node_ceiling <= 0.0:
        for detail in plan_result.get("nodes") or ():
            if not isinstance(detail, dict):
                continue
            route = detail.get("route") if isinstance(detail.get("route"), dict) else {}
            try:
                node_ceiling += float(route.get("cost_ceiling") or detail.get("cost_ceiling") or 0.0)
            except (TypeError, ValueError):
                continue

    completed = set(incurred_stages or ())
    decompose_cost = 0.0
    waist_cost = 0.0
    consensus_cost = 0.0
    if governor is not None:
        if decompose_llm and "decompose" not in completed:
            model = decompose_model
            if not model:
                try:
                    model = resolve_scout_ladder(use_free=use_free,
                                                 custom_frontier=frontier_model)[0]
                except Exception:
                    model = None
            decompose_cost = _call_worst_case(governor, model, DECOMPOSE_MAX_TOKENS)
        if plan_consensus and "consensus" not in completed:
            model = decompose_model
            if not model:
                try:
                    model = resolve_scout_ladder(use_free=use_free,
                                                 custom_frontier=frontier_model)[0]
                except Exception:
                    model = None
            consensus_cost = _call_worst_case(governor, model, 256)
        if confirm and "waist" not in completed:
            try:
                ladder = resolve_waist_ladder(
                    use_free=use_free, custom_frontier=frontier_model,
                    allow_escalation=allow_escalation)
            except Exception:
                ladder = [frontier_model] if frontier_model else []
            # Worst-case: every ladder rung could be attempted across the
            # window-round budget before one lands.
            for rung in ladder[:4]:
                waist_cost += _call_worst_case(
                    governor, rung, WAIST_MAX_TOKENS * MAX_WAIST_ROUNDS)

    composed = round(node_ceiling + decompose_cost + waist_cost + consensus_cost, 6)
    remaining = None
    if governor is not None and callable(getattr(governor, "remaining", None)):
        try:
            remaining = float(governor.remaining())
        except Exception:
            remaining = None
    plan_ceiling = None
    if governor is not None and getattr(governor, "max_cost", None) is not None:
        try:
            plan_ceiling = round(float(governor.max_cost), 6)
        except (TypeError, ValueError):
            plan_ceiling = None
    envelope = {
        "composed_worst_case": composed,
        "node_ceiling": round(node_ceiling, 6),
        "decompose": round(decompose_cost, 6),
        "waist": round(waist_cost, 6),
        "consensus": round(consensus_cost, 6),
        "remaining": remaining,
        "plan_ceiling": plan_ceiling,
        "exceeds_remaining": (
            None if remaining is None else bool(composed > remaining + 1e-12)),
    }
    if planning_spent is not None:
        spent_val = round(max(0.0, float(planning_spent)), 6)
        envelope["planning_spent"] = spent_val
        envelope["all_in_worst_case"] = round(spent_val + composed, 6)
    return envelope


def _refuse_composed_ceiling(plan_result: Dict[str, Any], composed: Dict[str, Any]) -> Dict[str, Any]:
    """Fail-closed envelope when the composed pyramid ceiling cannot fit."""
    refused = dict(plan_result)
    refused["status"] = "refused"
    refused["composed_worst_case"] = composed
    reason = (
        f"composed worst-case ${composed['composed_worst_case']:.6f} exceeds "
        f"remaining budget ${composed['remaining']:.6f}")
    evidence = (
        f"nodes={composed['node_ceiling']:.6f} "
        f"decompose={composed['decompose']:.6f} "
        f"waist={composed['waist']:.6f} "
        f"consensus={composed['consensus']:.6f}")
    if composed.get("planning_spent") is not None:
        evidence += f" planning_spent={composed['planning_spent']:.6f}"
    refused["confirmation"] = {
        "verdict": "refused",
        "model": "composed-ceiling",
        "rounds": 0,
        "reason": reason,
        "evidence": evidence,
        "cost": 0.0,
    }
    return refused


def _decompose_repo_context(goal: str,
                            candidate_files: Optional[Sequence[str]],
                            root: Optional[str] = None,
                            ledger=None, task_id: Optional[str] = None,
                            ) -> Optional[str]:
    """Condensed signatures for the decompose prompt (HG-condense-decompose).

    ``decompose_via_llm`` / ``build_decomposition_prompt`` already accept
    ``repo_context``; this is the plan lane's producer: distill candidate
    files into signatures so the cheap decomposer never sees raw bodies.
    When a ledger is supplied the condensation is recorded as HV-2
    evidence (``brief_built``, site=hourglass) like every other lane.
    """
    if not candidate_files:
        return None
    files: Dict[str, str] = {}
    for rel in candidate_files:
        rel_s = str(rel)
        path = rel_s if os.path.isabs(rel_s) else os.path.join(root or os.getcwd(), rel_s)
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                files[rel_s] = handle.read()
        except OSError:
            continue
    if not files:
        return None
    brief = distill_context(files, summary=goal or "")
    if ledger is not None:
        ledger.append("brief_built", task_id=task_id, site="hourglass",
                      schema=2, **brief.ledger_fields())
    return brief.to_prompt_context()








# Alias: compose_plan's boolean arm shares the public name ``plan_consensus``.
plan_consensus_check = plan_consensus





def node_apply_kwargs(
    node_detail: Optional[Dict[str, Any]] = None,
    explicit_model: Optional[str] = None,
    explicit_task_max_cost: Optional[float] = None,
    allow_escalation: Optional[bool] = None,
    attest_model: Optional[str] = None,
) -> Dict[str, Any]:
    """Per-request apply kwargs for executing one planned DAG node.

    Threads a node's sliding-scale route (from :func:`plan_task`'s
    ``nodes`` entries) into :meth:`harness.apply.ApplyEngine.apply_edit`:
    the tier ladder becomes the request's ``apply_pool`` -- the engine
    orders it at the routing boundary via ``capability.ordered_pool``
    (interfaces never pre-order a pool) and rotation stays inside the
    tier-appropriate models. The tier cost ceiling becomes the per-task
    ceiling only when it is a real bound (paid tiers): a $0 free-tier
    ceiling is deliberately NOT passed, because a zero task budget would
    refuse the escalation ladder before it could rescue a hard node
    (``spent - start < 0.0`` is never true); free-tier cost discipline is
    the governor's job (every attempted model bills $0.0).

    An explicit model pin wins outright (manual routing, no pool override);
    an explicit ``task_max_cost`` pin suppresses only the ceiling.
    Unknown, missing, or MALFORMED route detail degrades to today's
    defaults ({}): non-mapping detail/route, a non-sequence ladder (a
    string would otherwise become per-character "model ids"), and
    non-finite ceilings are all refused silently -- the governor's
    key-level ceiling still binds, so degradation never fails open.

    ``allow_escalation`` and ``attest_model`` are threaded verbatim when the
    caller supplies them, so a lane whose node can fail a gate carries the
    escalation arming and the verifier identity explicitly instead of
    inheriting them silently from the session defaults. ``None`` omits the
    key, leaving the engine/settings default in charge.
    """
    if explicit_model is not None:
        return {}
    detail = node_detail if isinstance(node_detail, dict) else {}
    route = detail.get("route")
    if not isinstance(route, dict):
        route = {}
    kwargs = {}
    raw_ladder = route.get("ladder")
    if isinstance(raw_ladder, (list, tuple)):
        ladder = [str(m).strip() for m in raw_ladder if str(m).strip()]
        if ladder:
            kwargs["apply_pool"] = ladder
    if explicit_task_max_cost is None:
        try:
            ceiling = float(route.get("cost_ceiling"))
        except (TypeError, ValueError):
            ceiling = 0.0
        if ceiling > 0.0 and math.isfinite(ceiling):
            kwargs["task_max_cost"] = ceiling
    if allow_escalation is not None:
        kwargs["allow_escalation"] = bool(allow_escalation)
    if attest_model:
        kwargs["attest_model"] = str(attest_model)
    # A chunked large-file node carries the engine's own backend vocabulary;
    # anything else stays out (the engine validates it again at the boundary).
    backend = detail.get("backend")
    if backend in ("harness", "morph", "diff"):
        kwargs["backend"] = backend
    return kwargs










# Verdict spellings models actually emit, mapped to the four canonical kinds.
# Deliberately a closed set: an unknown verdict must still fail closed rather
# than be coerced into an approval.

















def compose_plan(*, transport, api_key, governor, ledger, opts_goal,
                 candidate_files=None, frontier_model=None, use_free=True,
                 decompose_llm=False, confirm=False, decompose_model=None,
                 chat_fn=None, max_cost=None, keep_going=False, out=None,
                 execute=False, root=None, max_tokens=None,
                 allow_escalation: bool = False,
                 plan_consensus: bool = False,
                 jev_policy=None,
                 issue_sort_pack=None,
                 allow_heuristic_preview: bool = False,
                 token_budget=None,
                 stages: Optional[Sequence[str]] = None,
                 supplied_brief: bool = False,
                 supplied_plan: bool = False,
                 brief: Optional[Dict[str, Any]] = None,
                 brief_tokens: Optional[int] = None,
                 reader=None,
                 context_judgment: Optional[Dict[str, Any]] = None,
                 **kwargs) -> Dict[str, Any]:
    """ONE owner of the plan-lane flow (CLI and MCP call this).

    Order: optional cheap-LLM decomposition (M1, condensed signatures) ->
    tier classification -> single-pass chunking -> optional cheap plan
    consensus -> optional waist confirmation (M2) over the plan that will
    actually run -> composed pyramid ceiling check before execute spend.

    Decomposition failures retry once, then:
    * ``execute=True`` -- always fall back loudly to the heuristic
      (decomposition='heuristic'; an orchestration event + stderr note).
      The run spends anyway, so a loud fallback keeps it going.
    * ``execute=False`` (plan-only preview) -- FAILS CLOSED by default: the
      operator asked for LLM planning, and silently handing back the
      heuristic plan would be dishonest (raises HarnessError, non-zero
      exit). Passing ``allow_heuristic_preview=True`` (CLI:
      ``--allow-heuristic-preview``) opts into the same loud heuristic
      fallback as execute mode instead -- decomposition='heuristic', a
      loud stderr note, and the waist confirmation step (``confirm``) is
      skipped rather than confirming a plan the operator never got the
      LLM decomposition they asked for: the envelope's ``confirmation``
      is explicitly ``verdict: "skipped"``, never ``"approved"``.

    Fail-closed rules (hourglass composition):
    * confirm=True and EVERY waist rung unreachable on execute -> REFUSE
      (never proceed under the local gate silently).
    * composed_worst_case exceeds governor.remaining() -> REFUSE before
      execute dispatch (spend stays 0 on that path when planning itself
      was injected/hermetic).

    ``root`` is the tree the plan edits (defaults to the process CWD, which
    is what the CLI/MCP lanes edit); ``max_tokens`` is the lane's pinned
    output budget when it has one -- both feed the chunk policy's real
    per-pass budget, none of them add a budget of their own.

    ``issue_sort_pack`` (optional operator bucket pack): when provided with
    a ``jev_policy``, attach the issue-sort combo on the plan envelope as
    ``issue_sort`` via the ONE policy owner (path_id from pack only).

    ``token_budget`` + ``stages`` (HV-4): when the caller supplies the run's
    ``TokenBudget``, the plan lane composes its stages against it and records
    the decision on the envelope as ``composition`` -- which stages ran, what
    each was allowed to spend, and which were bypassed and why. With no
    budget the lane behaves exactly as before (no composition key), because
    composition may not invent an allowance. ``brief_tokens`` is the measured
    size of a brief the caller already curated; supplying it preflights the
    later stages against the evidence they will actually read.

    ``brief`` (HV-2-use) is that brief itself: the ``context`` stage's
    artifact, handed in by the run's caller as its intake evidence. Passing
    the pack rather than only the ``supplied_brief`` flag is what lets the
    ``context`` bypass be decided on real evidence -- the pack's own
    freshness, and the re-condense trigger whenever the caller also reports
    stage evidence -- instead of on a boolean the caller asserts. It is also
    reported as ``completed``, not ``skipped``: composition budgets stages,
    it does not perform them, so a caller that actually produced the
    artifact is the one that can say the stage is done.
    """
    if (decompose_llm or confirm or plan_consensus) and governor is None:
        raise HarnessError("LLM plan features require a governor")

    def _governor_spent():
        if governor is None:
            return 0.0
        try:
            return float(getattr(governor, "spent", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    plan_start_spent = _governor_spent()

    def _evaluate_composed_ceiling(target_plan, *, completed_stages):
        spent_now = max(0.0, _governor_spent() - plan_start_spent)
        composed = composed_worst_case(
            target_plan,
            governor=governor,
            decompose_llm=decompose_llm,
            confirm=confirm and not _degraded_preview_heuristic,
            decompose_model=decompose_model,
            frontier_model=frontier_model,
            use_free=use_free,
            allow_escalation=allow_escalation,
            plan_consensus=bool(plan_consensus and confirm),
            incurred_stages=tuple(completed_stages),
            planning_spent=spent_now,
        )
        target_plan["composed_worst_case"] = composed
        if (execute and governor is not None
                and target_plan.get("status") != "refused"
                and composed.get("exceeds_remaining")):
            from . import events as _events
            _events.emit(
                "orchestration_note",
                note=("composed pyramid ceiling exceeds remaining budget; "
                      "refusing before execute spend"))
            return _refuse_composed_ceiling(target_plan, composed)
        return target_plan

    plan_goal = opts_goal
    plan_structural = None
    plan_triage = None
    plan_issue_sort = None
    jev_route_feed = None
    repo_context = None
    if isinstance(jev_policy, JevPolicy):
        # JEV-P3-route: one typed route choice through the policy owner.
        # Route, plan and issue-sort judge the same state independently, so
        # they fan out in parallel (order-stable; each fails closed alone).
        jobs = [
            ("route", lambda: jev_policy.evaluate_route(
                opts_goal, candidate_files, site="route")),
            ("waist", lambda: jev_policy.evaluate_plan(
                opts_goal, candidate_files, site="waist")),
        ]
        if issue_sort_pack is not None:
            jobs.append((
                "issue_sort",
                lambda: jev_policy.evaluate_issue_sort(
                    {"issue": opts_goal}, issue_sort_pack, site="issue_sort"),
                lambda result, structural: (
                    result, structural, JevPolicy._issue_sort_empty_combo(
                        structural=structural, evidence=result.reasons))))
        fanned = jev_policy.fan_out(jobs)
        route_eval, route_envelope = fanned[0]
        plan_eval, plan_structural = fanned[1]
        plan_triage = dict(route_envelope)
        plan_triage["route"] = route_eval.answers.get("route", "free-distill")
        plan_triage["route_is_fallback"] = bool(route_eval.is_fallback)
        plan_triage["requires_iteration"] = bool(
            plan_eval.answers.get("requires_iteration")
            or route_eval.answers.get("requires_iteration", False))
        if not route_eval.is_fallback:
            jev_route_feed = plan_triage["route"]
        if plan_eval.answers.get("requires_iteration") or plan_triage["requires_iteration"]:
            plan_goal = (
                f"{opts_goal}\n\n[STRUCTURAL GUIDELINE]: This goal requires iterative "
                "control flow, conditional branching, or multi-step execution. "
                "Represent those dependencies explicitly in the executable DAG.")
        if issue_sort_pack is not None:
            _sort_result, _sort_structural, plan_issue_sort = fanned[2]
    # JEV-P3-context-pack: distilled decision-relevant state before generative
    # seats that lack a pack. Smallest seam — pass into LLM decompose.
    if decompose_llm and not repo_context:
        repo_context = build_context_pack(
            opts_goal, candidate_files=candidate_files)

    # The run-level gate: the goal's own candidate files. It is the
    # last-resort arm of the ONE gate rule (repo_scope.gate_for_targets),
    # so a node whose own target yields no gate still inherits the run's
    # verification instead of dispatching an unverifiable write.
    run_gate = discover_verification_gate(list(candidate_files or []), root)

    decomposed = None
    decomposition = "heuristic"
    decomposition_repair = None
    last_exc = None
    # DF-HG-3b: set only when a plan-only preview degraded to the heuristic
    # after an opted-in LLM decomposition failure -- the waist confirmation
    # step is then skipped rather than confirming (and reporting as
    # approved) a plan the operator never got the LLM decomposition for.
    _degraded_preview_heuristic = False
    if decompose_llm:
        if chat_fn is None:
            if not decompose_model:
                scout = resolve_scout_ladder(use_free=use_free,
                                             custom_frontier=frontier_model,
                                             allow_escalation=allow_escalation)
                decompose_model = scout[0]
            else:
                scout = [decompose_model]

            def _caller_gov(p, m):
                return governed_text(transport, api_key, governor, m,
                                     p, DECOMPOSE_MAX_TOKENS, label="decompose")

            chat_caller = _caller_gov
        else:
            scout = [decompose_model] if decompose_model else []
            def _caller_fn(p, m):
                return chat_fn(p)
            chat_caller = _caller_fn

        def _extract_caller_text(res):
            if isinstance(res, (tuple, list)):
                return res[0]
            if isinstance(res, dict):
                return res.get("content", "")
            return str(res)

        # DF-HG-3: one strict retry on LLM decomposition failure, then loud heuristic fallback in preview too
        last_exc = None
        raw_output = ""
        for attempt in (1, 2):
            active_model = scout[min(attempt - 1, len(scout) - 1)] if scout else decompose_model
            try:
                # chat_fn's contract is (text, cost) -- decomposition consumes
                # the text only; the cost stays on the governor/caller side.
                # HG-condense-decompose + JEV-P3-context-pack: signatures AND
                # decision pack; never raw file bodies; prompt still labels
                # REPOSITORY CONTEXT: via build_decomposition_prompt.
                sig_ctx = _decompose_repo_context(
                    plan_goal, candidate_files, root=root, ledger=ledger)
                decision_ctx = build_context_pack(
                    opts_goal, candidate_files=candidate_files)
                if sig_ctx and str(sig_ctx).strip():
                    repo_context = decision_ctx + "\n\n" + str(sig_ctx).strip()
                else:
                    repo_context = decision_ctx
                def _chat_capture(p, _model=active_model):
                    # #541: keep the exact body so a parse failure can be
                    # repaired from what the model already produced, and the
                    # raw output survives in the run record either way.
                    nonlocal raw_output
                    raw_output = _extract_caller_text(chat_caller(p, _model))
                    return raw_output

                decomposed = decompose_via_llm(_chat_capture, plan_goal,
                                               candidate_files=candidate_files,
                                               repo_context=repo_context)
                decomposition = (f"llm:{active_model}"
                                 if active_model else "llm:injected")
                last_exc = None
                break
            except HarnessError as exc:
                last_exc = exc
                if attempt == 1:
                    eprint(f"[plan] LLM decomposition attempt 1 failed ({exc}); retrying")
        if last_exc is not None and raw_output:
            # ONE bounded repair before the heuristic (#541): salvage the
            # structure already paid for, at strictly less cost than a second
            # full decomposition call.
            salvaged = _salvage_decomposition(raw_output)
            if salvaged is not None and salvaged.nodes:
                decomposed = salvaged
                decomposition = (f"llm-salvage:{active_model}"
                                 if active_model else "llm-salvage:injected")
                decomposition_repair = decomposition_repair_record(
                    last_exc, raw_output)
                decomposition_repair["outcome"] = "salvaged"
                eprint("[plan] decomposition parse failed; salvaged the "
                       "partial structure instead of a second full call")
                last_exc = None
        if last_exc is not None:
            # DF-HG-3b (Board ruling on PR #68): a plan-only preview stays
            # FAIL-CLOSED by default -- the operator asked for LLM planning,
            # and silently handing back the heuristic plan would misreport
            # what actually ran. --execute always falls back loudly (the
            # run spends anyway); a preview only degrades when the operator
            # opted in with allow_heuristic_preview.
            if not execute and not allow_heuristic_preview:
                refusal = HarnessError(
                    f"LLM decomposition failed twice ({last_exc}); refusing "
                    "to silently degrade a plan-only preview to the "
                    "heuristic decomposition. Pass --allow-heuristic-preview "
                    "to opt into a loud heuristic fallback, or rerun with "
                    "--execute.")
                if raw_output:
                    # #541: even a fail-closed stop carries the evidence.
                    repair = decomposition_repair_record(last_exc, raw_output)
                    refusal.raw_output = repair["raw_output"]
                    refusal.raw_output_sha256 = repair["raw_output_sha256"]
                    refusal.parse_error = repair["parse_error"]
                raise refusal from last_exc
            from . import events as _events
            _events.emit(
                "orchestration_note",
                note=f"LLM decomposition failed ({last_exc}); loud heuristic fallback")
            eprint(f"[plan] LLM decomposition failed ({last_exc}); loud heuristic fallback")
            decomposition = "heuristic"
            decomposed = None
            if not execute:
                _degraded_preview_heuristic = True

    plan_result = plan_task(
        goal=plan_goal, candidate_files=candidate_files,
        custom_frontier=frontier_model, use_free=use_free,
        decomposed_dag=decomposed, root=root, run_gate=run_gate,
        allow_escalation=allow_escalation, jev_route=jev_route_feed)
    plan_result["decomposition"] = decomposition
    if decomposition_repair is not None:
        plan_result["decomposition_repair"] = decomposition_repair
    if last_exc is not None:
        plan_result["degraded"] = True
        _unparseable = any(marker in str(last_exc) for marker in (
            "failed to parse JSON", "must be a JSON object",
            "no valid JSON object", "returned no nodes"))
        plan_result["degrade_reason"] = (
            "decomposition_unparseable" if _unparseable
            else "decomposition_unavailable")
        if raw_output:
            # The heuristic engaged loudly, with its evidence attached: the
            # parse error and a reference to the preserved raw output (#541).
            repair = decomposition_repair_record(last_exc, raw_output)
            repair["outcome"] = "heuristic"
            plan_result["decomposition_repair"] = repair
    if plan_triage is not None:
        plan_result["triage"] = plan_triage
    if plan_structural is not None:
        plan_result["structural"] = plan_structural
    if plan_issue_sort is not None:
        plan_result["issue_sort"] = plan_issue_sort
    # Chunk anything that cannot fit ONE model pass before the gate sees it,
    # so the waist confirms the plan that will actually run.
    plan_result = _fit_plan_to_single_pass(
        plan_result, goal=opts_goal, candidate_files=candidate_files,
        custom_frontier=frontier_model, use_free=use_free, root=root,
        run_gate=run_gate, max_tokens=max_tokens,
        allow_escalation=allow_escalation)
    if plan_structural is not None:
        plan_result["structural"] = plan_structural
    if plan_issue_sort is not None:
        plan_result["issue_sort"] = plan_issue_sort

    # #346: preflight unincurred consensus + waist + execute liability BEFORE
    # spending on consensus/confirm when waist/consensus are armed for execute.
    if execute and governor is not None and confirm and not _degraded_preview_heuristic:
        plan_result = _evaluate_composed_ceiling(
            plan_result, completed_stages=("decompose",))

    # HG-plan-consensus: optional cheap soundness check BEFORE the waist.
    # It always uses its OWN governed call (or an injected consensus seam),
    # never the decompose chat_fn -- those are different contracts.
    consensus = None
    if plan_result.get("status") != "refused" and plan_consensus and confirm:
        consensus_model = decompose_model
        if not consensus_model:
            try:
                consensus_model = resolve_scout_ladder(
                    use_free=use_free, custom_frontier=frontier_model)[0]
            except Exception:
                consensus_model = frontier_model
        try:
            # chat_fn=None -> plan_consensus builds the governed_text call.
            consensus = plan_consensus_check(
                transport=transport, api_key=api_key, governor=governor,
                ledger=ledger, plan_result=plan_result,
                model=consensus_model, chat_fn=None)
        except HarnessError as exc:
            # Fail closed on unparseable consensus when the operator armed it.
            if not execute:
                raise
            eprint(f"[plan] plan consensus failed ({exc}); continuing to waist")
            consensus = {"sound": True, "reasons": [f"consensus_unavailable: {exc}"],
                         "cost": 0.0, "model": consensus_model}
        if consensus is not None:
            plan_result["consensus"] = consensus

    if plan_result.get("status") == "refused":
        pass
    elif confirm and _degraded_preview_heuristic:
        # DF-HG-3b: the operator opted into a heuristic-degraded preview,
        # which never ran the LLM decomposition the waist would confirm.
        # Report the skip explicitly -- never "approved" for a plan that
        # was not actually reviewed against the requested decomposition.
        plan_result["confirmation"] = {
            "verdict": "skipped",
            "model": None,
            "rounds": 0,
            "reason": "plan-only preview degraded to heuristic decomposition "
                      "via --allow-heuristic-preview; waist confirmation "
                      "over an LLM decomposition never happened, so it is "
                      "skipped rather than confirming an unreviewed plan.",
            "cost": 0.0,
        }
    elif confirm:
        primary_ladder = resolve_waist_ladder(
            use_free=use_free, custom_frontier=frontier_model,
            allow_escalation=allow_escalation)
        # #539: a rung known to be unservable is not dispatched again; the
        # ledger's verdicts (this run and earlier ones) order the ladder.
        from .availability import (
            default_ledger,
            failover_models,
            order_models,
            record_error,
        )
        from .config import (
            laptop_local_pool,
            resolve_cerebras_key,
            resolve_fireworks_key,
            resolve_groq_key,
            resolve_meta_key,
        )

        _ledger = default_ledger()
        _fallback_pool = laptop_local_pool(
            groq_key=resolve_groq_key() or None,
            cerebras_key=resolve_cerebras_key() or None,
            fireworks_key=resolve_fireworks_key() or None,
            meta_key=resolve_meta_key() or None,
        )
        ladder = list(
            failover_models(
                primary_ladder, _fallback_pool, prefer_free=bool(use_free)
            )
            or order_models(primary_ladder, prefer_free=bool(use_free))
        )
        # #204: one circuit per run -- throttled models stay skipped and
        # the wait ceiling stops a storm with an honest rate-limited error.
        from .lifecycle_guards import (
            RATE_LIMITED,
            RateCircuit,
            classify_harness_error,
            is_availability_failure,
            is_terminal_failure,
        )
        _rate_circuit = RateCircuit()
        plan_result_confirmed = None
        last_exc = None
        _failover_extended = False
        for rung_idx, candidate_model in enumerate(ladder):
            if (
                _failover_extended
                and candidate_model in primary_ladder
                and "/" in str(candidate_model)
                and _ledger.is_excluded(candidate_model)
            ):
                continue
            if _rate_circuit.should_skip(candidate_model):
                from . import events as _events
                _events.emit("rotation", model=candidate_model,
                             reason="rate_limited_cooldown",
                             note=f"waist rung {rung_idx + 1}/{len(ladder)} skipped (rate-limit cooldown)")
                continue
            try:
                _rate_circuit.check_wait_budget()
                res = confirm_plan(
                    transport=transport, api_key=api_key, governor=governor,
                    ledger=ledger, plan_result=plan_result, model=candidate_model,
                    use_free=use_free, custom_frontier=frontier_model,
                    root=root, run_gate=run_gate, chat_fn=None,
                    consensus=consensus)
                plan_result_confirmed = res
                break
            except HarnessError as exc:
                last_exc = exc
                _kind = classify_harness_error(str(exc))
                if is_terminal_failure(_kind):
                    # Only this run's own budget cap stops the ladder (#538).
                    raise
                if is_availability_failure(_kind):
                    # Provider verdict: rotate to the next configured rung,
                    # and remember the pair for the next run.
                    record_error(candidate_model, exc, kind=_kind)
                    if not _failover_extended:
                        _extra = failover_models(
                            primary_ladder,
                            _fallback_pool,
                            prefer_free=bool(use_free),
                        )
                        if _extra:
                            _failover_extended = True
                            for _m in _extra:
                                if _m not in ladder:
                                    ladder.append(_m)
                if _kind == RATE_LIMITED:
                    _rate_circuit.note_rate_limited(candidate_model)
                from . import events as _events
                _events.emit("rotation", model=candidate_model, reason=str(exc),
                             note=f"waist confirmation failed on rung {rung_idx + 1}/{len(ladder)}")
                continue

        if plan_result_confirmed is not None:
            plan_result = plan_result_confirmed
            if plan_structural is not None:
                plan_result["structural"] = plan_structural
            if consensus is not None:
                plan_result["consensus"] = consensus
            if plan_issue_sort is not None:
                plan_result["issue_sort"] = plan_issue_sort
            # When in autonomous execution mode and the waist refused,
            # do not immediately halt. Attempt critique-driven re-planning if decomposition
            # was LLM-based, feeding the frontier's architectural critique back to the planner.
            if plan_result.get("status") == "refused" and execute and decompose_llm:
                refusal_reason = plan_result.get("confirmation", {}).get("reason", "")
                from . import events as _events
                from .lifecycle_guards import is_missing_tool_refusal as _is_missing_tool
                if _is_missing_tool(refusal_reason):
                    # #205: absent capability -- no re-plan could fix it.
                    _events.emit("orchestration_note",
                                 note=f"Waist refused plan ('{refusal_reason}'); "
                                      "missing capability, not re-planning")
                else:
                    _events.emit("orchestration_note",
                                 note=f"Waist refused plan ('{refusal_reason}'); re-planning with critique")
                    critique_prompt = (
                        f"{opts_goal}\n\n"
                        f"[ARCHITECTURAL REVIEW CRITIQUE]: The previous plan was rejected: "
                        f"'{refusal_reason}'. "
                        f"Address this critique directly: ensure all iteration loops, conditional branching, "
                        f"dependencies, and granular steps are properly structured into the DAG."
                    )
                    try:
                        critique_context = _decompose_repo_context(
                            critique_prompt, candidate_files, root=root,
                            ledger=ledger)
                        re_decomposed = decompose_via_llm(
                            lambda p: _extract_caller_text(chat_fn(p)), critique_prompt,
                            candidate_files=candidate_files,
                            repo_context=critique_context)
                        re_plan = plan_task(
                            goal=plan_goal, candidate_files=candidate_files,
                            custom_frontier=frontier_model, use_free=use_free,
                            decomposed_dag=re_decomposed, root=root, run_gate=run_gate,
                            allow_escalation=allow_escalation)
                        re_plan["decomposition"] = decomposition + ":critique_replan"
                        re_plan = _fit_plan_to_single_pass(
                            re_plan, goal=opts_goal, candidate_files=candidate_files,
                            custom_frontier=frontier_model, use_free=use_free, root=root,
                            run_gate=run_gate, max_tokens=max_tokens,
                            allow_escalation=allow_escalation)
                        # #204: the re-plan confirm is another plan attempt
                        # on the same run -- rate-limited rungs stay skipped.
                        for candidate_model in _rate_circuit.available(ladder):
                            try:
                                _rate_circuit.check_wait_budget()
                                re_res = confirm_plan(
                                    transport=transport, api_key=api_key, governor=governor,
                                    ledger=ledger, plan_result=re_plan, model=candidate_model,
                                    use_free=use_free, custom_frontier=frontier_model,
                                    root=root, run_gate=run_gate, chat_fn=None,
                                    consensus=consensus)
                                if re_res.get("status") != "refused":
                                    plan_result = re_res
                                    break
                            except HarnessError as _re_exc:
                                _re_kind = classify_harness_error(str(_re_exc))
                                if is_terminal_failure(_re_kind):
                                    raise
                                if is_availability_failure(_re_kind):
                                    record_error(candidate_model, _re_exc,
                                                 kind=_re_kind)
                                if _re_kind == RATE_LIMITED:
                                    _rate_circuit.note_rate_limited(candidate_model)
                                continue
                    except HarnessError as exc:
                        # #204: terminal spend stays terminal -- retaining the
                        # refusal would launder an exhausted key into a plan.
                        if is_terminal_failure(classify_harness_error(str(exc))):
                            raise
                        eprint(f"[plan] Critique re-planning failed ({exc}); retaining initial result")

            if plan_result.get("status") != "refused":
                # An amend/split verdict replaces the node set: re-fit it, or the
                # gate's own repair could hand execution an oversized node.
                plan_result = _fit_plan_to_single_pass(
                    plan_result, goal=opts_goal, candidate_files=candidate_files,
                    custom_frontier=frontier_model, use_free=use_free, root=root,
                    run_gate=run_gate, max_tokens=max_tokens,
                    allow_escalation=allow_escalation)
        else:
            # HG: Confirm-armed waist UNREACHABLE across the full ladder.
            # Operator ruling (2026-09-22): an unreachable seat is an
            # AVAILABILITY failure, not a policy refusal -- the only two
            # things allowed to stop a run are the monetary cap and required
            # user input. Degrade to executing under the local structural
            # gate (which plan_task already ran) with explicit provenance:
            # every downstream envelope records that NO model confirmed this
            # plan. Plan-only mode (execute=False) still raises: there is no
            # execution to protect there, and the caller asked a question
            # whose honest answer is "the gate could not run".
            first_model = ladder[0] if ladder else (
                frontier_model or resolve_frontier_model(None, use_free=use_free))
            message = (
                f"waist confirmation could not run on {first_model} "
                f"(plan NOT executed): {last_exc}")
            if not execute:
                raise HarnessError(message) from last_exc
            from . import events as _events
            _events.emit(
                "orchestration_note",
                note=(f"Waist confirmation unreachable across ladder ({last_exc}); "
                      "degrading to local-gate execution per operator "
                      "no-interruptions ruling"))
            eprint(f"[waist] Confirmation unreachable across ladder ({last_exc}); "
                   f"degrading to local-gate execution (verdict=unavailable)")
            degraded = dict(plan_result)
            degraded["status"] = "planned"
            degraded["degraded"] = True
            degraded["degrade_reason"] = "waist_unavailable"
            resume_hash = hashlib.sha256(
                f"{opts_goal}:{plan_result.get('total_nodes', 1)}".encode("utf-8")
            ).hexdigest()[:16]
            resume_token = f"waist-resume-{resume_hash}"
            degraded["resume_token"] = resume_token
            degraded["confirmation"] = {
                "verdict": "unavailable",
                "model": first_model,
                "rounds": 0,
                "reason": "waist confirmation unreachable across the full ladder; "
                          "executing under local structural gate only",
                "evidence": str(last_exc) if last_exc is not None else "",
                "cost": 0.0,
                "degraded": True,
                "degrade_reason": "waist_unavailable",
                "resume_token": resume_token,
            }
            plan_result = degraded

    # #346 / HG-composed-ceiling: all planning stages (decompose, consensus,
    # waist + retries/critique) have already completed and settled against the
    # governor, so compare ONLY not-yet-incurred DAG execution liability against
    # remaining funds unless already refused before waist spend.
    if plan_result.get("status") != "refused":
        plan_result = _evaluate_composed_ceiling(
            plan_result, completed_stages=("decompose", "consensus", "waist"))
    if token_budget is not None:
        # HV-4: the composition decision is evidence, so it rides on the
        # envelope rather than living only in the caller's head. Attached
        # last, so it survives the degraded/refused envelope copies above.
        composition = compose_stages(
            budget=token_budget, declared=stages,
            supplied_brief=supplied_brief, supplied_plan=supplied_plan,
            brief=brief, brief_tokens=brief_tokens, reader=reader)
        states = stage_states(composition)
        planning_stage = next(
            (entry for entry in composition["stages"]
             if entry["stage"] == STAGE_PLANNING), None)
        if planning_stage is not None and plan_result.get("status") != "refused":
            # HV-5: composition selects and budgets the planning stage; the
            # waist remains its sole production owner. Give it the composed
            # child allowance and the same intake artifact/reader the lane
            # used to make the composition decision.
            planning = run_planning(
                goal=opts_goal,
                budget=token_budget,
                stage_budget=planning_stage["budget"],
                files=candidate_files or (), reader=reader, brief=brief,
                jev_policy=jev_policy)
            planning_payload = planning.to_dict()
            plan_result["planning"] = planning_payload
            if isinstance(planning_payload, dict) and planning_payload.get("jev_signals"):
                if "stage_judgments" not in plan_result:
                    plan_result["stage_judgments"] = {}
                plan_result["stage_judgments"]["planning"] = planning_payload["jev_signals"]
            states[STAGE_PLANNING] = STATE_COMPLETED
            # Only sufficiency authorizes the already-composed outer DAG.
            # A proposed planning DAG has no adapter into that outer plan,
            # and an evidence request/defer explicitly says the available
            # evidence cannot support execution. Fail closed while preserving
            # the full typed result for the caller.
            kind = (planning_payload.get("kind")
                    if isinstance(planning_payload, dict) else None)
            if kind != OUTCOME_SUFFICIENT:
                if kind == OUTCOME_DEFER:
                    reason = (planning_payload.get("reason")
                              or "planning deferred execution")
                elif kind == OUTCOME_EVIDENCE_REQUEST:
                    reason = (planning_payload.get("reason")
                              or "planning requires additional evidence")
                elif kind == OUTCOME_PLAN:
                    reason = (
                        "planning produced a separate plan without an adapter "
                        "to the composed execution DAG")
                else:
                    reason = "planning returned an unsupported outcome"
                plan_result["status"] = "refused"
                plan_result["confirmation"] = {
                    "verdict": "refused",
                    "model": "planning-outcome",
                    "rounds": 0,
                    "reason": reason,
                    "cost": 0.0,
                }
        ctx_judge = kwargs.get("context_judgment") or context_judgment
        if ctx_judge:
            if "stage_judgments" not in plan_result:
                plan_result["stage_judgments"] = {}
            plan_result["stage_judgments"]["context"] = ctx_judge
        context_stage = next(
            (entry for entry in composition["stages"]
             if entry["stage"] == STAGE_CONTEXT), None)
        if context_stage is not None and plan_result.get("status") != "refused":
            if jev_policy is not None and hasattr(jev_policy, "evaluate_hourglass_stage"):
                if "stage_judgments" not in plan_result:
                    plan_result["stage_judgments"] = {}
                if "context" not in plan_result["stage_judgments"]:
                    state = {
                        "request": opts_goal,
                        "goal": opts_goal,
                        "files": list(candidate_files or []),
                    }
                    if brief is not None:
                        state["brief_tokens"] = brief_tokens or brief.get("estimated_tokens")
                    try:
                        eval_res = jev_policy.evaluate_hourglass_stage(
                            "context_intake", state, site="hourglass-intake")
                        if isinstance(eval_res, tuple) and len(eval_res) >= 2:
                            _res, structural = eval_res[0], eval_res[1]
                        else:
                            _res, structural = None, getattr(eval_res, "structural", {}) or {}
                        from .jev_packs import HOURGLASS_STAGE_DIMENSIONS
                        declared = HOURGLASS_STAGE_DIMENSIONS["context_intake"]["signals"]
                        signals = {name: (structural or {}).get(name) for name in declared
                                   if (structural or {}).get(name) is not None}
                        plan_result["stage_judgments"]["context"] = {
                            "dimension": "context_intake",
                            "signals": signals,
                            "native": bool((structural or {}).get("native")),
                        }
                    except (HarnessError, TypeError, ValueError):
                        plan_result["stage_judgments"]["context"] = {
                            "dimension": "context_intake", "signals": {}, "native": False
                        }
        if brief is not None and STAGE_CONTEXT in (composition.get("bypassed")
                                                  or {}):
            # HV-2-use: the brief IS the context stage's artifact, and the
            # caller produced it, so a granted bypass means that stage is
            # **done** rather than *skipped*. Only a granted bypass: when the
            # pack is stale the bypass is denied, the stage genuinely has to
            # run, and its own `pending` is the honest report.
            states[STAGE_CONTEXT] = STATE_COMPLETED
        plan_result["composition"] = composition_envelope(composition,
                                                          states=states)
        plan_result["stage_states"] = states
        plan_result["token_budget"] = token_budget.snapshot()
    if brief is not None:
        plan_result["brief"] = brief
    return plan_result


def _fit_plan_to_single_pass(plan_result: Dict[str, Any], *, goal,
                             candidate_files, custom_frontier, use_free,
                             root, run_gate, max_tokens,
                             allow_escalation: bool = False) -> Dict[str, Any]:
    """Apply the chunk policy to a plan result, re-planning when it split.

    The chunk policy itself lives in :func:`chunk_oversized_nodes` (ONE
    owner); this wrapper only re-derives the tier/ceiling details through
    ``plan_task`` when the DAG changed, so node details keep exactly one
    producer. Returns the plan unchanged when nothing was oversized.
    """
    if plan_result.get("status") == "refused":
        return plan_result
    dag = TaskDAG.from_dict(plan_result["dag"])
    fitted = chunk_oversized_nodes(dag, root=root, max_tokens=max_tokens,
                                   source_tokens=rung_read_budgets(plan_result))
    if fitted is dag:
        return plan_result
    rebuilt = plan_task(goal=goal, candidate_files=candidate_files,
                        custom_frontier=custom_frontier, use_free=use_free,
                        decomposed_dag=fitted, root=root, run_gate=run_gate,
                        allow_escalation=allow_escalation)
    rebuilt["decomposition"] = plan_result.get("decomposition", "heuristic")
    if len(fitted.nodes) != len(dag.nodes):
        # Visible evidence that the planner chunked: a reader can see how
        # many nodes the goal originally needed versus how many passes it
        # was split into, instead of wondering why the node count grew.
        rebuilt["chunking"] = {
            "required": True,
            "unchunked_nodes": plan_result.get("total_nodes", 0)}
    return rebuilt


def resolve_scout_ladder(use_free=True, custom_frontier=None, allow_escalation=False):
    """The tier-0 ladder from the same sliding-scale policy that classifies
    nodes -- the decomposition model is simply the cheapest rung, with no
    new routing policy of its own."""
    route = resolve_sliding_scale_route(
        instruction="decompose the goal into subtasks",
        target_files=(), dependency_depth=0, is_leaf=True,
        use_free=use_free, custom_frontier=custom_frontier,
        allow_escalation=allow_escalation)
    return list(route.ladder)


def resolve_waist_ladder(use_free=True, custom_frontier=None, allow_escalation=False):
    """The model ladder for waist plan confirmation (cheapest / free first).

    - If custom_frontier is specified, it is placed at the head of the ladder.
    - If use_free is True:
        - Primary free judge (FREE_JUDGE, e.g. google/gemma-4-31b-it:free)
        - Free alternatives from ESCALATION_POOL_FREE
        - If allow_escalation is True:
            - Paid frontier model: resolve_frontier_model(custom_frontier, use_free=False)
            - Paid escalation models from ESCALATION_POOL_PAID
    - If use_free is False:
        - Paid frontier model, then ESCALATION_POOL_PAID.
    """
    out = []
    if custom_frontier:
        resolved = resolve_frontier_model(custom_frontier, use_free=use_free)
        if resolved and resolved not in out:
            out.append(resolved)
    if use_free:
        for m in [FREE_JUDGE] + list(ESCALATION_POOL_FREE):
            if m not in out:
                out.append(m)
        if allow_escalation:
            frontier_paid = resolve_frontier_model(custom_frontier, use_free=False)
            if frontier_paid not in out:
                out.append(frontier_paid)
            for m in ESCALATION_POOL_PAID:
                if m not in out:
                    out.append(m)
    else:
        frontier_paid = resolve_frontier_model(custom_frontier, use_free=False)
        if frontier_paid not in out:
            out.append(frontier_paid)
        for m in ESCALATION_POOL_PAID:
            if m not in out:
                out.append(m)
    return out


def resolve_planner_ladder(use_free=True, custom_frontier=None, allow_paid=False):
    """The model ladder for task decomposition and complex planning."""
    return resolve_waist_ladder(use_free=use_free, custom_frontier=custom_frontier, allow_escalation=allow_paid)


# ---- HV-4: stage composition and the planning waist contract -------------
#
# Composition is a *selection* concern, not a reimplementation: the brief
# schema stays with ``brief``, the token arithmetic with ``token_budget``,
# plan validation with ``dag``, and Jev's dimensions with ``jev_policy``.
# This section only decides WHICH stages run, what each one may spend, and
# what the planning waist is allowed to emit.
#
# This module is the ONE owner of composition. The canon's ``HV-4`` row
# names ``harness/waist.py`` as the composition owner, so the alternative
# single-purpose ``harness/stages.py`` was dissolved into this section
# rather than left beside it: two owners of ``resolve_stages`` would be
# exactly the second implementation the row forbids.

# Hourglass compatibility: with nothing declared, every stage runs, exactly
# as the lanes behaved before composition was selectable.

# A supplied artifact means its stage already happened upstream. Composition
# records the bypass instead of silently re-running or silently dropping it.

# A supplied brief that no longer matches its pins buys no bypass. Planning on
# evidence that drifted from what it cited is exactly what the brief's
# freshness contract exists to prevent, so the context stage runs, rebuilds,
# and the caller can see that its supply was refused.

# Per-stage states a composition may report. A stage that is selected and
# silently absent is the one thing a composition must never be, so every
# declared stage is always visible in exactly one of these states.

# Successive stages plan over less than the one before: the brief is curated
# down as it is consumed, so a later stage's ceiling is the earlier stage's
# smaller share. This is a *narrowing* factor applied on top of the run
# budget, never a budget of its own.

# The planning ladder narrows by this share per round. Below 1.0 by
# construction: the ladder narrows, it never widens.

# A round below this many input tokens cannot ask a model anything useful, so
# the ladder stops before it spends a reservation on a truncated request.

# The planning waist may stop, plan, ask, or defer -- and nothing else.


#: A plan is accepted only if it validates AND stays inside this bound. The
#: number is declared here, not negotiated in a prompt.
DEFAULT_MAX_PLAN_NODES = 12

#: Code-owned stopping rule, not a model judgment. Jev answers "is more
#: evidence required?"; code decides what counts as yes. A request is taken
#: at or above this confidence and ignored below it, so a borderline call
#: ends the ladder instead of buying another round of curation.
SUFFICIENCY_NOUL_THRESHOLD = 0.5

#: How narrow the window search may get, in characters. A brief's size is
#: monotone in its window budget, so a bounded bisection finds the largest
#: window that fits; the cap keeps the rebuild count finite and cheap (every
#: step is a hermetic re-read, never a model call).








# ---- GAP-recondense: when a stage-mutated tree invalidates the brief -----
#
# A supplied brief buys the ``context`` bypass only while it is still
# evidence. ``brief.freshness_report`` answers one half of that -- has a
# cited file changed? -- and a *composed* run has two more, neither of which
# a pin check can see: a stage gate that failed, which voids the green-tree
# basis the plan was written against, and an executed node that wrote a path
# the brief describes, which makes the brief's account of that path stale
# even while every file it pinned is byte-identical. The trigger vocabulary
# is declared here so a caller reads a fixed set of reasons instead of
# inventing one, and precedence is code's rather than a model's: a terminal
# fact outranks a drifted pin, and a drifted pin outranks a heuristic overlap.

























# ------------------------------------------------------------- planning




def _curated_brief(goal, files, *, reader, allowance_tokens):
    """The largest brief whose MEASURED token estimate fits the allowance.

    :func:`harness.brief.build_brief` estimates over the bytes it actually
    ships, so the fit is checked against the real number rather than a
    characters-per-token guess. A brief's size is monotone in its window
    budget, so the window is bisected down to the largest value that fits --
    which is the only way to get this right, because the estimate is
    dominated by the pack's own metadata (sources, coverage, rules) rather
    than by the window: a step sized from the token excess leaves the pack
    byte-identical until the window drops below the content, so a larger
    allowance can fail where a smaller one succeeded.

    ``None`` means no honest brief exists at any window -- the round defers
    rather than shipping a brief it cannot pay for.
    """
    def build(window):
        pack = build_brief(goal, files, reader=reader, max_total_chars=window)
        return pack, estimate_brief_tokens(pack)

    smallest, smallest_tokens = build(0)
    if smallest_tokens > allowance_tokens:
        return None, 0
    low, high = 0, MAX_TOTAL_WINDOW_CHARS
    best = smallest
    while high - low > _WINDOW_SEARCH_FLOOR:
        mid = (low + high) // 2
        pack, tokens = build(mid)
        if tokens <= allowance_tokens:
            low, best = mid, pack
        else:
            high = mid
    return best, low


def _unrepresented(pack) -> List[str]:
    """The brief's own admission of what it could not represent."""
    return list(pack.get("omitted") or [])


def _conflicts(pack) -> List[Dict[str, Any]]:
    return [c for c in (pack.get("conflicts") or []) if isinstance(c, dict)]


def _evidence_request(pack, *, max_items=MAX_EVIDENCE_QUESTIONS):
    """A BOUNDED request for the evidence the brief says it is missing."""
    items: List[Dict[str, Any]] = [
        {"source": path, "reason": "not represented in the brief"}
        for path in _unrepresented(pack)]
    for conflict in _conflicts(pack):
        items.append({
            "source": ", ".join(str(s) for s in conflict.get("source_ids") or []),
            "reason": str(conflict.get("description") or "declared conflict"),
        })
        if len(items) >= max_items:
            break
    return items[:max_items]


def _jev_sufficiency(jev_policy, goal, pack, *, site):
    """Ask the one declared dimension that owns 'is this enough to plan on?'.

    Returns ``(signals, native)``. A policy that fails, falls back, or
    answers out of vocabulary yields ``native=False`` with whatever signals it
    produced, and the caller reads that as "not sufficient". Composition never
    re-implements the judgment and never promotes a fallback to native.

    The signal names come from the pack that declared them, not from a local
    list, so a new dimension's vocabulary cannot drift from this reader.
    """
    from .jev_packs import HOURGLASS_STAGE_DIMENSIONS
    state = {
        "goal": goal,
        "represented_sources": len(
            ((pack.get("grounding") or {}).get("sources") or [])),
        "omitted": _unrepresented(pack),
        "conflicts": [c.get("description") for c in _conflicts(pack)],
        "brief_render": render_brief(pack),
    }
    _result, structural = jev_policy.evaluate_hourglass_stage(
        "plan_soundness", state, site=site)
    structural = structural or {}
    declared = HOURGLASS_STAGE_DIMENSIONS["plan_soundness"]["signals"]
    signals = {name: structural.get(name) for name in declared
               if structural.get(name) is not None}
    return signals, bool(structural.get("native"))


def _validated_plan(plan_data, *, max_nodes=DEFAULT_MAX_PLAN_NODES):
    """A plan is accepted only if it validates AND stays inside its bound."""
    dag = plan_data if isinstance(plan_data, TaskDAG) else TaskDAG.from_dict(
        plan_data)
    count = len(dag.nodes)
    if count == 0:
        raise HarnessError("a plan must declare at least one node")
    if count > max_nodes:
        raise HarnessError(
            "plan declares {0} node(s), over the bound of {1}"
            .format(count, max_nodes))
    return dag


@dataclass(frozen=True)
class PlanningOutcome:
    """One planning run's result: exactly one of :data:`PLAN_OUTCOMES`.

    The run evidence (per-round allowances, what each round measured, the
    Jev signals, the budget snapshot) rides along with the terminal verdict
    so a reader can see *how* the waist decided, not only what it decided.
    The verdict itself is always produced through :func:`plan_outcome`, so
    the bounds on questions, defer reasons and DAG shape are live here too.
    """

    kind: str
    reason: Optional[str] = None
    brief: Optional[Dict[str, Any]] = None
    plan: Any = None
    evidence_request: Sequence[Dict[str, Any]] = ()
    rounds: Sequence[Dict[str, Any]] = ()
    jev_signals: Dict[str, Any] = field(default_factory=dict)
    budget: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.kind not in PLAN_OUTCOMES:
            raise HarnessError(
                "planning outcome must be one of {0}; got {1!r}"
                .format(list(PLAN_OUTCOMES), self.kind))
        object.__setattr__(self, "evidence_request",
                           tuple(self.evidence_request or ()))
        object.__setattr__(self, "rounds", tuple(self.rounds or ()))
        if self.kind == OUTCOME_EVIDENCE_REQUEST and not self.evidence_request:
            raise HarnessError(
                "an evidence request must actually ask something; use a defer "
                "with a reason when there is nothing to ask about")
        if self.kind == OUTCOME_DEFER and not str(self.reason or "").strip():
            raise HarnessError(
                "a defer must state why it deferred; an unexplained defer is a "
                "silent failure")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "reason": self.reason,
            "brief_tokens": (self.brief or {}).get("estimated_tokens"),
            "plan": (self.plan.to_dict() if isinstance(self.plan, TaskDAG)
                     else self.plan),
            "evidence_request": [dict(item) for item in self.evidence_request],
            "rounds": [dict(item) for item in self.rounds],
            "jev_signals": dict(self.jev_signals),
            "budget": dict(self.budget),
        }


def run_planning(*, goal, budget, stage_budget=None, files=(), reader=None, brief=None,
                 jev_policy=None, planner=None, rounds=2,
                 max_nodes=DEFAULT_MAX_PLAN_NODES,
                 max_evidence_items=MAX_EVIDENCE_QUESTIONS,
                 site="hourglass-planning"):
    """Run the planning stage: curate, judge sufficiency, and stop honestly.

    One round is one allowance, and the round's allowance is what its brief
    must fit inside. The ladder either finds the evidence sufficient (and
    stops there, spending nothing further), asks for a bounded piece of
    evidence, or -- when a ``planner`` is supplied -- emits a validated
    bounded plan. When it is exhausted the outcome is an honest ``defer``
    naming what was still missing, never a plan built on evidence the stage
    admitted it could not represent.
    """
    if jev_policy is not None and not hasattr(jev_policy,
                                               "evaluate_hourglass_stage"):
        raise HarnessError(
            "jev_policy must be a JevPolicy-like owner exposing "
            "evaluate_hourglass_stage")
    if planner is not None and not callable(planner):
        raise HarnessError("planner must be callable")
    if not isinstance(budget, TokenBudget):
        raise HarnessError("planning needs a TokenBudget to spend from")
    if stage_budget is not None and not isinstance(stage_budget, TokenBudget):
        raise HarnessError("planning stage_budget must be a TokenBudget")
    if stage_budget is not None and (
            stage_budget.label != STAGE_PLANNING
            or stage_budget._parent is not budget):
        raise HarnessError(
            "planning stage_budget must be the planning child of budget")

    stage = stage_budget or budget.stage(STAGE_PLANNING)
    ladder = planning_ladder(stage, rounds=rounds)
    round_log: List[Dict[str, Any]] = []
    jev_signals: Dict[str, Any] = {}
    pack = brief

    for index, round_budget in enumerate(ladder, start=1):
        allowance = round_budget.max_input_tokens
        if index > 1 and not files:
            # Nothing left to curate. A second round would judge the IDENTICAL
            # brief again, and a judgment that cannot change its answer must
            # not be paid for -- so the ladder stops here and says why.
            round_log.append({"round": index, "outcome": STATE_SKIPPED,
                              "reason": "nothing_left_to_curate",
                              "max_input_tokens": allowance})
            break
        if pack is None or index > 1:
            # Round one reads a supplied brief as data; every round after the
            # first curates its own, because a narrower allowance has to buy a
            # narrower brief. Curating reads the sources, so a caller that
            # supplies both a brief and unreadable files gets the reader's own
            # error rather than a silently different evidence set.
            pack, _ = _curated_brief(goal, files, reader=reader,
                                     allowance_tokens=allowance)
        if pack is None:
            round_log.append({"round": index, "outcome": STATE_SKIPPED,
                              "reason": "brief_exceeds_allowance",
                              "max_input_tokens": allowance})
            # A round with no honest brief is not a stopping point by itself:
            # a narrower round may still fit. The ladder decides.
            continue

        issues = validate_brief(pack, reader=reader)
        missing = _unrepresented(pack)
        conflicts = _conflicts(pack)
        sources = len(((pack.get("grounding") or {}).get("sources") or []))
        lint_clean = not issues
        # A brief citing no source is not evidence of anything: without this
        # bound an empty pack reads as a clean, gapless, conflictless brief and
        # planning would stop on it.
        sufficient = lint_clean and sources > 0 and not missing and not conflicts
        native = False
        # The semantic question is only asked when the artifact's own facts
        # are inconclusive, a failed lint always wins over a Jev "yes", and a
        # brief citing nothing is not asked about at all -- that question has
        # no answer worth a reservation.
        if lint_clean and sources > 0 and jev_policy is not None \
                and not sufficient:
            try:
                jev_signals, native = _jev_sufficiency(jev_policy, goal, pack,
                                                      site=site)
            except HarnessError:
                jev_signals, native = {}, False
            if native and sources > 0:
                requested = jev_signals.get("plan_evidence_requested")
                # The semantic answer is Jev's; what counts as "yes, ask for
                # more" is code's. A missing signal is not a quiet yes.
                if isinstance(requested, (int, float)) \
                        and not isinstance(requested, bool) \
                        and requested < SUFFICIENCY_NOUL_THRESHOLD:
                    sufficient = True
        round_log.append({
            "round": index,
            "outcome": (OUTCOME_SUFFICIENT if sufficient
                        else OUTCOME_EVIDENCE_REQUEST),
            "max_input_tokens": allowance,
            "brief_tokens": pack.get("estimated_tokens"),
            "sources": sources,
            "omitted": len(missing),
            "conflicts": len(conflicts),
            "grounding_issues": len(issues),
            "jev_native": native,
        })
        if sufficient:
            # Route through the one terminal contract, so the verdict a run
            # reports is the same checked verdict a caller would get.
            plan_outcome(OUTCOME_SUFFICIENT)
            return PlanningOutcome(
                OUTCOME_SUFFICIENT, reason="brief_covers_the_request",
                brief=pack, rounds=round_log, jev_signals=jev_signals,
                budget=stage.snapshot())

    if planner is not None and pack is not None:
        try:
            dag = _validated_plan(planner(goal, pack), max_nodes=max_nodes)
        except HarnessError as exc:
            return PlanningOutcome(
                OUTCOME_DEFER, reason="plan_rejected: {0}".format(exc),
                brief=pack, rounds=round_log, jev_signals=jev_signals,
                budget=stage.snapshot())
        plan_outcome(OUTCOME_PLAN, plan=dag.to_dict())
        return PlanningOutcome(
            OUTCOME_PLAN, reason="validated_bounded_plan", brief=pack,
            plan=dag, rounds=round_log, jev_signals=jev_signals,
            budget=stage.snapshot())

    request = _evidence_request(pack, max_items=max_evidence_items) \
        if pack is not None else []
    if request:
        # The bound is the waist's, so an over-long question is refused here
        # rather than trimmed into something the caller never asked.
        plan_outcome(OUTCOME_EVIDENCE_REQUEST,
                     questions=["{0}: {1}".format(item.get("source"),
                                                 item.get("reason"))
                                for item in request])
        reason = "bounded_evidence_request"
    elif pack is None:
        reason = "no_brief_fit_any_round"
    elif not ((pack.get("grounding") or {}).get("sources") or []):
        reason = "no_evidence_cited"
    else:
        reason = "nothing_left_to_request"
    if not request:
        plan_outcome(OUTCOME_DEFER, reason=reason)
    return PlanningOutcome(
        OUTCOME_EVIDENCE_REQUEST if request else OUTCOME_DEFER,
        reason=reason, brief=pack, evidence_request=request, rounds=round_log,
        jev_signals=jev_signals, budget=stage.snapshot())
