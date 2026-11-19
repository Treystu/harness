"""Consensus and confirmation owner (M2): consensus prompt/parse, tiering, the confirmation gate.

Owner split per #308: this module owns the one-round-trip confirmation and
consensus concern -- the prompt, the verdict vocabulary, the window reader,
tier classification (plan_task) and confirm_plan's fail-closed gate. Spend
still flows through the caller's governor; this module never reserves."""
import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Sequence

from .chat import governed_text
from .condenser import distill_context
from .dag import DAGNode, TaskDAG
from .errors import HarnessError
from .repo_scope import gate_for_targets
from .sliding_scale import resolve_sliding_scale_route
from .validation import MAX_INSTRUCTION_CHARS

from .plan_decompose import _parse_json_object, heuristic_decompose_goal

from .plan_contracts import (
    MAX_BRIEF_FILES,MAX_WAIST_ROUNDS, MAX_WINDOWS_PER_ROUND, MAX_WINDOW_LINES, WAIST_MAX_TOKENS)




def build_consensus_prompt(plan_result: Dict[str, Any]) -> str:
    """Cheap plan-soundness prompt (HG-plan-consensus)."""
    nodes = [
        {k: n[k] for k in ("node_id", "instruction", "target_files",
                           "create_files",
                           "dependencies", "local_gate", "complexity_tier")
         if k in n}
        for n in plan_result.get("nodes", [])
        if isinstance(n, dict)
    ]
    return "\n".join([
        "You are a cheap soundness checker for an autonomous coding plan.",
        "Decide whether this DAG can actually achieve the goal. You do NOT",
        "confirm routing quality (the waist does that); you only catch",
        "structurally unsound plans before confirmation spend grows.",
        "",
        "GOAL:",
        (plan_result.get("goal") or "").strip(),
        "",
        "PLANNED DAG (JSON):",
        json.dumps({"nodes": nodes}, indent=2),
        "",
        "Respond with ONLY one JSON object:",
        '  {"sound": true, "reasons": []}',
        '  {"sound": false, "reasons": ["..."]}',
        "sound=false when the DAG cannot achieve the goal, has cycles,",
        "omits critical write steps, or targets files unrelated to the work.",
    ])

def parse_plan_consensus(response_text: str) -> Dict[str, Any]:
    """Parse the plan-consensus verdict (strict; fail-closed)."""
    data = _parse_json_object(response_text, "plan consensus")
    if "sound" not in data:
        raise HarnessError("plan consensus verdict requires 'sound'")
    reasons = data.get("reasons") or []
    if not isinstance(reasons, list):
        reasons = [reasons]
    return {"sound": bool(data["sound"]), "reasons": [str(r) for r in reasons]}

def plan_consensus(*, transport, api_key, governor, ledger, plan_result,
                   model, chat_fn=None) -> Dict[str, Any]:
    """Optional cheap soundness check that runs BEFORE the waist.

    Returns ``{sound, reasons, cost, model}``. Ledger event:
    ``plan_consensus``. Cost is accounted on the governor (when the default
    governed chat_fn runs) and reported in the envelope.
    """
    if not model:
        raise HarnessError("plan consensus requires a model")
    if chat_fn is None:
        def chat_fn(prompt):
            return governed_text(transport, api_key, governor, model, prompt,
                                 256, label="plan_consensus")
    task_id = plan_task_id(plan_result)
    if ledger is not None:
        ledger.ensure_offered_task_id(
            task_id, model=model, required=False, source="plan_consensus")
    spent_before = governor.spent if governor is not None else 0.0
    raw = chat_fn(build_consensus_prompt(plan_result))
    if isinstance(raw, tuple):
        text = raw[0]
    else:
        text = raw
    verdict = parse_plan_consensus(text)
    cost = _verdict_cost(governor, spent_before)
    verdict["cost"] = cost
    verdict["model"] = model
    if ledger is not None:
        ledger.append(
            "plan_consensus", task_id=task_id,
            sound=verdict["sound"], reasons=verdict["reasons"],
            model=model, cost=cost)
    return verdict

