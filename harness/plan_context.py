"""Context intake and stage selection owner: arguments, brief assembly, recondense decision, wanted stages.

Owner split per #308: this module owns how a goal becomes a bounded,
evidence-backed brief, when that brief must be recondensed, and which stages
a run asks for -- the recondense evidence is what drives stage selection, so
the two live together. It reads files through a caller-supplied reader; it
never spends, dispatches or judges sufficiency."""
import json
import os
from typing import Any, Dict, List, Optional, Sequence

from .brief import (build_brief, estimate_brief_tokens, freshness_report, render_brief, validate_brief)
from .errors import HarnessError
from .osal import read_text
from .token_budget import budget_from_settings


from .plan_contracts import (HOURGLASS_DEFAULT_STAGES, STAGE_BYPASS_REASONS, STAGE_CONTEXT, STAGE_DENIED_BYPASS, STAGE_ORDER, STAGE_PLANNING)


_WINDOW_SEARCH_FLOOR = 256

def stage_selection_from_settings(settings, *, default=None) -> List[str]:
    """The configured stage selection (``HARNESS_HOURGLASS_STAGES``).

    The default keeps every stage selected: the hourglass is the product's
    default posture, and compatibility requires it to stay on. Validation of
    the names themselves belongs to :func:`resolve_stages` -- config only
    decides what an operator asks for, so an unknown name is refused where
    the ladder is resolved rather than silently dropped here.
    """
    raw = getattr(settings, "hourglass_stages", None)
    if raw in (None, "", []):
        raw = default
    if raw in (None, "", []):
        return list(HOURGLASS_DEFAULT_STAGES)
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",") if part.strip()]
    return list(raw)

def tree_reader(root):
    """Read a run's files relative to the tree that run edits.

    An agent lane's candidate files are relative to ITS root, not to the
    process CWD, so building the intake brief with the default reader would
    either miss the file or -- worse -- silently read a same-named file from
    wherever the process happens to be. Reading goes through ``osal`` (the
    ONE owner of evidence bytes) so the sha256 a pack pins matches the bytes
    on disk on every platform.

    An absolute path is left alone: a caller that names one means it.
    """
    base = str(root)

    def read(path):
        name = path if os.path.isabs(str(path)) else os.path.join(base,
                                                                str(path))
        return read_text(name)

    return read

def compose_arguments(settings, *, goal, files, root=None,
                      reader=None, stages=None, brief=None,
                      token_budget=None,
                      max_input_tokens: Optional[int] = None,
                      max_output_tokens: Optional[int] = None,
                      jev_policy=None) -> Dict[str, Any]:
    """Everything ``compose_plan`` needs to compose one run (HV-2-use / HV-6).

    ONE owner for *how a lane composes*, so the CLI, MCP and agent lanes
    cannot drift apart on what a composed run is:

    * the allowance from ``budget_from_settings`` or explicit overrides;
    * the stage subset from ``stage_selection_from_settings`` or caller overrides;
    * when supplied or ``context`` is selected, the intake brief pack.
    """
    if stages is not None:
        if isinstance(stages, str):
            stage_candidates = [s.strip() for s in stages.split(",") if s.strip()]
        else:
            stage_candidates = list(stages)
        resolved = resolve_stages(stage_candidates)
        stages_subset = list(resolved["stages"])
    else:
        stages_subset = stage_selection_from_settings(settings)

    if reader is None and root is not None:
        reader = tree_reader(root)

    if token_budget is not None:
        tb = token_budget
    elif settings is not None:
        tb = budget_from_settings(settings, max_input_tokens=max_input_tokens,
                                 max_output_tokens=max_output_tokens)
    else:
        tb = None

    arguments: Dict[str, Any] = {
        "token_budget": tb,
        "stages": stages_subset,
        "reader": reader,
    }

    brief_pack = None
    if brief is not None:
        if isinstance(brief, str):
            if os.path.isfile(brief):
                with open(brief, encoding="utf-8") as f:
                    brief_pack = json.load(f)
            else:
                try:
                    brief_pack = json.loads(brief)
                except Exception:
                    brief_pack = None
        elif isinstance(brief, dict):
            brief_pack = brief

    if brief_pack is not None:
        arguments["brief"] = brief_pack
        arguments["brief_tokens"] = estimate_brief_tokens(brief_pack)
        arguments["supplied_brief"] = True
    elif STAGE_CONTEXT in stages_subset:
        intake = intake_brief(goal, files, reader=reader, jev_policy=jev_policy)
        arguments["brief"] = intake["brief"]
        arguments["brief_tokens"] = intake["tokens"]
        arguments["supplied_brief"] = True
        if intake.get("judgment"):
            arguments["context_judgment"] = intake["judgment"]
    return arguments

