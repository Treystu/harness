"""RSI Build 1 - the completion spec as data (plan section 3).

The spec is one frozen JSON document (``packs/completion_spec.json``) that
enumerates every completion bar as an executable check with its bar id, class,
threshold, evidence type and evidence surface. This module loads, validates and
runs it against a recorded census; it never writes the spec, because the spec is
frozen-zone data the loop reads and never writes (plan section 4).

Five classes, exactly as ruled (D5): STATE, RAIL, JUDGMENT, BEHAVIOR, CENSUS.
Bar results are always reported passed-against-full-total. A run in which a whole
class is unexercised is a PARTIAL diagnostic and earns zero exit credit.

The spec is *seeded from* ``harness/jev_completion.py``: the phase-completion
bar keeps that module as its owner (``PHASE_COMPLETE_MIN_SCORE`` and the hard
gate set), and this spec references its result rather than restating its rules.

``p5.*`` element ids are the P5 completion definition decomposed; validation
refuses a spec in which any element maps to no bar.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .errors import HarnessError
from .jev_completion import (
    PHASE_COMPLETE_MIN_SCORE,
    _HARD_GATE_POINTS,
)

SPEC_PATH = "packs/completion_spec.json"

BAR_CLASSES: Tuple[str, ...] = ("STATE", "RAIL", "JUDGMENT", "BEHAVIOR", "CENSUS")

EVIDENCE_CLASSES: Tuple[str, ...] = (
    "merged_fix",
    "measured_result",
    "disposition",
    "operator_hold",
)

# The P5 completion definition (plan premise P5, as amended by the ASTRA3
# record), decomposed so every element can be required to map to a bar id.
P5_ELEMENTS: Dict[str, str] = {
    "p5.inventory.zero_open_obligations_excluding_hold":
        "Zero open obligations on the plan-of-record inventory, excluding rows in "
        "explicit operator hold (counted and named, never worked by the loop).",
    "p5.inventory.issue_rows_counted":
        "Issue rows on the plan of record are counted and reconciled with the API.",
    "p5.inventory.nonissue_rows_counted":
        "Non-issue rows (U-C4, Slice 2, the Wave 5 items) are counted as obligations.",
    "p5.closure.every_closure_carries_evidence_class":
        "Every closure carries one of the four evidence classes.",
    "p5.checks.section_16_5":
        "The P5 plan-of-record section 16.5 register checks are recorded and pass.",
    "p5.census.unification_closed":
        "The unification census is closed: every group reconciled or carrying a filed cure.",
    "p5.plan_of_record.single_home_with_generated_view":
        "docs/jev-roadmap.md is the sole plan of record; #295 is its generated "
        "census/evidence view.",
}

# Frozen-zone paths the loop may never write (plan section 4). Promotion of a
# diff touching any of these is excluded from loop authority and routed to the
# outside seat.
FROZEN_SPEC_PATHS: Tuple[str, ...] = (
    "packs/completion_spec.json",
    "harness/completion_spec.py",
    "harness/jev_completion.py",
    "harness/jev_policy.py",
    "harness/jev_packs.py",
)

_REQUIRED_BAR_FIELDS = (
    "id",
    "class",
    "check",
    "threshold",
    "evidence_type",
    "evidence_surface",
)


def _result(state: str, observed: Any, detail: str) -> Dict[str, Any]:
    return {"state": state, "observed": observed, "detail": detail}


def _not_run(detail: str) -> Dict[str, Any]:
    return _result("not_run", None, detail)


def _dig(census: Dict[str, Any], *path: str) -> Any:
    cur: Any = census
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def _row_label(row: Dict[str, Any]) -> str:
    if "id" in row:
        return str(row["id"])
    if "number" in row:
        return f"#{row['number']}"
    return "?"


# --- STATE -----------------------------------------------------------------

def _check_open_obligations_zero(census: Dict[str, Any], bar: Dict[str, Any]) -> Dict[str, Any]:
    inventory = _dig(census, "inventory")
    if not isinstance(inventory, dict):
        return _not_run("census carries no inventory section")
    if not isinstance(inventory.get("issues"), list) and not isinstance(
            inventory.get("nonissue"), list):
        return _not_run("inventory carries neither issue nor non-issue rows")
    rows: List[Dict[str, Any]] = list(inventory.get("issues") or []) + list(
        inventory.get("nonissue") or [])
    open_obligations = [
        row for row in rows
        if str(row.get("state", "open")).lower() == "open" and not row.get("operator_hold")
    ]
    held = [row for row in rows if row.get("operator_hold")]
    observed = {
        "open": len(open_obligations),
        "open_ids": [_row_label(row) for row in open_obligations],
        "operator_hold": [_row_label(row) for row in held],
    }
    if open_obligations:
        return _result("red", observed,
                       f"{len(open_obligations)} open obligations outside operator hold")
    return _result("green", observed, "zero open obligations outside operator hold")


def _check_issue_rows_reconciled(census: Dict[str, Any], bar: Dict[str, Any]) -> Dict[str, Any]:
    rec = _dig(census, "inventory", "reconciliation", "issues")
    issues = _dig(census, "inventory", "issues")
    if not isinstance(rec, dict) or not isinstance(issues, list):
        return _not_run("census carries no issue reconciliation")
    unexplained = list(rec.get("unexplained") or [])
    api_count = rec.get("api_count")
    register_open = rec.get("register_open")
    closures = rec.get("receipted_closures")
    if api_count is None or register_open is None or closures is None:
        return _not_run("issue reconciliation is missing a count")
    expected = int(register_open) - int(closures)
    observed = {
        "api_count": api_count,
        "register_open": register_open,
        "receipted_closures": closures,
        "list_len": len(issues),
        "unexplained": unexplained,
    }
    if unexplained or int(api_count) != expected or len(issues) != int(api_count):
        return _result("red", observed,
                       f"issue census does not reconcile (api={api_count}, "
                       f"register-closures={expected})")
    return _result("green", observed, "issue census reconciles with receipted closures")


def _check_nonissue_rows_reconciled(census: Dict[str, Any],
                                    bar: Dict[str, Any]) -> Dict[str, Any]:
    rec = _dig(census, "inventory", "reconciliation", "nonissue")
    rows = _dig(census, "inventory", "nonissue")
    if not isinstance(rec, dict) or not isinstance(rows, list):
        return _not_run("census carries no non-issue reconciliation")
    unexplained = list(rec.get("unexplained") or [])
    register_open = rec.get("register_open")
    if register_open is None:
        return _not_run("non-issue reconciliation is missing the register count")
    observed = {"register_open": register_open, "list_len": len(rows),
                "unexplained": unexplained}
    if unexplained or len(rows) != int(register_open):
        return _result("red", observed, "non-issue rows do not reconcile with the register")
    return _result("green", observed, "non-issue rows reconcile with the register")


def _check_closures_carry_evidence_class(census: Dict[str, Any],
                                         bar: Dict[str, Any]) -> Dict[str, Any]:
    closures = _dig(census, "inventory", "closures")
    if not isinstance(closures, dict) or not closures.get("recorded"):
        return _not_run("closure log not recorded in this census")
    items = list(closures.get("items") or [])
    unclassified = [
        _row_label(item) for item in items
        if item.get("evidence_class") not in EVIDENCE_CLASSES
    ]
    observed = {"closures": len(items), "unclassified": unclassified}
    if unclassified:
        return _result("red", observed,
                       "closure without an evidence class: " + ", ".join(unclassified))
    return _result("green", observed, "every closure carries an evidence class")


def _check_register_checks_16_5_pass(census: Dict[str, Any],
                                     bar: Dict[str, Any]) -> Dict[str, Any]:
    block = _dig(census, "checks_16_5")
    if not isinstance(block, dict) or not block.get("recorded"):
        return _not_run("section 16.5 register checks not recorded")
    checks = list(block.get("checks") or [])
    failing = [str(item.get("id")) for item in checks if item.get("state") != "pass"]
    observed = {"checks": len(checks), "failing": failing}
    if not checks:
        return _result("red", observed, "no section 16.5 check is recorded as run")
    if failing:
        return _result("red", observed, "section 16.5 checks failing: " + ", ".join(failing))
    return _result("green", observed, "every section 16.5 check passes")


def _check_open_pulls_zero(census: Dict[str, Any], bar: Dict[str, Any]) -> Dict[str, Any]:
    pulls = _dig(census, "pulls", "open")
    if not isinstance(pulls, list):
        return _not_run("census carries no pull-request read")
    observed = {"open": len(pulls), "ids": [_row_label(row) for row in pulls]}
    if pulls:
        return _result("red", observed,
                       f"{len(pulls)} open pull requests (drafts included)")
    return _result("green", observed, "zero open pull requests")


def _check_unpushed_work_zero(census: Dict[str, Any], bar: Dict[str, Any]) -> Dict[str, Any]:
    trees = _dig(census, "worktrees")
    if not isinstance(trees, dict) or not trees.get("recorded"):
        return _not_run("fleet unpushed-work read not recorded")
    dirty = list(trees.get("dirty") or [])
    observed = {"dirty": dirty}
    if dirty:
        return _result("red", observed, "unpushed work in: " + ", ".join(map(str, dirty)))
    return _result("green", observed, "zero unpushed work across the fleet's clones")


# --- RAIL ------------------------------------------------------------------

def _check_rail_green_or_labelled_interim(census: Dict[str, Any],
                                          bar: Dict[str, Any]) -> Dict[str, Any]:
    rail = _dig(census, "rail")
    if not isinstance(rail, dict):
        return _not_run("census carries no rail state")
    contexts = list(rail.get("contexts") or [])
    if not contexts:
        return _not_run("rail state names no context")
    failing = [str(c.get("name")) for c in contexts if c.get("state") != "success"]
    observed = {
        "head": rail.get("head"),
        "source": rail.get("source"),
        "contexts": len(contexts),
        "failing": failing,
    }
    if not failing:
        return _result("green", observed, "every rail context is success at the head")
    interim = rail.get("interim") or {}
    if interim.get("labelled_local") and interim.get("debt_entry"):
        observed["interim"] = interim
        return _result("green", observed, "LOCAL-labelled interim evidence with a debt entry")
    return _result("red", observed,
                   "rail not green and no labelled interim: " + ", ".join(failing))


def _check_rail_debt_current(census: Dict[str, Any], bar: Dict[str, Any]) -> Dict[str, Any]:
    rail = _dig(census, "rail")
    if not isinstance(rail, dict) or not isinstance(rail.get("debt"), list):
        return _not_run("rail debt list not recorded")
    entries = list(rail["debt"])
    incomplete = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            incomplete.append(index)
            continue
        if not all(str(entry.get(key) or "").strip() for key in ("head", "command", "result")):
            incomplete.append(index)
        elif not entry.get("labelled_local"):
            incomplete.append(index)
    observed = {"entries": len(entries), "incomplete": incomplete}
    if incomplete:
        return _result("red", observed,
                       "rail debt entry missing head/command/result/LOCAL label")
    return _result("green", observed, "rail debt list is empty or fully current")


# --- JUDGMENT --------------------------------------------------------------

def _modal_axis(axes: Dict[str, Any]) -> Optional[float]:
    values: List[float] = []
    for value in axes.values():
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    if not values:
        return None
    counts: Dict[float, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    best = max(counts.values())
    return max(value for value, count in counts.items() if count == best)


def _one_judgment_run(run: Dict[str, Any], threshold: Dict[str, Any]) -> List[str]:
    faults: List[str] = []
    combined = run.get("combined")
    axes = run.get("axes") if isinstance(run.get("axes"), dict) else {}
    try:
        combined_value = float(combined)
    except (TypeError, ValueError):
        return ["combined score missing"]
    if combined_value >= 100.0:
        faults.append("composite of exactly 100 is a red flag")
    combined_min = float(threshold.get("combined_min", 95))
    if combined_value < combined_min:
        faults.append(f"combined {combined_value} < {combined_min}")
    floor = float(threshold.get("axis_floor", 60))
    low = []
    unparsed = []
    for name, value in axes.items():
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            unparsed.append(name)
            continue
        if numeric < floor:
            low.append(name)
    if unparsed:
        faults.append("axis rating not numeric: " + ", ".join(sorted(unparsed)))
    if low:
        faults.append("axis below floor: " + ", ".join(sorted(low)))
    modal = _modal_axis(axes)
    modal_min = float(threshold.get("axis_modal_min", 85))
    if modal is None:
        faults.append("no axis ratings recorded")
    elif modal < modal_min:
        faults.append(f"modal axis {modal} < {modal_min}")
    return faults


def _check_judgment_bar_pass(census: Dict[str, Any], bar: Dict[str, Any]) -> Dict[str, Any]:
    block = _dig(census, "judgment", "artifact_bar")
    if not isinstance(block, dict):
        return _not_run("no house-instrument run recorded")
    runs = list(block.get("runs") or [])
    threshold = bar.get("threshold") or {}
    runs_min = int(threshold.get("runs_min", 2))
    if len(runs) < runs_min:
        return _result("red", {"runs": len(runs)},
                       f"fewer than {runs_min} instrument runs recorded")
    faults = []
    for index, run in enumerate(runs, start=1):
        for fault in _one_judgment_run(run, threshold):
            faults.append(f"run {index}: {fault}")
    observed = {"runs": len(runs),
                "combined": [run.get("combined") for run in runs],
                "axes": [run.get("axes") for run in runs]}
    if faults:
        return _result("red", observed, "; ".join(faults))
    return _result("green", observed, "every instrument run clears the artifact bar")


def _check_probes_axis_judged(census: Dict[str, Any], bar: Dict[str, Any]) -> Dict[str, Any]:
    block = _dig(census, "judgment", "artifact_bar")
    if not isinstance(block, dict):
        return _not_run("no house-instrument run recorded")
    runs = list(block.get("runs") or [])
    if not runs:
        return _not_run("instrument run carries no probe axis")
    states = [run.get("probes") for run in runs]
    observed = {"probes": states}
    if any(state != "proven" for state in states):
        return _result("red", observed, f"planted-probe axis not proven: {states}")
    return _result("green", observed, "planted-probe axis proven on every run")


def _check_phase_bar_pass(census: Dict[str, Any], bar: Dict[str, Any]) -> Dict[str, Any]:
    block = _dig(census, "judgment", "phase_bar")
    if not isinstance(block, dict) or not block.get("recorded"):
        return _not_run("phase-completion bar not recorded")
    phases = block.get("phases") or {}
    if not isinstance(phases, dict) or not phases:
        return _result("red", {"phases": 0}, "phase bar recorded no phase")
    min_score = float(block.get("min_score", PHASE_COMPLETE_MIN_SCORE))
    # The hard-gate set and its weights stay with harness/jev_completion.py; a
    # phase bar whose hard gates were never declared cannot have passed them.
    hard_gates = block.get("hard_gates") or {}
    failing = []
    if not hard_gates:
        failing.append("hard gates not recorded")
    for phase, row in sorted(phases.items()):
        try:
            score = float(row.get("score"))
        except (TypeError, ValueError):
            failing.append(f"{phase}: no score")
            continue
        if score < min_score or not row.get("bar_pass"):
            failing.append(f"{phase}: {score}")
    observed = {"phases": sorted(phases), "min_score": min_score,
                "hard_gate_names": sorted(hard_gates), "failing": failing}
    if failing:
        return _result("red", observed, "phases below the bar: " + ", ".join(failing))
    return _result("green", observed, f"every phase clears the {min_score} bar")


def _check_epoch_change_set_judged(census: Dict[str, Any], bar: Dict[str, Any]) -> Dict[str, Any]:
    block = _dig(census, "judgment", "change_set")
    if not isinstance(block, dict):
        return _not_run("epoch change-set judgment not recorded")
    if not block.get("present"):
        return _result("green", {"present": False},
                       "no change set in this epoch; nothing to judge")
    if not block.get("judged"):
        return _result("red", block, "epoch change set present but unjudged")
    return _result("green", block, "epoch change set judged by the house instrument")


# --- BEHAVIOR --------------------------------------------------------------

def _check_surface_passed(census: Dict[str, Any], bar: Dict[str, Any]) -> Dict[str, Any]:
    key = bar.get("surface_key")
    surfaces = _dig(census, "behavior", "surfaces")
    if not key:
        return _not_run("bar names no surface")
    if not isinstance(surfaces, dict) or key not in surfaces:
        return _not_run(f"surface {key!r} not driven in this census")
    row = surfaces[key] or {}
    state = str(row.get("state") or "not_run")
    observed = {"surface": key, "state": state, "note": row.get("note")}
    if state == "pass":
        return _result("green", observed, f"{key} surface passes its scripted drive")
    if state == "not_run":
        return _not_run(f"{key} surface was not driven")
    return _result("red", observed, f"{key} surface drive failed")


def _check_never_defer_proven(census: Dict[str, Any], bar: Dict[str, Any]) -> Dict[str, Any]:
    block = _dig(census, "behavior", "never_defer")
    if not isinstance(block, dict):
        return _not_run("no provider-failure drive recorded")
    state = str(block.get("state") or "not_run")
    observed = {"state": state, "note": block.get("note")}
    if state == "pass":
        return _result("green", observed,
                       "provider failure mid-run fails over and completes")
    if state == "not_run":
        return _not_run("provider-failure drive not run")
    return _result("red", observed, "provider-failure drive did not fail over and complete")


# --- CENSUS ----------------------------------------------------------------

def _check_unification_closed(census: Dict[str, Any], bar: Dict[str, Any]) -> Dict[str, Any]:
    block = _dig(census, "census", "unification")
    if not isinstance(block, dict):
        return _not_run("census carries no unification state")
    closed = bool(block.get("closed"))
    observed = {"closed": closed, "note": block.get("note")}
    if closed:
        return _result("green", observed, "unification census closed")
    return _result("red", observed, "unification census open")


def _check_self_claims_verified(census: Dict[str, Any], bar: Dict[str, Any]) -> Dict[str, Any]:
    block = _dig(census, "census", "self_claims")
    if not isinstance(block, dict) or not block.get("recorded"):
        return _not_run("self-claims panel run not recorded")
    try:
        total = int(block.get("total"))
        verified = int(block.get("verified"))
    except (TypeError, ValueError):
        return _not_run("self-claims counts missing")
    observed = {"total": total, "verified": verified}
    if total < 1:
        return _result("red", observed, "self-claims set is empty")
    if verified < total:
        return _result("red", observed, f"{verified} of {total} self-claims verified")
    return _result("green", observed, "every self-claim is verified")


def _check_plan_of_record_single_home(census: Dict[str, Any],
                                      bar: Dict[str, Any]) -> Dict[str, Any]:
    block = _dig(census, "plan_of_record")
    if not isinstance(block, dict):
        return _not_run("census carries no plan-of-record state")
    observed = {
        "canonical": block.get("canonical"),
        "census_view": block.get("census_view"),
        "single_home": block.get("single_home"),
        "generated": block.get("generated"),
    }
    threshold = bar.get("threshold") or {}
    if block.get("canonical") != threshold.get("canonical"):
        return _result("red", observed,
                       f"canonical plan of record is not {threshold.get('canonical')!r}")
    if block.get("census_view") != threshold.get("census_view"):
        return _result("red", observed,
                       f"census view is not {threshold.get('census_view')!r}")
    if not block.get("single_home") or not block.get("generated"):
        return _result("red", observed,
                       "plan of record is not a single generated-view home")
    return _result("green", observed, "one plan of record with a generated census view")


CHECKS = {
    "open_obligations_zero": _check_open_obligations_zero,
    "issue_rows_reconciled": _check_issue_rows_reconciled,
    "nonissue_rows_reconciled": _check_nonissue_rows_reconciled,
    "closures_carry_evidence_class": _check_closures_carry_evidence_class,
    "register_checks_16_5_pass": _check_register_checks_16_5_pass,
    "open_pulls_zero": _check_open_pulls_zero,
    "unpushed_work_zero": _check_unpushed_work_zero,
    "rail_green_or_labelled_interim": _check_rail_green_or_labelled_interim,
    "rail_debt_current": _check_rail_debt_current,
    "judgment_bar_pass": _check_judgment_bar_pass,
    "probes_axis_judged": _check_probes_axis_judged,
    "phase_bar_pass": _check_phase_bar_pass,
    "epoch_change_set_judged": _check_epoch_change_set_judged,
    "surface_passed": _check_surface_passed,
    "never_defer_proven": _check_never_defer_proven,
    "unification_closed": _check_unification_closed,
    "self_claims_verified": _check_self_claims_verified,
    "plan_of_record_single_home": _check_plan_of_record_single_home,
}

# Seeded from the existing bar owner: if its hard-gate weights stop summing to
# 100, a phase can never clear the mechanical bar and this spec's phase bar
# would silently measure the wrong thing.
assert sum(_HARD_GATE_POINTS.values()) == 100, "jev_completion hard-gate points drifted"


def validate_spec(spec: Any) -> Dict[str, Any]:
    """Validate a spec document; refuse the whole spec on the first defect."""
    if not isinstance(spec, dict):
        raise HarnessError("completion spec must be a JSON object")
    if not str(spec.get("id") or "").strip():
        raise HarnessError("completion spec requires an id")
    if spec.get("frozen") is not True:
        raise HarnessError(
            "completion spec must declare frozen=true; a writable spec is refused")
    bars = spec.get("bars")
    if not isinstance(bars, list) or not bars:
        raise HarnessError("completion spec requires a non-empty bars list")
    seen: Dict[str, str] = {}
    covered: Dict[str, List[str]] = {element: [] for element in P5_ELEMENTS}
    for index, bar in enumerate(bars):
        if not isinstance(bar, dict):
            raise HarnessError(f"bar {index} is not an object")
        missing = [field for field in _REQUIRED_BAR_FIELDS if not bar.get(field)]
        if missing:
            raise HarnessError(f"bar {index} is missing {', '.join(missing)}")
        bar_id = str(bar["id"])
        if bar_id in seen:
            raise HarnessError(f"duplicate bar id {bar_id}")
        seen[bar_id] = str(bar["class"])
        if bar["class"] not in BAR_CLASSES:
            raise HarnessError(f"bar {bar_id} names unknown class {bar['class']!r}")
        if bar["check"] not in CHECKS:
            raise HarnessError(f"bar {bar_id} names unknown check {bar['check']!r}")
        if not isinstance(bar["threshold"], dict) or not bar["threshold"]:
            raise HarnessError(f"bar {bar_id} requires a non-empty threshold")
        if bar["check"] == "surface_passed" and not bar.get("surface_key"):
            raise HarnessError(f"bar {bar_id} is a surface check without surface_key")
        element = bar.get("p5_element")
        if element is not None:
            if element not in P5_ELEMENTS:
                raise HarnessError(f"bar {bar_id} names unknown P5 element {element!r}")
            covered[element].append(bar_id)
    uncovered = sorted(element for element, ids in covered.items() if not ids)
    if uncovered:
        raise HarnessError("P5 elements with no bar: " + ", ".join(uncovered))
    return spec


def load_spec(repo_root: str = ".", path: Optional[str] = None) -> Dict[str, Any]:
    """Read and validate the frozen spec. Never writes anything."""
    root = Path(repo_root)
    rel = path or SPEC_PATH
    full = Path(rel) if Path(rel).is_absolute() else root / rel
    try:
        text = full.read_text(encoding="utf-8")
    except OSError as exc:
        raise HarnessError(f"completion spec unreadable at {full}: {exc}") from exc
    try:
        spec = json.loads(text)
    except ValueError as exc:
        raise HarnessError(f"completion spec is not valid JSON: {exc}") from exc
    return validate_spec(spec)


def load_census(path: str) -> Dict[str, Any]:
    full = Path(path)
    try:
        text = full.read_text(encoding="utf-8")
    except OSError as exc:
        raise HarnessError(f"census unreadable at {full}: {exc}") from exc
    try:
        census = json.loads(text)
    except ValueError as exc:
        raise HarnessError(f"census is not valid JSON: {exc}") from exc
    if not isinstance(census, dict):
        raise HarnessError("census must be a JSON object")
    return census


def run_spec(spec: Dict[str, Any], census: Dict[str, Any]) -> Dict[str, Any]:
    """Run every bar against one recorded census. Pure: no writes, no network."""
    classes: Dict[str, Dict[str, Any]] = {
        name: {"state": "green", "passed": 0, "total": 0, "bars": [],
               "unrun": []}
        for name in BAR_CLASSES
    }
    bar_rows: List[Dict[str, Any]] = []
    for bar in spec["bars"]:
        check = CHECKS[bar["check"]]
        outcome = check(census, bar)
        state = str(outcome.get("state") or "red")
        bar_rows.append({
            "id": bar["id"],
            "class": bar["class"],
            "check": bar["check"],
            "state": state,
            "observed": outcome.get("observed"),
            "detail": outcome.get("detail"),
            "threshold": bar.get("threshold"),
            "evidence_type": bar.get("evidence_type"),
            "evidence_surface": bar.get("evidence_surface"),
            "p5_element": bar.get("p5_element"),
        })
        bucket = classes[bar["class"]]
        bucket["total"] += 1
        bucket["bars"].append(bar["id"])
        if state == "green":
            bucket["passed"] += 1
        elif state == "not_run":
            bucket["unrun"].append(bar["id"])
    for bucket in classes.values():
        bucket["state"] = ("green" if bucket["total"] and
                           bucket["passed"] == bucket["total"] else "red")
    green = [row["id"] for row in bar_rows if row["state"] == "green"]
    red = [row["id"] for row in bar_rows if row["state"] == "red"]
    unrun = [row["id"] for row in bar_rows if row["state"] == "not_run"]
    classes_run = [name for name in BAR_CLASSES if classes[name]["total"]]
    classes_unrun = [name for name in BAR_CLASSES if not classes[name]["total"]]
    # A class is unexercised when it has no bar at all, or every one of its bars
    # is not-run. That alone makes the run a PARTIAL diagnostic (D5): zero credit.
    partially_run = [name for name in BAR_CLASSES
                     if classes[name]["total"] and
                     len(classes[name]["unrun"]) == classes[name]["total"]]
    full_run = not partially_run and not classes_unrun
    verdict = "green" if not red and not unrun and full_run else "red"
    credit = 1 if (verdict == "green" and full_run) else 0
    element_coverage: Dict[str, List[str]] = {element: [] for element in P5_ELEMENTS}
    for row in bar_rows:
        element = row.get("p5_element")
        if element:
            element_coverage[element].append(row["id"])
    return {
        "spec_id": spec.get("id"),
        "spec_version": spec.get("version"),
        "as_of": census.get("as_of"),
        "classes": classes,
        "bars": bar_rows,
        "element_coverage": element_coverage,
        "summary": {
            "label": "FULL" if full_run else "PARTIAL",
            "verdict": verdict,
            "passed": len(green),
            "total": len(bar_rows),
            "credit": credit,
            "classes_run": classes_run,
            "partial_classes": partially_run + classes_unrun,
            "classes_unrun": classes_unrun,
            "red_bars": red,
            "unrun_bars": unrun,
        },
    }


def run_spec_file(repo_root: str = ".", census_path: str = "",
                  spec_path: Optional[str] = None) -> Dict[str, Any]:
    """Load the spec and one recorded census, run the spec, return the board."""
    if not str(census_path or "").strip():
        raise HarnessError("completion-spec requires a census path")
    spec = load_spec(repo_root, spec_path)
    census = load_census(census_path)
    return run_spec(spec, census)


def frozen_paths_touched(paths: List[str]) -> List[str]:
    """Frozen-zone paths a diff touches; any hit blocks loop promotion (section 4)."""
    normalised = {str(path).replace("\\", "/").lstrip("./") for path in paths}
    return sorted(path for path in FROZEN_SPEC_PATHS if path in normalised)