def plan_task(
    goal: str,
    candidate_files: Optional[Sequence[str]] = None,
    repo_context: Optional[str] = None,
    custom_frontier: Optional[str] = None,
    use_free: bool = True,
    decomposed_dag: Optional[TaskDAG] = None,
    root: Optional[str] = None,
    run_gate: Optional[str] = None,
    allow_escalation: bool = False,
    jev_route: Optional[str] = None,
) -> Dict[str, Any]:
    # Formulate a TaskDAG and classify sliding-scale tiers for each node.
    # decomposed_dag: a pre-built DAG (LLM-authored via decompose_via_llm or
    # waist-amended) replacing the heuristic decomposition; tier
    # classification and ceiling math are identical for either origin.
    # root/run_gate feed the ONE gate rule (repo_scope.gate_for_targets):
    # every node leaves this function with a verification gate derived from
    # its OWN declared target, so cli, mcp and the agent lane all dispatch
    # gated nodes instead of each lane re-deriving the rule (or omitting
    # it: an ungated write is refused at unknown trust, so the MCP lane's
    # plan_and_execute could not land anything at all).
    # jev_route: optional JEV-P3 typed route (vocabulary only) used as a
    # tier floor when keyed; unkeyed callers leave it None.
    dag = (decomposed_dag if decomposed_dag is not None
           else heuristic_decompose_goal(goal, candidate_files,
                                         root_dir=root))
    node_details: List[Dict[str, Any]] = []
    total_ceiling = 0.0

    classified_nodes: Dict[str, DAGNode] = {}
    batches = dag.topological_batches()
    depth_map: Dict[str, int] = {}
    for depth, batch in enumerate(batches):
        for n in batch:
            depth_map[n.node_id] = depth

    for node_id, node in dag.nodes.items():
        is_leaf = len(node.dependencies) == 0
        depth = depth_map.get(node_id, 0)
        gate = gate_for_targets(node.target_files, root,
                               declared=node.local_gate, run_gate=run_gate)
        route = resolve_sliding_scale_route(
            instruction=node.instruction,
            target_files=node.target_files,
            dependency_depth=depth,
            is_leaf=is_leaf,
            use_free=use_free,
            custom_frontier=custom_frontier,
            allow_escalation=allow_escalation,
            jev_route=jev_route,
        )
        total_ceiling += route.cost_ceiling
        classified_nodes[node_id] = DAGNode(
            node_id=node.node_id,
            instruction=node.instruction,
            target_files=node.target_files,
            create_files=node.create_files,
            dependencies=node.dependencies,
            local_gate=gate,
            complexity_tier=route.classification.tier,
            backend=node.backend,
        )
        node_details.append({
            "node_id": node.node_id,
            "instruction": node.instruction,
            "target_files": list(node.target_files),
            "create_files": list(node.create_files),
            "dependencies": list(node.dependencies),
            "local_gate": gate,
            "complexity_tier": route.classification.tier,
            "recommended_model": route.classification.recommended_model,
            "cost_ceiling": route.cost_ceiling,
            "backend": node.backend,
            "classification": {
                "tier": route.classification.tier,
                "score": route.classification.score,
                "reasons": list(route.classification.reasons),
                "estimated_cost_tier": route.classification.estimated_cost_tier,
            },
            "route": {
                "ladder": list(route.ladder),
                "cost_ceiling": route.cost_ceiling,
            },
        })

    enriched_dag = TaskDAG(nodes=classified_nodes)
    return {
        "status": "planned",
        "goal": goal.strip(),
        "total_nodes": len(enriched_dag.nodes),
        "batches": [[n.node_id for n in b] for b in enriched_dag.topological_batches()],
        "nodes": node_details,
        "total_cost_ceiling": round(total_ceiling, 4),
        "dag": enriched_dag.to_dict(),
    }

