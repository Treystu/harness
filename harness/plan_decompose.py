"""Decomposition owner (M1): prompt construction, JSON recovery, response parsing and the LLM/heuristic decompose entry points.

Owner split per #308: this module owns decomposition and its parsing only.
The waist consumes `parse_decomposition_response`; nothing here knows about
consensus, confirmation, stage budgets or brief assembly."""
import ast
import hashlib
import json
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .dag import DAGNode, TaskDAG
from .errors import HarnessError
from .validation import MAX_INSTRUCTION_CHARS


def build_decomposition_prompt(
    goal: str,
    repo_context: Optional[str] = None,
    candidate_files: Optional[Sequence[str]] = None,
) -> str:
    """Build a prompt instructing a model to decompose a goal into a TaskDAG JSON."""
    lines = [
        "You are an expert software architect decomposing a development task into an atomic, dependency-ordered work graph.",
        "",
        "GOAL:",
        goal.strip(),
        "",
    ]
    if candidate_files:
        lines.append("AVAILABLE / CANDIDATE FILES:")
        for cf in sorted(candidate_files):
            lines.append(f"  - {cf}")
        lines.append("")

    if repo_context:
        lines.append("REPOSITORY CONTEXT:")
        lines.append(repo_context.strip())
        lines.append("")

    lines.extend([
        "INSTRUCTIONS:",
        "1. Break the goal into small, focused, verifiable subtasks (DAG nodes).",
        "2. EVERY node MUST end in a file being written or modified: each node",
        "   is executed by a code-writing engine that receives the node's",
        "   instruction and edits its target file. Do NOT create analysis,",
        "   research, inspection, planning, or review nodes -- the planning",
        "   pass already gathered that context. An instruction like 'inspect",
        "   X' or 'determine what to test' is ALWAYS WRONG: fold whatever it",
        "   was meant to learn into the writing node's instruction instead.",
        "3. For each subtask, declare:",
        "   - 'node_id': unique alphanumeric identifier (e.g. 'task_1', 'task_2').",
        "   - 'instruction': the COMPLETE, self-contained change to make to the",
        "     target file in this step (the executor sees no other context):",
        "     what to write, with the exact behavior, signatures, and cases.",
        "   - 'target_files': list of exact files modified by this subtask (at most 1-2 files per node).",
        "   - 'create_files': the subset of target_files that do NOT exist yet",
        "     and must be CREATED (greenfield files, e.g. a new package). Name",
        "     a file here exactly when it is absent from AVAILABLE / CANDIDATE",
        "     FILES above; the executor refuses to create any target NOT listed",
        "     here, so a typo'd path can never conjure an unintended file.",
        "   - 'dependencies': list of node_ids that MUST pass before this subtask can begin.",
        "   - 'local_gate': automated verification command run in the target",
        "     file's directory (e.g. 'python -m unittest test_types') or null.",
        "   - 'complexity_tier': 0 (scout/simple fix), 1 (standard logic), 2 (deep architecture/frontier).",
        "4. Ensure the graph is strictly ACYCLIC (no circular dependencies).",
        "5. Independent tasks should have empty dependencies so they can run concurrently.",
        "",
        "Output ONLY valid JSON matching this schema:",
        "```json",
        "{",
        '  "nodes": [',
        '    {',
        '      "node_id": "task_1",',
        '      "instruction": "Create pkg/types.py defining the ShipmentsFilter dataclass with fields query (str), limit (int, default 20); include a __repr__.",',
        '      "target_files": ["pkg/types.py"],',
        '      "create_files": ["pkg/types.py"],',
        '      "dependencies": [],',
        '      "local_gate": "python -m unittest tests.test_types",',
        '      "complexity_tier": 0',
        '    }',
        '  ]',
        "}",
        "```"
    ])
    return "\n".join(lines)

