"""Answer-lifecycle consistency check for a delivered plotting script (#568).

The defect this closes: an answer delivered a runnable Matplotlib script whose
code contradicted its own prose -- two linear panels titled "Log10 scale",
ticks at powers of ten while the bars sat at exponents, and labels described as
"underneath" that the code anchored inside the bars. Nothing was executed, so a
run-time check could not have caught it either; the contradiction is in the
source.

The check is static and owned by the answer lifecycle: before a candidate is
released as answer text, the plotting settings are derived for the default
state and for every advertised flag state, then compared with the request, the
panel titles and the explanatory prose. Rendering consequences (whether the
library raises, warns or clips; actual pixel visibility) stay explicitly
unverified -- only claims the source can settle are checked.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

#: A fenced code block: triple backticks with an optional language tag.
_FENCE = re.compile(r"^\s*```(?P<lang>[A-Za-z0-9_+-]*)\s*$")

_PY_LANGS = ("", "python", "py", "python3")

_LOG_WORD = re.compile(r"\blog(?:10|arith|\u2081\u2080)?\b", re.IGNORECASE)
_LINEAR_WORD = re.compile(r"\blinear\b", re.IGNORECASE)
_UNDER_WORD = re.compile(r"\b(underneath|below|beneath)\b", re.IGNORECASE)

_SCALE_SETTERS = ("set_xscale", "set_yscale")


@dataclass(frozen=True)
class PlotFinding:
    """One claim the source cannot support, with the values that disagree."""

    check: str
    detail: str
    line: Optional[int] = None

    def as_dict(self) -> Dict[str, object]:
        return {"check": self.check, "detail": self.detail, "line": self.line}


@dataclass
class PlotConsistencyReport:
    script_found: bool = False
    promise_found: bool = False
    findings: List[PlotFinding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings


# ---------------------------------------------------------------- extraction

def extract_scripts(answer: str) -> List[Tuple[str, int]]:
    """Return ``(code, first_line)`` for every Python fenced block in ``answer``."""
    blocks: List[Tuple[str, int]] = []
    lines = (answer or "").splitlines()
    index = 0
    while index < len(lines):
        match = _FENCE.match(lines[index])
        if not match:
            index += 1
            continue
        lang = (match.group("lang") or "").lower()
        start = index + 1
        body: List[str] = []
        index = start
        while index < len(lines) and not _FENCE.match(lines[index]):
            body.append(lines[index])
            index += 1
        if lang in _PY_LANGS and body:
            blocks.append(("\n".join(body), start + 1))
        index += 1
    return blocks


def strip_scripts(answer: str) -> str:
    """``answer`` with its fenced blocks removed (the prose only)."""
    out: List[str] = []
    lines = (answer or "").splitlines()
    index = 0
    while index < len(lines):
        if _FENCE.match(lines[index]):
            index += 1
            while index < len(lines) and not _FENCE.match(lines[index]):
                index += 1
            index += 1
            continue
        out.append(lines[index])
        index += 1
    return "\n".join(out)


def promises_scale_comparison(text: str) -> bool:
    """True when ``text`` promises a linear/log comparison or a toggle."""
    return bool(_LOG_WORD.search(text or "") and _LINEAR_WORD.search(text or ""))


# ---------------------------------------------------------------- collection

@dataclass
class _Scale:
    axes: str
    axis: str
    scale: str
    cond: Dict[str, bool]
    lineno: int


@dataclass
class _Title:
    axes: str
    text: str
    cond: Dict[str, bool]
    lineno: int


class _Collector:
    """Walk a script without running it and record its plotting settings."""

    def __init__(self) -> None:
        self.flags: Dict[str, bool] = {}
        self.axes: set = set()
        self.functions: Dict[str, ast.FunctionDef] = {}
        self.scales: List[_Scale] = []
        self.titles: List[_Title] = []
        self.power_ticks = False
        self.plain_bar_positions: List[str] = []
        #: Names assigned a list comprehension of powers of ten, so a bar
        #: drawn at those positions is not reported against power ticks
        #: (#683 finding 28).
        self.power_positions: set = set()
        self.text_anchors: List[Tuple[int, object, Optional[str]]] = []
        self.walks = 0
        #: Bar positions whose values are known to be plain numbers.
        self.confirmed_plain_bars: List[str] = []

    # -- helpers --

    def _is_power(self, node: ast.AST) -> bool:
        return (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow)
                and isinstance(node.left, ast.Constant)
                and node.left.value == 10)

    def _has_power(self, node: ast.AST) -> bool:
        return any(self._is_power(child) for child in ast.walk(node))

    def _flag_of(self, node: ast.AST,
                 aliases: Dict[str, Tuple[str, str]]) -> Optional[Tuple[str, bool]]:
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            inner = self._flag_of(node.operand, aliases)
            return (inner[0], not inner[1]) if inner else None
        if isinstance(node, ast.Name):
            if node.id in self.flags:
                return node.id, True
            bound = aliases.get(node.id)
            if bound and bound[0] == "flag" and bound[1] in self.flags:
                return bound[1], True
        if isinstance(node, ast.Attribute):
            # #683 finding 29: the standard `args = parser.parse_args()` /
            # `if args.log:` toggle was unresolved, so both branches were
            # collected with identical conditions and a correct toggle
            # produced contradictory findings.
            if node.attr in self.flags:
                return node.attr, True
        return None

    def _bound_axes(self, node: ast.AST,
                    aliases: Dict[str, Tuple[str, str]]) -> Optional[str]:
        if isinstance(node, ast.Name):
            if node.id in self.axes:
                return node.id
            bound = aliases.get(node.id)
            if bound and bound[0] == "axes":
                return bound[1]
        return None

    def _record_axes_assignment(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, (ast.Tuple, ast.List)):
                # ``fig, (ax_a, ax_b) = plt.subplots(...)``: only the nested
                # names are axes; the plain name is the figure.
                inner = [elt for elt in target.elts
                         if isinstance(elt, (ast.Tuple, ast.List))]
                names = [elt.id for group in inner for elt in group.elts
                         if isinstance(elt, ast.Name)]
                if not inner:
                    names = [elt.id for elt in target.elts
                             if isinstance(elt, ast.Name)]
                value = node.value
                produced = (isinstance(value, ast.Call)
                            and isinstance(value.func, ast.Attribute)
                            and isinstance(value.func.value, ast.Name)
                            and value.func.value.id == "plt"
                            and value.func.attr == "subplots")
                if produced:
                    self.axes.update(names)

    def _record_call(self, call: ast.Call, cond: Dict[str, bool],
                     aliases: Dict[str, Tuple[str, str]]) -> None:
        func = call.func
        if isinstance(func, ast.Name) and func.id in self.functions:
            self._inline(func.id, call, cond, aliases)
            return
        if not isinstance(func, ast.Attribute):
            return
        axes = self._bound_axes(func.value, aliases)
        if axes is None:
            return
        if func.attr in _SCALE_SETTERS and call.args:
            first = call.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                self.scales.append(_Scale(
                    axes, "x" if func.attr == "set_xscale" else "y",
                    first.value.lower(), dict(cond), call.lineno))
        elif func.attr == "set_title" and call.args:
            first = call.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                self.titles.append(
                    _Title(axes, first.value, dict(cond), call.lineno))
        elif func.attr == "set_xticks" and call.args:
            if self._has_power(call.args[0]):
                self.power_ticks = True
        elif func.attr == "bar" and call.args:
            # Only a position whose values are known to be plain is evidence
            # of a unit mismatch (#683 finding 28). A name bound to powers of
            # ten is not, and an unresolved name is left alone.
            first = call.args[0]
            if (isinstance(first, ast.Name)
                    and first.id in self.plain_bar_positions
                    and first.id not in self.power_positions):
                self.confirmed_plain_bars.append(first.id)
        elif func.attr == "text":
            value = call.args[1] if len(call.args) > 1 else None
            va = None
            for keyword in call.keywords:
                if keyword.arg == "va" and isinstance(keyword.value, ast.Constant):
                    va = str(keyword.value.value)
            self.text_anchors.append((call.lineno, value, va))

    def _inline(self, name: str, call: ast.Call, cond: Dict[str, bool],
                aliases: Dict[str, Tuple[str, str]]) -> None:
        function = self.functions[name]
        if self.walks > 40:  # recursive or pathological: stop unrolling
            return
        bound: Dict[str, Tuple[str, str]] = {}
        params = [arg.arg for arg in list(function.args.args)
                  + list(function.args.kwonlyargs)]
        for param, value in zip(params, call.args):
            resolved = self._bound_axes(value, aliases)
            if resolved:
                bound[param] = ("axes", resolved)
            else:
                flag = self._flag_of(value, aliases)
                if flag:
                    bound[param] = ("flag", flag[0])
        for keyword in call.keywords:
            flag = self._flag_of(keyword.value, aliases)
            if flag and keyword.arg in params:
                bound[keyword.arg] = ("flag", flag[0])
            if keyword.arg == "title" and isinstance(
                    keyword.value, ast.Constant) and call.args:
                axes = self._bound_axes(call.args[0], aliases)
                if axes and isinstance(keyword.value.value, str):
                    self.titles.append(_Title(
                        axes, keyword.value.value, dict(cond), call.lineno))
        merged = dict(aliases)
        merged.update(bound)
        self.walks += 1
        self.walk(function.body, cond, merged)

    def walk(self, nodes: List[ast.stmt], cond: Dict[str, bool],
             aliases: Dict[str, Tuple[str, str]]) -> None:
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.functions[node.name] = node
                continue
            if isinstance(node, ast.If):
                flag = self._flag_of(node.test, aliases)
                if flag:
                    name, truth = flag
                    body_cond = dict(cond)
                    body_cond[name] = truth
                    else_cond = dict(cond)
                    else_cond[name] = not truth
                    self.walk(node.body, body_cond, aliases)
                    self.walk(node.orelse, else_cond, aliases)
                elif isinstance(node.test, ast.Attribute):
                    # An attribute toggle this collector does not know is an
                    # alternative, not a simultaneous execution: asserting a
                    # contradiction across both branches is exactly the
                    # unsupported finding #683 finding 29 reported.
                    continue
                else:
                    self.walk(node.body, cond, aliases)
                    self.walk(node.orelse, cond, aliases)
                continue
            if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                self.walk(node.body, cond, aliases)
                self.walk(node.orelse, cond, aliases)
                continue
            if isinstance(node, ast.Try):
                self.walk(node.body, cond, aliases)
                for handler in node.handlers:
                    self.walk(handler.body, cond, aliases)
                self.walk(node.orelse, cond, aliases)
                self.walk(node.finalbody, cond, aliases)
                continue
            if isinstance(node, ast.With):
                self.walk(node.body, cond, aliases)
                continue
            if isinstance(node, ast.Assign):
                self._record_axes_assignment(node)
                value = node.value
                if (isinstance(value, ast.ListComp)
                        and isinstance(node.targets[0], ast.Name)):
                    if self._has_power(value):
                        self.power_positions.add(node.targets[0].id)
                    else:
                        # Any comprehension without a power expression yields
                        # values that are not powers of ten.
                        self.plain_bar_positions.append(node.targets[0].id)
                continue
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                self._record_call(node.value, cond, aliases)


def _collect_flags(nodes: List[ast.stmt]) -> Dict[str, bool]:
    """``--flag`` names that argparse declares, with their defaults."""
    flags: Dict[str, bool] = {}
    for node in ast.walk(ast.Module(body=list(nodes), type_ignores=[])):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "add_argument"):
            continue
        names = [arg.value for arg in node.args
                 if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                 and arg.value.startswith("-")]
        if not names:
            continue
        action = None
        dest = None
        for keyword in node.keywords:
            if keyword.arg == "action" and isinstance(keyword.value, ast.Constant):
                action = keyword.value.value
            if keyword.arg == "dest" and isinstance(keyword.value, ast.Constant):
                dest = keyword.value.value
        if action not in ("store_true", "store_false"):
            continue
        long_names = [n for n in names if n.startswith("--")] or names
        name = dest or long_names[0].lstrip("-").replace("-", "_")
        flags[name] = (action == "store_false")
    return flags


# ---------------------------------------------------------------- the check

def _consistent(cond: Dict[str, bool], state: Dict[str, bool]) -> bool:
    return all(state.get(key) == value for key, value in cond.items())


def analyse_script(code: str, *, first_line: int = 1,
                   promise: bool = False, prose: str = "") -> List[PlotFinding]:
    """The static findings for one script, with no execution."""
    if "matplotlib" not in code:
        return []
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:  # a script that cannot parse cannot be checked
        return [PlotFinding(
            "script-parse",
            "the delivered script does not parse ({}), so its plotting claims "
            "cannot be verified".format(exc.msg),
            first_line + (exc.lineno or 1) - 1)]
    collector = _Collector()
    collector.flags = _collect_flags(tree.body)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            collector.functions[node.name] = node
    collector.walk(tree.body, {}, {})

    def line_of(lineno: int) -> int:
        return first_line + lineno - 1

    findings: List[PlotFinding] = []
    flags = collector.flags
    default_state = {name: value for name, value in flags.items()}

    def state_for(name: str, value: bool) -> Dict[str, bool]:
        state = dict(default_state)
        state[name] = value
        return state

    # (1) panel modes vs titles, in the default state and every flag state.
    states = [("the default state", default_state)] + [
        (name, state_for(name, not value)) for name, value in flags.items()]
    for label, state in states:
        for title in collector.titles:
            if not _consistent(title.cond, state):
                continue
            wanted = None
            if _LOG_WORD.search(title.text):
                wanted = "log"
            elif _LINEAR_WORD.search(title.text):
                wanted = "linear"
            if wanted is None:
                continue
            # The effective scale is the last consistent setter per axis, not
            # every setter: an axis initialised linear and later switched to
            # log presents as log, and a "Log scale" title is correct
            # (#683 finding 30). A title that names no dimension is
            # consistent when either axis carries it.
            effective = {"x": ("linear", None), "y": ("linear", None)}
            for scale in collector.scales:
                if (scale.axes != title.axes
                        or not _consistent(scale.cond, state)):
                    continue
                effective[scale.axis] = (scale.scale, scale.lineno)
            if wanted in (value for value, _lineno in effective.values()):
                continue
            derived = ", ".join("{}={}".format(axis, value)
                                for axis, (value, _lineno)
                                in sorted(effective.items()))
            source_line = next((lineno for _value, lineno
                                in effective.values() if lineno), None)
            findings.append(PlotFinding(
                "panel-title",
                'panel `{}` is titled "{}" but its final scales in {} are '
                "{} -- the title and the axis disagree".format(
                    title.axes, title.text, label, derived),
                line_of(source_line or title.lineno)))

    # (2) the promised comparison vs what the default state actually draws.
    if promise and len(collector.axes) >= 2:
        scales: Dict[str, str] = {}
        for axes in collector.axes:
            assigned = [s for s in collector.scales
                        if s.axes == axes and s.axis == "x"
                        and _consistent(s.cond, default_state)]
            scales[axes] = assigned[-1].scale if assigned else "linear"
        if len(set(scales.values())) == 1:
            findings.append(PlotFinding(
                "promised-comparison",
                "the request or the prose promises a linear/log comparison, but "
                "in the default state every panel is {}: {} -- no panel "
                "contrasts the scales".format(
                    next(iter(scales.values())),
                    ", ".join("`{}`".format(name) for name in sorted(scales))),
                None))

    # (3) tick units vs the positions the bars are drawn at.
    if collector.power_ticks:
        for name in collector.confirmed_plain_bars:
            findings.append(PlotFinding(
                "tick-units",
                "ticks are set to powers of ten (`10 ** k`) while the bars are "
                "positioned from `{}`, whose values are not powers of ten -- "
                "the axis units and the bar positions disagree".format(name),
                None))
            break

    # (4) where the prose says the labels sit vs where the code anchors them.
    if _UNDER_WORD.search(prose or ""):
        for lineno, value, va in collector.text_anchors:
            if va == "top":
                continue
            if isinstance(value, ast.Constant) and isinstance(value.value, (int, float)) \
                    and value.value > 0:
                findings.append(PlotFinding(
                    "label-placement",
                    "the prose places the labels underneath the bars, but "
                    "`ax.text(...)` anchors them at y={} inside the bar".format(
                        value.value),
                    line_of(lineno)))
                break
    return findings


def check_answer_plot_consistency(prompt: str, answer: str,
                                  *, prose_override: Optional[str] = None
                                  ) -> PlotConsistencyReport:
    """The lifecycle gate: does the delivered answer keep its plotting claims?"""
    answer = answer or ""
    report = PlotConsistencyReport(
        promise_found=promises_scale_comparison(prompt or ""))
    prose = strip_scripts(answer) if prose_override is None else prose_override
    if not report.promise_found:
        report.promise_found = promises_scale_comparison(prose)
    for code, first_line in extract_scripts(answer):
        if "matplotlib" not in code:
            continue
        report.script_found = True
        report.findings.extend(analyse_script(
            code, first_line=first_line, promise=report.promise_found,
            prose=prose))
    return report


def revision_prompt(original_prompt: str, answer: str,
                    findings: List[PlotFinding]) -> str:
    """Ask for one corrected candidate, naming what disagrees."""
    lines = [
        "The answer below delivers a Python plotting script whose code "
        "contradicts the request, its own panel titles, or its own prose.",
        "",
        "Original request:",
        original_prompt,
        "",
        "Unsupported claims found by static inspection (nothing was executed):",
    ]
    for finding in findings:
        where = " (line {})".format(finding.line) if finding.line else ""
        lines.append("- [{}] {}{}".format(finding.check, finding.detail, where))
    lines.extend([
        "",
        "Return the complete corrected answer: the full script plus prose that "
        "matches what the code actually draws. Do not restate these findings "
        "as fixed unless the code now supports them.",
        "",
        "Candidate answer:",
        answer,
    ])
    return "\n".join(lines)


def withhold_script(answer: str, findings: List[PlotFinding]) -> str:
    """Deliver the explanation without the script that cannot be trusted."""
    kept = strip_scripts(answer).strip()
    reason = "; ".join(finding.detail for finding in findings) or (
        "its plotting claims could not be verified")
    note = ("I withheld the plotting script: it did not survive the "
            "answer-lifecycle consistency check, so this claim could not be "
            "verified -- " + reason + ".")
    return (kept + "\n\n" + note).strip() if kept else note