def build_waist_prompt(
    plan_result: Dict[str, Any],
    brief_context: str = "",
    window_context: str = "",
    consensus: Optional[Dict[str, Any]] = None,
) -> str:
    """Build the frontier waist-confirmation prompt (M2).

    The brief (file signatures + bounded windows + failure evidence) is the
    confirming model's ONLY repo access: bounded file-window round-trips
    replace open-ended reading. The verdict contract is strict JSON, one of::

        {"verdict": "approve"}
        {"verdict": "amend", "nodes": [ ...same node schema as decomposition... ]}
        {"verdict": "refuse", "reason": "...", "evidence": "cited brief section"}
        {"verdict": "request_windows",
         "file_window_requests": [{"path": "p/x.py", "start_line": 1, "end_line": 80}]}

    ``amend`` replaces the whole node set (subdividing a node is just an
    amend), and the replacement re-validates through the same schema as the
    original plan. A refusal must cite the brief section that fails --
    honest evidence, not vibes.
    """
    nodes = [
        {k: n[k] for k in ("node_id", "instruction", "target_files",
                           "create_files",
                           "dependencies", "local_gate", "complexity_tier")
         if k in n}
        for n in plan_result.get("nodes", [])
    ]
    lines = [
        "You are the plan-confirmation gate for an autonomous coding harness.",
        "A cheaper model decomposed the goal below into an executable DAG.",
        "Confirm the plan BEFORE execution spend: check decomposition quality,",
        "tier assignments (0=scout/simple, 1=standard, 2=deep/frontier),",
        "dependency ordering, and target-file scoping.",
        "",
        "GOAL:",
        plan_result.get("goal", "").strip(),
        "",
        "PLANNED DAG (JSON):",
        json.dumps({"nodes": nodes}, indent=2),
        "",
    ]
    if brief_context:
        lines.extend(["REPOSITORY BRIEF (signatures; your only repo access):",
                      brief_context.strip(), ""])
    if window_context:
        lines.extend(["REQUESTED FILE WINDOWS (attached this round):",
                      window_context.strip(), ""])
    if consensus is not None and not consensus.get("sound", True):
        lines.extend([
            "PLAN CONSENSUS (cheap pre-check marked this plan UNSOUND):",
            json.dumps({"sound": False,
                        "reasons": list(consensus.get("reasons") or [])}, indent=2),
            "You MUST return 'amend' with a corrected replacement DAG. Do not",
            "approve an unsound plan.",
            "",
        ])
    lines.extend([
        "VERDICT CONTRACT -- respond with ONLY one JSON object:",
        '  {"verdict": "approve"}                                   plan is sound as routed',
        '  {"verdict": "amend", "nodes": [...]}                     full replacement node set,',
        '                                                           same schema, re-validated;',
        '                                                           subdividing a node is an amend',
        '  {"verdict": "refuse", "reason": "...", "evidence": "..."}  cite the brief section',
        '                                                           that fails; evidence required',
        '  {"verdict": "request_windows", "file_window_requests": [...]}  need bounded source',
        '                                                           windows before deciding',
        '                                                            ({"path", "start_line",',
        '                                                              "end_line"}; 1-based,',
        '                                                              end inclusive)',
        "Rules: the DAG must stay acyclic; node instructions must be precise and",
        "scoped (they are executed verbatim by cheaper models); do not request",
        "more windows than you need -- round-trips are budgeted.",
        "AMENDMENT vs REFUSAL POLICY:",
        "- DO NOT REFUSE simply because the planned DAG is incomplete, lacks iteration loops,",
        "  has missing steps, or needs different granularity/ordering. If the planned DAG is",
        "  suboptimal, REPAIR IT: return 'amend' with the complete, corrected replacement DAG nodes.",
        "- 'refuse' is STRICTLY reserved for requests that are genuinely impossible, out of scope,",
        "  destructive, or malicious. Refusing an executable coding task is a failure.",
    ])
    return "\n".join(lines)

