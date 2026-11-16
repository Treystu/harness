"""#275 L1-L3 — the Freebuff mission dossier's trace, decision and grade specs.

The dossier (2026-10-19) reverse-engineered Freebuff Desktop's mission mode and
proposed twelve lessons for Hourglass/HUL. L10 landed separately in
:mod:`harness.mission_record` (the 4,000-char mission cap). This module is the
dossier's own suggested action 1: adopt **L1-L3 into the HUL driver**, hermetically.

* **L1 — the clipped trace.** A manager that decides what happens next must not
  read the conversation. Freebuff clips agent prose to 4,000 chars per message,
  renders each tool call as one 140-char line, caps the whole trace at 60,000
  chars while keeping the original request (<=8,000 chars) as the scope anchor,
  and marks the dropped earlier turns instead of silently losing them. That
  trace is "enough to decide, never enough to drown", and it is adopted here as
  the one default context packet.

* **L2 — the typed decision.** Every continue/stop carries a forecast, its
  evidence and the alternatives it rejected: ``read``, ``decision``, ``why``,
  ``input``, ``declined[]``, ``expectedGain`` (0-3 forecast of the final
  outcome's 0-10 quality), ``confidence`` and ``evidence[]``. The validation is
  total: an undeclared key is refused, a decision of "run" without an input is
  refused, and a stop that carries an input is refused too -- "stop, but also
  do this" is two decisions.

* **L3 — the grade line.** A worker pass reports
  ``GRADES spec=<n> design=<n> correctness=<n> quality=<n>; biggest gap: ...``,
  and the driver steers at the *lowest* grade, in ladder order
  spec -> design -> correctness -> quality. Steering at the lowest dimension is
  what turns "what next?" into a target.

What this module deliberately does **not** do is decide *when* a mission is
finished. L8 and L9 are the dossier's named non-goals precisely because HUL is
ahead there: the Jev scope gate stays the authority on completion and the
durable mission pack stays the survival mechanism.
"""
import json
import math

#: Prose per message is clipped to this many characters (L1).
TRACE_PROSE_CLIP = 4000

#: A tool call renders as one line of at most this many characters (L1).
TRACE_TOOL_LINE = 140

#: The whole trace is budgeted to this many characters (L1).
TRACE_BUDGET = 60000

#: The original request is preserved up to this many characters (L1).
SCOPE_ANCHOR_MAX = 8000

#: The marker written where earlier turns were dropped (L1). It is explicit so
#: a decider can tell "nothing happened earlier" from "earlier was omitted".
OMITTED_MARKER = "[earlier turns omitted]"

#: How many pass receipts the decider is shown (L7's window, used here because
#: L1's trace and L7's receipts are read together).
RECEIPT_WINDOW = 8

#: The grade dimensions, in ladder order (L3). Order is load-bearing: a tie is
#: broken by climbing the ladder from the bottom.
GRADE_FIELDS = ("spec", "design", "correctness", "quality")

#: The declared decision fields, exactly (L2).
DECISION_FIELDS = ("read", "decision", "why", "input", "declined",
                   "expectedGain", "confidence", "evidence")

#: The two decisions a decider may emit (L2).
DECISIONS = ("run", "stop")

#: What a run's input may be for (L2).
INPUT_PURPOSES = ("required", "refinement")

#: The largest expectedGain forecast (L2): a 0-3 improvement to a 0-10 outcome.
MAX_EXPECTED_GAIN = 3.0


class HulDecisionError(ValueError):
    """A trace, decision or grade line that does not meet the dossier's spec."""


def _is_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _clip(text, limit):
    text = "" if text is None else str(text)
    if len(text) <= limit:
        return text, 0
    return text[:limit], len(text) - limit


def clip_message(message):
    """One trace line for one message: prose clipped, tool calls one-lined.

    A tool call is rendered as ``tool: <name> <args>`` and cut to
    :data:`TRACE_TOOL_LINE`; a plain message keeps up to
    :data:`TRACE_PROSE_CLIP` characters. The returned dict reports what was
    dropped so a caller can tell a clipped line from a complete one.
    """
    if not isinstance(message, dict):
        raise HulDecisionError(
            f"a trace message must be a mapping, got {type(message).__name__}")
    role = str(message.get("role") or "worker")
    tool = message.get("tool")
    if tool:
        rendered = f"tool: {tool} {message.get('args') or ''}".strip()
        text, dropped = _clip(rendered, TRACE_TOOL_LINE)
        return {"role": role, "kind": "tool", "text": text,
                "dropped": dropped}
    text, dropped = _clip(message.get("text"), TRACE_PROSE_CLIP)
    kind = "diff" if message.get("diff") else "prose"
    if kind == "diff":
        # A diff is summarized by its file count, never its content: the
        # decider needs to know that files moved, not what moved in them.
        files = message.get("files") or ()
        text = f"diff: {len(files)} file(s) changed"
        dropped = 0
    return {"role": role, "kind": kind, "text": text, "dropped": dropped}