def _balanced_object_spans(text: str) -> List[str]:
    """Every balanced ``{...}`` span in ``text``, left to right.

    Brace counting is string-aware, so a ``}`` inside a JSON string does not
    close the span early, and an unbalanced ``{`` (a reasoning trace that
    mentions one) is skipped rather than swallowing the rest of the response.
    """
    spans: List[str] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth = 0
        in_string = False
        escaped = False
        closed = -1
        for j in range(i, n):
            ch = text[j]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    closed = j
                    break
        if closed == -1:
            # Unbalanced to end of text: resume at the next opening brace so a
            # stray '{' in prose cannot hide a real object that follows it.
            nxt = text.find("{", i + 1)
            if nxt == -1:
                break
            i = nxt
            continue
        spans.append(text[i:closed + 1])
        i = closed + 1
    return spans

def _repair_truncated_json(candidate: str) -> Optional[dict]:
    """Attempt to repair JSON truncated by token limits (unclosed braces/brackets/strings)."""
    s = candidate.strip()
    if not s.startswith("{"):
        return None
    # Strip trailing commas or trailing incomplete key/colon
    s = re.sub(r',\s*$', '', s)
    s = re.sub(r':\s*$', ': ""', s)
    in_str = False
    escaped = False
    open_brackets = 0
    open_braces = 0
    for ch in s:
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == '[':
            open_brackets += 1
        elif ch == ']':
            open_brackets = max(0, open_brackets - 1)
        elif ch == '{':
            open_braces += 1
        elif ch == '}':
            open_braces = max(0, open_braces - 1)
    if in_str:
        s += '"'
    s += ']' * open_brackets
    s += '}' * open_braces
    try:
        data = json.loads(s)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return None

def _json_object_candidates(text: str) -> Iterable[str]:
    """Candidate JSON object texts, most-trusted first.

    A fenced block is the model naming its own payload, so it outranks
    anything found by scanning. After that: the first balanced object, so a
    reasoning trace printed before the answer cannot displace it.
    """
    clean_text = re.sub(r"<(think|thought|reasoning|reflection)>[\s\S]*?</\1>", "", text, flags=re.IGNORECASE).strip()
    clean_text = re.sub(r"\[harness:reasoning_fallback\][\s\S]*?\n\n", "", clean_text).strip()
    sources = [clean_text] if clean_text and clean_text != text else []
    sources.append(text)
    seen = set()
    for src in sources:
        for m in re.finditer(r"(`{3,})(?:json)?\s*([\s\S]*?)\s*\1", src, re.IGNORECASE):
            body = m.group(2).strip()
            if body and body not in seen:
                seen.add(body)
                yield body
        for span in _balanced_object_spans(src):
            if span not in seen:
                seen.add(span)
                yield span
        first_brace = src.find("{")
        last_brace = src.rfind("}")
        if first_brace != -1 and last_brace > first_brace:
            outer = src[first_brace:last_brace + 1]
            if outer not in seen:
                seen.add(outer)
                yield outer

def _parse_json_object(response_text: str, what: str) -> Dict[str, Any]:
    """Extract a JSON object from an LLM response. ONE owner of that
    extraction (decomposition and waist verdicts share it).

    Robust to the shapes models actually emit -- a fenced block, a bare
    object, an object wrapped in prose or a reasoning trace, an object
    followed by trailing commentary -- and still fail-closed: if no candidate
    parses to an object this raises, rather than inventing an empty answer.
    A reasoning-only response therefore fails here, which is what lets the
    caller treat it as a retryable transport-shaped failure instead of a
    verdict.
    """
    if not response_text or not response_text.strip():
        raise HarnessError(f"empty response for {what}")

    text = response_text.strip()
    candidates = list(_json_object_candidates(text))
    if text.startswith("{") or not candidates:
        candidates.append(text)          # last resort: the whole body is the object

    last_error: Exception = HarnessError(
        f"no valid JSON object found in {what}")
    for candidate in candidates:
        # 1. Direct standard JSON
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
            last_error = HarnessError(f"{what} must be a JSON object, not {type(data).__name__}")
            continue
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            last_error = exc

        # 2. Tolerant retry: strip JS single-line comments and trailing commas in arrays/objects
        cleaned = re.sub(r'//[^\n]*', '', candidate)
        cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)
        try:
            data = json.loads(cleaned)
            if isinstance(data, dict):
                return data
            last_error = HarnessError(f"{what} must be a JSON object, not {type(data).__name__}")
            continue
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

        # 3. Python-style literal dict (single quotes, True/False/None)
        try:
            val = ast.literal_eval(cleaned.strip())
            if isinstance(val, dict):
                return val
        except Exception:
            pass

        # 4. Truncated JSON repair (e.g. cut off at max token boundary)
        repaired = _repair_truncated_json(candidate)
        if repaired is not None:
            return repaired

    raise HarnessError(
        f"failed to parse JSON from {what}: {last_error}") from last_error