def _waist_window_request(raw) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise HarnessError("waist file_window_requests entries must be objects")
    path = str(raw.get("path") or "").strip()
    if not path:
        raise HarnessError("waist file_window_request missing 'path'")
    request: Dict[str, Any] = {"path": path}
    for key in ("start_line", "end_line"):
        value = raw.get(key)
        if value is None:
            continue
        try:
            line = int(value)
        except (TypeError, ValueError):
            raise HarnessError(
                f"waist file_window_request {key} must be an integer") from None
        if line < 1:
            raise HarnessError(f"waist file_window_request {key} must be >= 1")
        request[key] = line
    if ("start_line" in request or "end_line" in request) and \
            request.get("start_line", 1) > request.get("end_line", 1 << 30):
        raise HarnessError("waist file_window_request start_line exceeds end_line")
    return request

_VERDICT_ALIASES = {
    "approve": "approve", "approved": "approve", "approval": "approve",
    "accept": "approve", "accepted": "approve", "ok": "approve",
    "refuse": "refuse", "refused": "refuse", "reject": "refuse",
    "rejected": "refuse", "deny": "refuse", "denied": "refuse",
    "amend": "amend", "amended": "amend", "amendment": "amend",
    "revise": "amend", "revised": "amend",
    "split": "split", "subdivide": "split", "subdivided": "split",
    "request_windows": "request_windows", "request-windows": "request_windows",
    "requestwindows": "request_windows", "need_windows": "request_windows",
    "need-windows": "request_windows", "windows": "request_windows",
}

def _canonical_verdict(data: Dict[str, Any]) -> str:
    """The canonical verdict kind for a parsed verdict body.

    Tolerates the spelling and envelope differences models produce --
    ``APPROVED``, ``Approved.``, ``{"result": {"verdict": ...}}`` -- while
    keeping the decision set closed. An unrecognised or absent verdict
    returns ``""`` and the caller fails closed.
    """
    body = data
    if "verdict" not in body:
        # One level of envelope: {"result": {...}} / {"plan": {...}} / ...
        for key in ("result", "plan", "response", "output", "decision"):
            nested = body.get(key)
            if isinstance(nested, dict) and "verdict" in nested:
                body = nested
                break
    raw = body.get("verdict")
    if isinstance(raw, dict):
        raw = raw.get("verdict") or raw.get("kind") or raw.get("decision")
    # Models append their own sentence punctuation: "Approved.", "Approve!".
    key = str(raw or "").strip().strip(".!?").strip().lower().replace(" ", "_")
    return _VERDICT_ALIASES.get(key, "")