def clip_trace(messages, *, scope_anchor=None, budget=TRACE_BUDGET):
    """The L1 context packet: a bounded trace with its scope anchor preserved.

    Recent messages are kept newest-first until the budget would be exceeded;
    everything older becomes one :data:`OMITTED_MARKER` line. The scope anchor
    (the original request, clipped to :data:`SCOPE_ANCHOR_MAX`) is kept even
    when it alone is larger than a turn's share, because it is what a decider
    judges relevance against.
    """
    if not isinstance(messages, (list, tuple)):
        raise HulDecisionError("a trace must be a sequence of messages")
    if not _is_number(budget) or budget <= 0:
        raise HulDecisionError(
            f"a trace budget must be a positive number, got {budget!r}")
    anchor = ""
    if scope_anchor is not None:
        anchor, anchor_dropped = _clip(scope_anchor, SCOPE_ANCHOR_MAX)
    else:
        anchor_dropped = 0

    kept, used, omitted = [], 0, 0
    for message in reversed(list(messages)):
        line = clip_message(message)
        cost = len(line["text"]) + 1
        if used + cost > budget:
            omitted += 1
            continue
        kept.append(line)
        used += cost
    kept.reverse()

    lines = []
    if anchor:
        lines.append(f"scope: {anchor}")
    if omitted:
        lines.append(OMITTED_MARKER)
    lines.extend(f"{line['role']}: {line['text']}" for line in kept)
    text = "\n".join(lines)
    return {"schema": "hul-trace@1", "text": text, "lines": lines,
            "chars": len(text), "budget": float(budget),
            "omitted": omitted, "kept": len(kept),
            "anchor_preserved": bool(anchor), "anchor_dropped": anchor_dropped}


def _checked_string(value, field):
    if not isinstance(value, str) or not value.strip():
        raise HulDecisionError(f"{field} must be a non-empty string, got {value!r}")
    return value.strip()


def _checked_strings(value, field):
    if not isinstance(value, (list, tuple)):
        raise HulDecisionError(f"{field} must be a sequence, got {type(value).__name__}")
    return [_checked_string(item, field) for item in value]