def intake_brief(goal, files, *, reader=None, jev_policy=None,
                 site="hourglass-intake") -> Dict[str, Any]:
    """The ``context`` stage's artifact for a composed plan run (HV-2-use).

    ONE owner for "the brief a plan run starts from", so no lane invents its
    own shape, its own reader, or its own token number:

    * the pack comes from :func:`harness.brief.build_brief`, the same owner
      the planning ladder curates through -- there is no second brief
      artifact;
    * the size is MEASURED with ``estimate_brief_tokens`` over the bytes the
      pack actually ships, because that number is what caps every later
      stage (``compose_plan(brief_tokens=...)``); and
    * the grounding lint runs here, through ``validate_brief``, so an
      ungrounded pack is visible at the moment it is built.

    ``issues`` are returned rather than raised: a caller decides whether an
    imperfect brief should stop the run, and the fact belongs on the
    envelope either way. An empty list means the pack passed the lint.

    A candidate the run cannot read is **excluded, not fatal**. A plan lane is
    allowed to name a file that does not exist yet -- a goal whose first node
    creates it is an ordinary goal -- and ``build_brief`` refuses to invent
    content for a path it cannot read, so the two cannot simply be handed to
    each other. The exclusion goes through the pack's own vocabulary for it
    (``scope.excluded``, and therefore ``coverage``), so an unreadable
    candidate stays visible instead of being dropped on the floor, and the
    returned ``excluded`` list names them for the caller and the ledger.

    A brief over no readable source is still a brief: it is simply not
    *evidence*, which is why the composition refuses its bypass rather than
    treating an empty pack as a fresh one.
    """
    probe = reader or read_text
    usable: List[str] = []
    excluded: List[str] = []
    for path in list(files or []):
        try:
            probe(path)
        except OSError:
            excluded.append(path)
        else:
            usable.append(path)
    pack = build_brief(goal, usable, reader=reader, scope=excluded)
    judgment = None
    if jev_policy is not None and hasattr(jev_policy, "evaluate_hourglass_stage"):
        state = {
            "request": goal,
            "goal": goal,
            "sources": usable,
            "omitted": excluded,
            "brief_render": render_brief(pack),
        }
        try:
            eval_res = jev_policy.evaluate_hourglass_stage(
                "context_intake", state, site=site)
            if isinstance(eval_res, tuple) and len(eval_res) >= 2:
                _result, structural = eval_res[0], eval_res[1]
            else:
                _result, structural = None, getattr(eval_res, "structural", {}) or {}
            from .jev_packs import HOURGLASS_STAGE_DIMENSIONS
            declared = HOURGLASS_STAGE_DIMENSIONS["context_intake"]["signals"]
            signals = {name: (structural or {}).get(name) for name in declared
                       if (structural or {}).get(name) is not None}
            judgment = {
                "dimension": "context_intake",
                "signals": signals,
                "native": bool((structural or {}).get("native")),
            }
        except (HarnessError, TypeError, ValueError):
            judgment = {"dimension": "context_intake", "signals": {}, "native": False}
    return {
        "brief": pack,
        "tokens": estimate_brief_tokens(pack),
        "issues": list(validate_brief(pack, reader=reader) or []),
        "excluded": excluded,
        "judgment": judgment,
    }

RECONDENSE_GATE_FAILURE = "gate_failure"

RECONDENSE_PIN_DRIFT = "pin_drift"

RECONDENSE_EXECUTED_OVERLAP = "executed_overlap"

RECONDENSE_TRIGGERS = (RECONDENSE_GATE_FAILURE, RECONDENSE_PIN_DRIFT,
                       RECONDENSE_EXECUTED_OVERLAP)

RECONDENSE_REASONS = {
    RECONDENSE_GATE_FAILURE: ("a stage gate failed, so the green-tree basis "
                              "the plan was written against is void"),
    RECONDENSE_PIN_DRIFT: "a cited source no longer matches its pin",
    RECONDENSE_EXECUTED_OVERLAP: ("an executed node wrote a path the brief "
                                  "describes"),
}