def parse_waist_verdict(response_text: str) -> Dict[str, Any]:
    """Parse and validate a waist verdict (strict; fail-closed).

    Returns one of ``{"verdict": "approve"}``, ``{"verdict": "amend",
    "dag": TaskDAG}`` (the replacement node set, re-validated for unique
    ids, unknown dependencies, cycles, and apply-time instruction
    length), ``{"verdict": "split", "dag": TaskDAG}`` (same shape and
    re-validation as amend; recorded distinctly so a planner that
    subdivides a node gets its own ledgered kind -- MR-4's four-way
    enum), ``{"verdict": "refuse", "reason", "evidence"}``, or
    ``{"verdict": "request_windows", "file_window_requests": [...]}``.
    """
    data = _parse_json_object(response_text, "waist plan verdict")
    verdict = _canonical_verdict(data)
    if verdict == "approve":
        return {"verdict": "approve"}
    if verdict in ("amend", "split"):
        nodes = data.get("nodes")
        if not isinstance(nodes, list) or not nodes:
            raise HarnessError(
                f"waist {verdict} verdict requires a non-empty 'nodes' list")
        amended = TaskDAG.from_dict({"nodes": nodes})
        for node in amended.nodes.values():
            if len(node.instruction) > MAX_INSTRUCTION_CHARS:
                raise HarnessError(
                    f"amended node {node.node_id!r} instruction exceeds "
                    f"{MAX_INSTRUCTION_CHARS} chars (would fail apply validation)")
        return {"verdict": verdict, "dag": amended}
    if verdict == "refuse":
        reason = str(data.get("reason") or "").strip()
        evidence = str(data.get("evidence") or "").strip()
        if not reason or not evidence:
            raise HarnessError(
                "waist refuse verdict requires non-empty 'reason' and "
                "'evidence' (cite the brief section that fails)")
        return {"verdict": "refuse", "reason": reason, "evidence": evidence}
    if verdict == "request_windows":
        requests = data.get("file_window_requests")
        if not isinstance(requests, list) or not requests:
            raise HarnessError(
                "waist request_windows verdict requires a non-empty "
                "'file_window_requests' list")
        return {"verdict": "request_windows",
                "file_window_requests": [_waist_window_request(r) for r in requests]}
    raw = str((data.get("verdict") if not isinstance(data.get("verdict"), dict)
               else data["verdict"].get("verdict")) or "").strip()
    raise HarnessError(f"unknown waist verdict {raw or '<missing>'!r}")

def plan_task_id(plan_result: Dict[str, Any]) -> str:
    """Deterministic ledger task id for a plan confirmation."""
    digest = hashlib.sha256(
        (plan_result.get("goal") or "").encode("utf-8")).hexdigest()[:12]
    return f"plan_{digest}"

