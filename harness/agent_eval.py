"""#285 -- an agent-eval layer over the MCP surface, scored as a pass rate.

The MCP catalog tells a model what each tool is for; nothing checked whether a
model given a task actually *selects* the right tool and chains multi-step calls
in the right order. This module is that layer, and it is deliberately split so
the scoring can run with no model at all:

* a **declared eval set** checked into the repo (``packs/agent_eval/``): task
  prompts plus the tool chain each one should produce;
* a **hermetic mode** that scores a *recorded* transcript, so CI has a real
  number without a provider call;
* a **live mode** that is opt-in and must name the model and the cost of the run
  -- a live result that cannot say what produced it is not evidence.

The score is a pass **rate** against a configurable threshold (default
:data:`DEFAULT_THRESHOLD`), recorded in the output, because partial competence is
information: a run that gets 9 of 12 chains right is different from one that gets
3, and a boolean throws that away.
"""
import json
import os

#: Output schema. Bump when a field changes meaning.
SCHEMA = "agent-eval@1"

#: Default pass-rate threshold, recorded in every run.
DEFAULT_THRESHOLD = 0.8

#: A case's expected tool chain may be matched as an exact chain, an unordered
#: set, or a chain prefix (the observable start of a longer plan).
MATCH_MODES = ("chain", "set", "prefix")


class EvalError(ValueError):
    """An eval set or transcript that cannot produce an honest score."""


def load_eval_set(path):
    """Load and validate a declared eval set (JSON, ``{"cases": [...]}``)."""
    if not isinstance(path, str) or not path:
        raise EvalError(f"eval set path must be a string, got {path!r}")
    with open(path, encoding="utf-8") as handle:
        try:
            doc = json.load(handle)
        except ValueError as exc:
            raise EvalError(f"{path} is not valid JSON: {exc}") from None
    cases = doc.get("cases") if isinstance(doc, dict) else None
    if not isinstance(cases, list) or not cases:
        raise EvalError(f"{path} declares no cases")
    seen = set()
    out = []
    for case in cases:
        if not isinstance(case, dict):
            raise EvalError(f"case {case!r} is not a mapping")
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id.strip():
            raise EvalError("every case needs an id")
        if case_id in seen:
            raise EvalError(f"duplicate case id {case_id!r}")
        seen.add(case_id)
        prompt = case.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise EvalError(f"case {case_id!r} has no prompt")
        expected = (case.get("expect") or {}).get("tools")
        if not isinstance(expected, list) or not expected:
            raise EvalError(f"case {case_id!r} declares no expected tools")
        mode = (case.get("expect") or {}).get("mode", "chain")
        if mode not in MATCH_MODES:
            raise EvalError(
                f"case {case_id!r} mode must be one of {list(MATCH_MODES)}, got {mode!r}")
        out.append({
            "id": case_id,
            "prompt": prompt.strip(),
            "expected": [str(t) for t in expected],
            "mode": mode,
            "allow_extra": bool(case.get("allow_extra")),
        })
    return out


def load_transcript(path):
    """Load a recorded transcript: ``{"model": ..., "calls": {case_id: [tools]}}``."""
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
    calls = doc.get("calls")
    if not isinstance(calls, dict):
        raise EvalError(f"{path} has no calls mapping")
    return {"model": str(doc.get("model") or ""),
            "cost_usd": doc.get("cost_usd", 0.0),
            "calls": {str(k): [str(t) for t in v] for k, v in calls.items()}}


def score_case(case, observed):
    """One case: ``{pass, reason, expected, observed}``.

    Chain mode compares the sequence; set mode ignores order; prefix mode accepts
    a longer plan that *starts* with the expected chain. Extra calls fail the case
    unless it explicitly allows them -- selecting an extra write tool is a real
    mistake, not noise.
    """
    if not isinstance(observed, list):
        raise EvalError(f"case {case['id']!r}: observed calls must be a list")
    expected = case["expected"]
    if case["mode"] == "set":
        ok = set(expected) == set(observed) if not case["allow_extra"] \
            else set(expected).issubset(set(observed))
        reason = ("selected exactly the expected tools" if ok
                  else f"expected set {expected}, observed {observed}")
    elif case["mode"] == "prefix":
        ok = observed[:len(expected)] == expected
        reason = ("chain starts with the expected calls" if ok
                  else f"expected prefix {expected}, observed {observed}")
    else:
        ok = observed == expected if not case["allow_extra"] \
            else observed[:len(expected)] == expected
        reason = ("selected the expected chain in order" if ok
                  else f"expected chain {expected}, observed {observed}")
    return {"id": case["id"], "pass": bool(ok), "reason": reason,
            "expected": expected, "observed": observed, "mode": case["mode"]}


def run_eval(cases, calls, threshold=DEFAULT_THRESHOLD, mode="hermetic",
             model="", cost_usd=None):
    """Score every case, aggregate, and compare the rate to the threshold.

    ``mode="live"`` refuses to report without the model and the cost: a live
    number that cannot say what produced it is not evidence. ``mode="hermetic"``
    scores a recorded transcript and needs neither.
    """
    if not cases:
        raise EvalError("an eval run needs at least one case")
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) \
            or not 0.0 <= float(threshold) <= 1.0:
        raise EvalError(f"threshold must be in [0, 1], got {threshold!r}")
    if mode not in ("hermetic", "live"):
        raise EvalError(f"mode must be 'hermetic' or 'live', got {mode!r}")
    if mode == "live":
        if not isinstance(model, str) or not model.strip():
            raise EvalError("a live eval must report the model that ran it")
        if cost_usd is None:
            raise EvalError("a live eval must report its cost_usd")
    rows = []
    for case in cases:
        if case["id"] not in calls:
            rows.append({"id": case["id"], "pass": False,
                         "reason": "the transcript recorded no call for this case",
                         "expected": case["expected"], "observed": [],
                         "mode": case["mode"]})
            continue
        rows.append(score_case(case, calls[case["id"]]))
    passed = sum(1 for row in rows if row["pass"])
    rate = round(passed / len(rows), 4)
    return {
        "schema": SCHEMA,
        "mode": mode,
        "model": model.strip() if model else "",
        "cost_usd": (round(float(cost_usd), 9)
                     if cost_usd is not None else 0.0),
        "threshold": float(threshold),
        "cases": rows,
        "aggregate": {
            "cases": len(rows),
            "passed": passed,
            "failed": len(rows) - passed,
            "pass_rate": rate,
            "threshold": float(threshold),
            "meets_threshold": bool(rate >= float(threshold)),
        },
    }


def render(result):
    """One line per case plus the aggregate, for a CI log or a receipt."""
    lines = [f"[eval] mode={result['mode']} cases={result['aggregate']['cases']} "
             f"threshold={result['aggregate']['threshold']:.2f}"]
    for row in result["cases"]:
        status_label = "PASS" if row["pass"] else "FAIL"
        lines.append(f"[eval] {row['id']:<24} {status_label}  {row['reason']}")
    agg = result["aggregate"]
    meets_label = "MEETS" if agg["meets_threshold"] else "BELOW"
    lines.append(
        f"[eval] pass_rate={agg['pass_rate']:.4f} ({agg['passed']}/{agg['cases']}) "
        f"threshold={agg['threshold']:.2f} -> {meets_label}"
    )
    return "\n".join(lines)


def default_paths(root=None):
    """The shipped eval set and its recorded transcript."""
    base = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    directory = os.path.join(base, "packs", "agent_eval")
    return {"eval_set": os.path.join(directory, "mcp-selection.pack.json"),
            "transcript": os.path.join(directory, "mcp-selection.recorded.json")}