def _brief_path(value):
    """One comparable path: separators normalized, no leading ``./``.

    Deliberately not a filesystem operation. This only decides whether two
    names a brief and an executed node both report are the same path, and it
    refuses to guess about case or symlinks rather than silently matching on
    one platform and missing on the other -- a false "no overlap" is a stale
    brief nobody notices, so the rule stays exact and is stated here.
    """
    if not isinstance(value, str):
        return None
    text = value.strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text or None

def _recondense_failures(gate_failures):
    """The stage gates that failed, refusing a bare string.

    A string here would silently iterate into characters and count as one
    failure per letter, which is the same class of mistake ``resolve_stages``
    already refuses for a declared-stage value.
    """
    if gate_failures is None:
        return []
    if isinstance(gate_failures, str):
        raise HarnessError(
            "gate_failures must be a sequence of gate names, not a string: "
            "{0!r}".format(gate_failures))
    return [f for f in gate_failures if f]

def brief_covered_paths(pack) -> List[str]:
    """Every path a brief describes, read from its own declared shape.

    A v2 pack names its evidence in ``grounding.sources[].path`` and its
    scope in ``scope.included``. Both are read; nothing is inferred from
    prose, because an overlap the brief never declared is not one this owner
    can honestly claim to have found.
    """
    if not isinstance(pack, dict):
        return []
    candidates = []
    for source in (pack.get("grounding") or {}).get("sources") or []:
        if isinstance(source, dict):
            candidates.append(source.get("path"))
    scope = pack.get("scope")
    if isinstance(scope, dict):
        candidates.extend(scope.get("included") or [])
    covered: List[str] = []
    for value in candidates:
        path = _brief_path(value)
        if path and path not in covered:
            covered.append(path)
    return covered

def recondense_decision(*, brief, freshness=None, touched_paths=(),
                        gate_failures=(), reader=None) -> Dict[str, Any]:
    """Must the brief be rebuilt before the run continues? Code owns the call.

    Returns the decision, the highest-precedence ``trigger``, *every* reason
    that applies, and the evidence behind each, so a refresh is never a bare
    boolean: a caller is expected to report why it paid to re-condense.

    ``freshness`` lets a caller that already measured the brief (for instance
    to decide a bypass once) reuse that report instead of re-reading the
    tree; omitted, it is measured here. ``touched_paths`` is what executed
    nodes actually wrote, and ``gate_failures`` the gates that failed -- both
    are supplied by a caller that ran a stage, which is why this owner cannot
    discover them itself.
    """
    if freshness is None:
        freshness = freshness_report(brief, reader=reader)
    failures = _recondense_failures(gate_failures)
    triggers: List[str] = []
    details: Dict[str, Any] = {}
    if failures:
        triggers.append(RECONDENSE_GATE_FAILURE)
        details[RECONDENSE_GATE_FAILURE] = {
            "gates": [str(f) for f in failures]}
    if not freshness.get("fresh"):
        triggers.append(RECONDENSE_PIN_DRIFT)
        details[RECONDENSE_PIN_DRIFT] = {
            "checked": freshness.get("checked"),
            "stale": [s.get("id") for s in freshness.get("stale") or []
                      if isinstance(s, dict)],
            "missing": [s.get("id") for s in freshness.get("missing") or []
                        if isinstance(s, dict)],
            "reasons": list(freshness.get("reasons") or []),
        }
    touched = {_brief_path(value) for value in (touched_paths or ())}
    overlap = sorted(set(brief_covered_paths(brief))
                     & {p for p in touched if p})
    if overlap:
        triggers.append(RECONDENSE_EXECUTED_OVERLAP)
        details[RECONDENSE_EXECUTED_OVERLAP] = {"paths": overlap}
    trigger = triggers[0] if triggers else None
    return {
        "refresh": trigger is not None,
        "trigger": trigger,
        "triggers": triggers,
        "reasons": [RECONDENSE_REASONS[t] for t in triggers],
        "details": details,
    }

