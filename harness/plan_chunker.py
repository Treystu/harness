"""Tier-0 chunking policy owner (#308).

One owner of the question "can ONE model pass do this node?" -- and of the
answer when it cannot. A node is split into ordered chunks only when one pass
genuinely cannot do the work:

* the instruction is longer than the apply validation ceiling
  (``validation.MAX_INSTRUCTION_CHARS`` -- such a request could never be sent,
  so it must become several requests), or
* one pass cannot even READ the target (more estimated tokens than the pass's
  quoted-source budget, ``capability.source_budget_for``; a node whose rung
  declares no context is left alone -- see ``source_tokens``).

A target past the engine's whole-file rewrite cap is NOT split: it becomes one
node carrying the ``backend="diff"`` hint, so the pass emits bounded hunks.

The waist keeps the orchestration: ``_fit_plan_to_single_pass`` applies this
policy to a plan result and re-derives node details when the DAG changed.
"""
import math
import os
import re
from typing import Any, Dict, List, Optional

from .capability import load_profiles, source_budget_for
from .config import CAPABILITIES_PATH, DEFAULT_APPLY_MAX_TOKENS
from .dag import DAGNode, TaskDAG
from .prompts import MAX_FILE_LINES
from .tokens import estimate_prompt_tokens
from .validation import MAX_INSTRUCTION_CHARS


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