def parse_decomposition_response(response_text: str) -> TaskDAG:
    """Extract and parse a TaskDAG from an LLM's response text."""
    data = _parse_json_object(response_text, "task decomposition")
    return TaskDAG.from_dict(data)

def _salvage_decomposition(response_text: str) -> Optional[TaskDAG]:
    """Deterministic salvage of a malformed decomposition body (#541).

    The bounded repair for a parse failure: recover the structure the model
    already produced instead of spending a second full decomposition call.
    Two shapes are recovered, both schema-checked through ``TaskDAG.from_dict``
    so a salvage can never admit a node the strict parser would reject:

    1. individual node objects that survived the truncation (``node_id`` +
       ``instruction``), assembled into one DAG; and
    2. the legacy ``nodes`` mapping, which may be the only thing that parsed.

    Returns ``None`` when nothing usable is present -- the caller then falls
    back to the heuristic plan with the raw body preserved.
    """
    text = str(response_text or "")
    if not text.strip():
        return None
    recovered: Dict[str, Any] = {}
    for span in _balanced_object_spans(text):
        data = None
        try:
            data = json.loads(span)
        except (json.JSONDecodeError, UnicodeDecodeError):
            try:
                literal = ast.literal_eval(span)
                data = literal if isinstance(literal, dict) else None
            except Exception:
                data = None
        if not isinstance(data, dict):
            continue
        if isinstance(data.get("nodes"), (dict, list)):
            payload = data
            if isinstance(payload.get("nodes"), dict):
                # A models sometimes emit ``nodes`` as a mapping; the strict
                # DAG contract takes a list, so normalise before validating.
                payload = dict(payload)
                payload["nodes"] = list(payload["nodes"].values())
            try:
                dag = TaskDAG.from_dict(payload)
            except HarnessError:
                dag = None
            if dag is not None and dag.nodes:
                return dag
        node_id = data.get("node_id") or data.get("id")
        instruction = data.get("instruction") or data.get("description")
        if (isinstance(node_id, str) and node_id.strip()
                and isinstance(instruction, str) and instruction.strip()):
            recovered.setdefault(node_id.strip(), data)
    if recovered:
        try:
            dag = TaskDAG.from_dict({"nodes": list(recovered.values())})
        except HarnessError:
            dag = None
        if dag is not None and dag.nodes:
            return dag
    return None

def decomposition_repair_record(exc: Exception, raw: str) -> Dict[str, Any]:
    """The run-record evidence for one decomposition repair attempt (#541).

    Carries the parse error and the exact raw body (bounded) so a malformed
    decomposition is diagnosable after the fact instead of being discarded.
    """
    body = str(raw or "")
    return {
        "path": "deterministic_salvage",
        "cost": 0.0,
        "parse_error": str(exc)[:400],
        "raw_output": body[:4000],
        "raw_output_chars": len(body),
        "raw_output_sha256": hashlib.sha256(
            body.encode("utf-8", "replace")).hexdigest(),
    }