def resolve_stages(declared: Optional[Sequence[str]] = None, *,
                   supplied_brief: bool = False,
                   supplied_plan: bool = False,
                   brief: Optional[Dict[str, Any]] = None,
                   reader=None,
                   touched_paths=None,
                   gate_failures=None,
                   freshness=None,
                   ) -> Dict[str, Any]:
    """Select the stages that will actually run, in pipeline order.

    ``declared`` is the operator's (or config's) subset of ``STAGE_ORDER``;
    ``None`` keeps the Hourglass default of every stage. Order is the
    pipeline's, not the caller's -- a caller may drop a stage, never reorder
    one into a shape the lanes do not support. An unknown name, a duplicate,
    and a bare string that is really a config value are each refused rather
    than dropped.

    A supplied brief or plan bypasses the stage that would have produced it
    (see ``STAGE_BYPASS_REASONS``), which is how a caller reuses upstream
    work without paying for intake or decomposition twice. The bypass is
    returned, not hidden: a stage that did not run is visible evidence.

    A bypass backed by an actual brief *pack* is stronger evidence than the
    bare ``supplied_brief`` flag, so it is checked: while the pack is fresh
    the bypass stands, and once it has drifted the bypass is denied, the
    stage runs, and the refusal is reported under ``denied``.

    ``touched_paths``/``gate_failures``/``freshness`` (GAP-recondense) are
    the evidence a *composed* run has that a pin check cannot see. Supplying
    any of them routes the bypass decision through
    :func:`recondense_decision` -- the ONE owner of the trigger vocabulary --
    and returns its decision under ``recondense``. Supplying none of them
    keeps this function's historical behaviour exactly: a tri-state sentinel,
    where ``touched_paths=None`` means "no stage ran, nothing to report" and
    ``touched_paths=()`` means "a stage ran and wrote nothing".
    """
    if declared is None:
        wanted = list(HOURGLASS_DEFAULT_STAGES)
    else:
        if isinstance(declared, str):
            raise HarnessError(
                "declared stages must be a sequence of stage names, not a "
                "string: {0!r}".format(declared))
        wanted = []
        for name in declared:
            stage = str(name or "").strip().lower()
            if not stage:
                raise HarnessError("declared stage names cannot be blank")
            if stage not in STAGE_ORDER:
                raise HarnessError(
                    "unknown stage {0!r}; the composable stages are {1}"
                    .format(stage, ", ".join(STAGE_ORDER)))
            if stage in wanted:
                raise HarnessError(
                    "stage {0!r} is declared twice; each stage composes at "
                    "most once per run".format(stage))
            wanted.append(stage)

    bypassed: Dict[str, str] = {}
    denied: Dict[str, str] = {}
    decision: Optional[Dict[str, Any]] = None
    # Tri-state: None means no stage has run, so there is no decision to make.
    stage_evidence = (touched_paths is not None or freshness is not None
                      or bool(_recondense_failures(gate_failures)))
    if (supplied_brief or brief is not None) and STAGE_CONTEXT in wanted:
        if brief is None:
            bypassed[STAGE_CONTEXT] = STAGE_BYPASS_REASONS[STAGE_CONTEXT]
        else:
            if stage_evidence:
                decision = recondense_decision(
                    brief=brief, freshness=freshness, reader=reader,
                    touched_paths=touched_paths or (),
                    gate_failures=gate_failures or ())
                drifted = bool(decision["refresh"])
            else:
                drifted = not freshness_report(brief, reader=reader).get("fresh")
            if not drifted:
                bypassed[STAGE_CONTEXT] = STAGE_BYPASS_REASONS[STAGE_CONTEXT]
            else:
                reason = STAGE_DENIED_BYPASS[STAGE_CONTEXT]
                if decision is not None and decision.get("trigger"):
                    # The refusal names its trigger, so a reader can tell a
                    # re-condense paid for by a failed gate from one paid for
                    # by a drifted pin without diffing the tree.
                    reason = "{0} (trigger: {1})".format(
                        reason, decision["trigger"])
                denied[STAGE_CONTEXT] = reason
    if supplied_plan and STAGE_PLANNING in wanted:
        bypassed[STAGE_PLANNING] = STAGE_BYPASS_REASONS[STAGE_PLANNING]

    # A *denied* bypass is not a skip: it is the reason the stage runs. Only a
    # granted bypass removes a stage from the run.
    stages = [s for s in STAGE_ORDER if s in wanted and s not in bypassed]
    resolved = {"stages": stages, "bypassed": bypassed, "denied": denied,
                "declared": list(wanted)}
    if decision is not None:
        resolved["recondense"] = decision
    return resolved
