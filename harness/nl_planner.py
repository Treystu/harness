"""Natural language to action-plan seam for the driver wave (#271).

``plan`` converts one operator sentence into a validated action plan: a list
of ``{"action": name, "params": {...}}`` steps drawn ONLY from the declared
driver vocabulary. The LLM is injected as ``chat_fn(prompt) -> text`` and run
under a bounded timeout, so this module stays pure and hermetically testable:
planning may degrade loudly, spending may not degrade silently.

The host gate (``HARNESS_NL_CONTROL``, default off) lives upstream in
``harness.server``: this module never reads the environment, it only refuses
to invent actions the vocabulary did not declare.
"""

import json
import threading

from driver_core.actions import DEFAULT_VOCABULARY, VocabularyError
from harness.errors import HarnessError

#: Bound on one planner LLM call (#271 acceptance: 10s). A planner that has
#: not answered in time is a failed plan, never a step that never ends.
NL_PLAN_TIMEOUT = 10.0


def build_nl_plan_prompt(user_input, vocabulary=DEFAULT_VOCABULARY):
    """Render the ONLY-JSON planning prompt for ``user_input``."""
    lines = [
        "Convert the operator request into a JSON array of action steps.",
        "Output ONLY the JSON array, no prose, no fences.",
        "Each step is an object with exactly two keys: "
        "\"action\" (a string) and \"params\" (an object).",
        "Every action name MUST be one of the declared actions below, "
        "with only its declared params:",
    ]
    for action in vocabulary.actions():
        params = ", ".join(action.params) if action.params else "(no params)"
        lines.append(f"- {action.name}({params})")
    lines.append(f"Operator request: {user_input}")
    return "\n".join(lines)


def _call_with_timeout(chat_fn, prompt, timeout):
    """Run ``chat_fn(prompt)`` and return its text within ``timeout`` seconds.

    A late answer raises instead of hanging the plan lane; a daemon worker
    means the abandoned call can never hold the process open. The worker
    body is a single statement on purpose: the traced D12 battery cannot
    see worker-thread lines, so every branch of the timeout/empty/failed
    ladder lives here in the calling thread where it is measured.
    """
    box = {}

    def run():
        box["text"] = chat_fn(prompt)

    worker = threading.Thread(target=run, name="nl-planner-chat", daemon=True)
    worker.start()
    worker.join(timeout=timeout)
    if worker.is_alive():
        raise HarnessError(
            f"NL planner LLM call exceeded {timeout:g}s")
    if "text" not in box:
        raise HarnessError(
            "NL planner LLM call failed before returning a result")
    return box["text"]


def _parse_plan(text):
    """Parse raw LLM text into a non-empty list of raw steps."""
    try:
        parsed = json.loads(text)
    except ValueError as exc:
        raise HarnessError(
            f"NL planner LLM did not return JSON: {exc}") from exc
    if not isinstance(parsed, list):
        raise HarnessError(
            "NL planner LLM must return a JSON array of steps, "
            f"got {type(parsed).__name__}")
    if not parsed:
        raise HarnessError("NL planner LLM returned no steps")
    steps = []
    for index, item in enumerate(parsed):
        if not isinstance(item, dict):
            raise HarnessError(
                f"NL planner step {index} is not an object")
        name = item.get("action")
        if not isinstance(name, str) or not name:
            raise HarnessError(
                f"NL planner step {index} has no action name")
        params = item.get("params", {})
        if not isinstance(params, dict):
            raise HarnessError(
                f"NL planner step {name!r} params must be an object")
        steps.append({"action": name, "params": dict(params)})
    return steps


def _validate_plan(steps, vocabulary):
    """Resolve every step against the declared vocabulary."""
    validated = []
    for step in steps:
        try:
            declared = vocabulary.resolve(step["action"])
        except VocabularyError as exc:
            raise HarnessError(
                f"NL planner proposed undeclared action: {exc}") from exc
        extras = sorted(set(step["params"]) - set(declared.params))
        if extras:
            raise HarnessError(
                f"NL planner step {step['action']!r} names undeclared "
                f"params {extras}; declared: {sorted(declared.params)}")
        validated.append({"action": step["action"],
                          "params": dict(step["params"])})
    return validated


def plan(user_input, chat_fn, *, timeout=NL_PLAN_TIMEOUT,
         vocabulary=DEFAULT_VOCABULARY):
    """Plan ``user_input`` into validated ``[{"action", "params"}]`` steps.

    Raises HarnessError on empty input, an empty/late/failing LLM answer, a
    non-JSON answer, or any step naming an undeclared action or param.
    """
    if not user_input or not str(user_input).strip():
        raise HarnessError("NL planner needs a non-empty request")
    prompt = build_nl_plan_prompt(str(user_input), vocabulary)
    raw = _call_with_timeout(chat_fn, prompt, timeout)
    if not raw or not str(raw).strip():
        raise HarnessError("NL planner LLM returned an empty response")
    return _validate_plan(_parse_plan(raw), vocabulary)