def validate_decision(payload):
    """The L2 typed decision, normalised, or a refusal naming the field.

    Total validation on purpose. A decider that can smuggle an undeclared key,
    omit its forecast or say "stop" while also asking for work is a decider
    whose output cannot be audited, and this is the surface that makes it
    auditable by construction.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError as exc:
            raise HulDecisionError(f"a decision is not valid JSON: {exc}") from None
    if not isinstance(payload, dict):
        raise HulDecisionError(
            f"a decision must be a mapping, got {type(payload).__name__}")
    unknown = sorted(set(payload) - set(DECISION_FIELDS))
    if unknown:
        raise HulDecisionError(
            f"a decision declares {list(DECISION_FIELDS)}; unknown key(s) {unknown}")
    missing = sorted(f for f in ("decision", "why") if f not in payload)
    if missing:
        raise HulDecisionError(f"a decision is missing required key(s) {missing}")

    decision = payload["decision"]
    if decision not in DECISIONS:
        raise HulDecisionError(
            f"decision must be one of {list(DECISIONS)}, got {decision!r}")
    why = _checked_string(payload["why"], "why")

    evidence = _checked_strings(payload.get("evidence") or [], "evidence")
    declined = _checked_strings(payload.get("declined") or [], "declined")

    gain = payload.get("expectedGain", 0)
    if not _is_number(gain) or not (0 <= float(gain) <= MAX_EXPECTED_GAIN):
        raise HulDecisionError(
            f"expectedGain must be a number in [0, {MAX_EXPECTED_GAIN:g}], got {gain!r}")
    confidence = payload.get("confidence", 0.0)
    if not _is_number(confidence) or not (0 <= float(confidence) <= 1):
        raise HulDecisionError(
            f"confidence must be a number in [0, 1], got {confidence!r}")

    normalised = {"decision": decision, "why": why,
                  "expectedGain": float(gain),
                  "confidence": float(confidence),
                  "evidence": evidence, "declined": declined}
    if "read" in payload:
        normalised["read"] = bool(payload["read"])

    if decision == "stop":
        if payload.get("input") is not None:
            raise HulDecisionError(
                "a stop decision carries no input; 'stop, but also do this' is "
                "two decisions, and only one of them may be obeyed")
        return normalised

    raw_input = payload.get("input")
    if not isinstance(raw_input, dict) or not raw_input:
        raise HulDecisionError(
            "a run decision must carry an input (a skill, or label + prompt)")
    unknown_input = sorted(set(raw_input) - {"skill", "label", "prompt", "purpose"})
    if unknown_input:
        raise HulDecisionError(
            f"a decision input declares skill | label+prompt | purpose; unknown "
            f"key(s) {unknown_input}")
    purpose = raw_input.get("purpose", "required")
    if purpose not in INPUT_PURPOSES:
        raise HulDecisionError(
            f"input purpose must be one of {list(INPUT_PURPOSES)}, got {purpose!r}")
    if raw_input.get("skill"):
        normalised["input"] = {"skill": _checked_string(raw_input["skill"], "skill"),
                               "purpose": purpose}
        return normalised
    if not raw_input.get("label") or not raw_input.get("prompt"):
        raise HulDecisionError(
            "a run input needs either a skill, or both a label and a prompt")
    normalised["input"] = {"label": _checked_string(raw_input["label"], "label"),
                           "prompt": _checked_string(raw_input["prompt"], "prompt"),
                           "purpose": purpose}
    return normalised


def format_grade_line(grades, biggest_gap):
    """Render the L3 pass-report header from a grade mapping."""
    if not isinstance(grades, dict):
        raise HulDecisionError("grades must be a mapping")
    parts = []
    for field in GRADE_FIELDS:
        value = grades.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 10:
            raise HulDecisionError(
                f"grade {field!r} must be an integer in [0, 10], got {value!r}")
        parts.append(f"{field}={value}")
    gap = _checked_string(biggest_gap, "biggest gap")
    return f"GRADES {' '.join(parts)}; biggest gap: {gap}"


def parse_grade_line(report):
    """Read the L3 header out of a worker report, or refuse by name.

    The header is the first line of the report; anything missing from it is a
    refusal rather than a zero, because a zero would look like a real grade and
    steer the next attempt at a dimension nobody measured.
    """
    if not isinstance(report, str):
        raise HulDecisionError(
            f"a report must be a string, got {type(report).__name__}")
    first = report.strip().splitlines()[0] if report.strip() else ""
    if not first.upper().startswith("GRADES "):
        raise HulDecisionError(
            "a worker pass must begin with 'GRADES spec=… design=… "
            f"correctness=… quality=…; biggest gap: …', got {first[:60]!r}")
    head, _, gap = first.partition("; biggest gap:")
    grades = {}
    for token in head.split()[1:]:
        name, _, value = token.partition("=")
        if name not in GRADE_FIELDS:
            raise HulDecisionError(f"undeclared grade dimension {name!r}")
        try:
            grades[name] = int(value)
        except ValueError:
            raise HulDecisionError(
                f"grade {name!r} is not an integer: {value!r}") from None
        if not 0 <= grades[name] <= 10:
            raise HulDecisionError(f"grade {name!r} is outside [0, 10]")
    missing = [f for f in GRADE_FIELDS if f not in grades]
    if missing:
        raise HulDecisionError(f"grade line is missing dimension(s) {missing}")
    return {"grades": grades, "biggest_gap": gap.strip() or None}


def next_grade_target(grades):
    """The dimension to steer the next attempt at (L3): the lowest, ladder-first.

    A tie goes to the earlier dimension in :data:`GRADE_FIELDS`, which is the
    dossier's ladder: spec before design before correctness before quality. The
    return value is ``(dimension, grade)`` so a caller can both name the target
    and log what it was measured at.
    """
    if not isinstance(grades, dict):
        raise HulDecisionError("grades must be a mapping")
    for field in GRADE_FIELDS:
        if field not in grades:
            raise HulDecisionError(f"grades are missing {field!r}")
    lowest = GRADE_FIELDS[0]
    for field in GRADE_FIELDS[1:]:
        if grades[field] < grades[lowest]:
            lowest = field
    return lowest, grades[lowest]


def receipts_window(receipts, *, limit=RECEIPT_WINDOW):
    """The last ``limit`` pass receipts, normalised, oldest first (L7/L1).

    Manager and worker spend are kept apart: the reason the decider sees them
    separately is to judge whether *passes* are getting more or less efficient,
    which a combined figure cannot show.
    """
    if not isinstance(receipts, (list, tuple)):
        raise HulDecisionError("receipts must be a sequence")
    if not isinstance(limit, int) or limit < 1:
        raise HulDecisionError(f"limit must be a positive integer, got {limit!r}")
    window = []
    for receipt in list(receipts)[-limit:]:
        if not isinstance(receipt, dict):
            raise HulDecisionError(
                f"a receipt must be a mapping, got {type(receipt).__name__}")
        window.append({
            "pass": receipt.get("pass"),
            "manager_tokens": int(receipt.get("manager_tokens") or 0),
            "worker_tokens": int(receipt.get("worker_tokens") or 0),
            "cost": float(receipt.get("cost") or 0.0),
            "duration": float(receipt.get("duration") or 0.0),
        })
    return window