def heuristic_decompose_goal(goal: str, candidate_files: Optional[Sequence[str]] = None,
                             *, root_dir: Optional[str] = None) -> TaskDAG:
    # Deterministic heuristic decomposition into a TaskDAG.
    # #456 greenfield creation: candidate files that do not exist under
    # root_dir are marked create_files, so the executor creates (not edits)
    # them. Without root_dir every candidate is assumed to exist.
    if not goal or not goal.strip():
        raise HarnessError("goal cannot be empty")

    files = [f.strip() for f in (candidate_files or []) if str(f).strip()]
    nodes: Dict[str, DAGNode] = {}

    def _creates(targets):
        if root_dir is None:
            return ()
        missing = []
        for rel in targets:
            full = rel if os.path.isabs(rel) else os.path.join(root_dir, rel)
            if not os.path.exists(full):
                missing.append(rel)
        return tuple(missing)

    # Check for numbered or bulleted steps in goal
    steps = [s.strip() for s in re.split(r"(?:^|\n)\s*(?:\d+[\.\)]|[-*])\s+", goal.strip()) if s.strip()]

    if len(steps) > 1:
        # Multi-step goal
        prev_id = None
        for i, step in enumerate(steps, 1):
            node_id = f"task_{i}"
            deps = (prev_id,) if prev_id else ()
            target = (files[i - 1],) if i - 1 < len(files) else ()
            nodes[node_id] = DAGNode(
                node_id=node_id,
                instruction=step,
                target_files=target,
                create_files=_creates(target),
                dependencies=deps,
                complexity_tier=1,
            )
            prev_id = node_id
    elif len(files) > 1:
        # Multi-file goal: one subtask per file
        test_files = [f for f in files if "test" in f.lower()]
        impl_files = [f for f in files if f not in test_files]

        impl_ids = []
        for i, f in enumerate(impl_files, 1):
            node_id = f"task_{i}"
            impl_ids.append(node_id)
            nodes[node_id] = DAGNode(
                node_id=node_id,
                instruction=f"{goal.strip()} for {f}",
                target_files=(f,),
                create_files=_creates((f,)),
                dependencies=(),
                complexity_tier=1,
            )

        start_test_idx = len(impl_files) + 1
        for j, f in enumerate(test_files, start_test_idx):
            node_id = f"task_{j}"
            nodes[node_id] = DAGNode(
                node_id=node_id,
                instruction=f"Update tests in {f} for {goal.strip()}",
                target_files=(f,),
                create_files=_creates((f,)),
                dependencies=tuple(impl_ids),
                complexity_tier=1,
            )
    else:
        # Single node goal
        target = tuple(files)
        if not target:
            # If no files were provided, check if the goal mentions a specific file
            found = re.findall(r"\b[\w-]+\.(?:py|rs|go|ts|js|md|json|toml|yaml|yml|c|cpp|h)\b", goal)
            if found:
                target = (found[0],)
            else:
                # Default deliverable target for analytical / open-ended tasks
                target = ("docs/reports/analysis.md",)
        nodes["task_1"] = DAGNode(
            node_id="task_1",
            instruction=goal.strip(),
            target_files=target,
            create_files=_creates(target),
            dependencies=(),
            complexity_tier=1,
        )

    return TaskDAG(nodes=nodes)

def decompose_via_llm(
    chat_fn,
    goal: str,
    candidate_files: Optional[Sequence[str]] = None,
    repo_context: Optional[str] = None,
) -> TaskDAG:
    """M1 seam: a cheap model authors the DAG; strict schema validation.

    ``chat_fn(prompt) -> response text`` is injected (governed upstream via
    ``chat.governed_text``), so this stays pure and hermetically testable.
    Raises HarnessError on empty/invalid responses, an empty node set, or
    nodes that would fail apply-time validation (instruction length). The
    heuristic decomposition stays the caller's fallback: planning may
    degrade loudly, spending may not degrade silently.
    """
    prompt = build_decomposition_prompt(
        goal, repo_context=repo_context, candidate_files=candidate_files)
    raw = chat_fn(prompt)
    if not raw or not str(raw).strip():
        raise HarnessError("LLM decomposition returned empty response")
    dag = parse_decomposition_response(raw)
    if not dag.nodes:
        raise HarnessError("LLM decomposition returned no nodes")
    for node in dag.nodes.values():
        if len(node.instruction) > MAX_INSTRUCTION_CHARS:
            raise HarnessError(
                f"LLM decomposition node {node.node_id!r} instruction exceeds "
                f"{MAX_INSTRUCTION_CHARS} chars (would fail apply validation)")
    return dag