def read_window(path: str, start_line=None, end_line=None) -> str:
    """Bounded source-window read for the brief (cwd-contained).

    Model-chosen paths are contained to the working tree (absolute paths
    and traversal outside the cwd are refused in-band, as an honest
    "refused" note the model can react to); missing files answer in-band
    too -- the window round-trip stays cheap and non-fatal.
    """
    raw = str(path)
    refused = "WINDOW REFUSED: only paths inside the working tree are readable"
    if os.path.isabs(raw) or ".." in raw.split(os.sep) or ".." in raw.split("/"):
        return refused
    root = os.path.realpath(os.getcwd())
    full = os.path.realpath(os.path.join(root, raw))
    if full != root and not full.startswith(root + os.sep):
        return refused
    try:
        with open(full, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return f"FILE NOT FOUND: {raw}"
    total = len(lines)
    start = max(int(start_line or 1), 1)
    if start > total:
        return f"WINDOW EMPTY: {raw} has {total} lines (requested start {start})"
    end = min(int(end_line or total), total, start + MAX_WINDOW_LINES - 1)
    body = "".join(lines[start - 1:end])
    return f"--- WINDOW: {raw} lines {start}-{end} of {total} ---\n{body}"

def _brief_for(plan_result: Dict[str, Any]) -> str:
    """Condensed signatures for the planned target files (the ONE brief)."""
    files: Dict[str, str] = {}
    for node in plan_result.get("nodes", []):
        for path in node.get("target_files", ()):
            if path in files or len(files) >= MAX_BRIEF_FILES:
                continue
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    files[path] = f.read()
            except OSError:
                continue
    if not files:
        return "(no readable target files; the plan names files that do not exist yet)"
    brief = distill_context(files, summary=plan_result.get("goal", ""))
    return brief.to_prompt_context()

def _verdict_cost(governor, spent_before: float) -> float:
    try:
        return round(governor.spent - spent_before, 6)
    except AttributeError:
        return 0.0

def confirm_plan(*, transport, api_key, governor, ledger, plan_result,
                 model, use_free=True, custom_frontier=None,
                 chat_fn=None, reader=read_window,
                 root=None, run_gate=None,
                 consensus=None,
                 max_rounds=MAX_WAIST_ROUNDS) -> Dict[str, Any]:
    """Run the waist: frontier confirms/repairs the plan; return the plan.

    Returns the (possibly amended) plan_result with a ``confirmation``
    field, or a ``status: "refused"`` envelope when the model refuses
    (callers must not execute it -- ``terminal_exit_code`` maps the
    unknown status to 2 fail-closed). Raises HarnessError when the model
    keeps requesting windows past ``max_rounds`` (the plan stays
    unconfirmed and unexecuted), on any transport/parse failure, or when
    ``model`` is unset (confirmation cannot silently skip itself).

    ``chat_fn(prompt) -> (text, cost)`` and ``reader(path, start, end) ->
    str`` are injectable seams for hermetic tests.
    """
    if not model:
        raise HarnessError(
            "waist confirmation requires a frontier model "
            "(--frontier-model or HARNESS_FRONTIER_MODEL)")
    if chat_fn is None:
        def chat_fn(prompt):
            return governed_text(transport, api_key, governor, model, prompt,
                                 WAIST_MAX_TOKENS, label="waist")
    brief = _brief_for(plan_result)
    task_id = plan_task_id(plan_result)
    if ledger is not None:
        ledger.ensure_offered_task_id(
            task_id, model=model, required=False, source="plan_confirmation")
    window_context = ""
    spent_before = governor.spent if governor is not None else 0.0

    for round_no in range(1, max_rounds + 1):
        prompt = build_waist_prompt(plan_result, brief, window_context,
                                    consensus=consensus)
        text, _cost = chat_fn(prompt)
        try:
            verdict = parse_waist_verdict(text)
        except HarnessError:
            # Fail closed on a malformed verdict: the spend already happened,
            # the plan stays unconfirmed, and the raw body is the evidence.
            if ledger is not None:
                ledger.append("plan_verdict", task_id=task_id, verdict="unparseable",
                              model=model, round=round_no)
            raise

        kind = verdict["verdict"]
        cost = _verdict_cost(governor, spent_before)
        if kind == "approve":
            plan_result["confirmation"] = {
                "verdict": "approved", "model": model, "rounds": round_no,
                "cost": cost}
            if ledger is not None:
                ledger.append("plan_verdict", task_id=task_id, verdict="approved",
                              model=model, rounds=round_no, cost=cost)
            return plan_result
        if kind == "refuse":
            refused = dict(plan_result)
            refused["status"] = "refused"
            refused["confirmation"] = {
                "verdict": "refused", "model": model, "rounds": round_no,
                "reason": verdict["reason"], "evidence": verdict["evidence"],
                "cost": cost}
            if ledger is not None:
                ledger.append("plan_verdict", task_id=task_id, verdict="refused",
                              model=model, rounds=round_no, cost=cost,
                              reason=verdict["reason"])
            return refused
        if kind in ("amend", "split"):
            amended = plan_task(
                plan_result.get("goal", ""),
                custom_frontier=custom_frontier, use_free=use_free,
                decomposed_dag=verdict["dag"], root=root, run_gate=run_gate)
            confirmed_kind = "amended" if kind == "amend" else "split"
            amended["confirmation"] = {
                "verdict": confirmed_kind, "model": model, "rounds": round_no,
                "cost": cost}
            if ledger is not None:
                ledger.append("plan_verdict", task_id=task_id, verdict=confirmed_kind,
                              model=model, rounds=round_no, cost=cost)
            return amended

        # request_windows: attach the bounded windows and spend another round
        blocks = [reader(req["path"], req.get("start_line"), req.get("end_line"))
                  for req in verdict["file_window_requests"][:MAX_WINDOWS_PER_ROUND]]
        window_context = "\n\n".join(blocks)
        if ledger is not None:
            ledger.append("plan_verdict", task_id=task_id,
                          verdict="request_windows", model=model, round=round_no,
                          windows=len(verdict["file_window_requests"]))
    raise HarnessError(
        f"waist requested file windows beyond the {max_rounds}-round budget; "
        "plan stays unconfirmed and will not execute")
