"""The distinguishing checks behind ``docs/audit-triage.md`` (issue #290).

Local audit and test failures on a fresh machine are usually environment, not
code -- missing ``python`` on PATH, no ``ruff`` for this interpreter, a key in
the ambient environment that un-skips a live check, a stale D12 baseline -- and
they present *identically* to real defects. The runbook says what to do; this
module is the part that can be run, so "the distinguishing check" is a command
with a verdict instead of advice an operator has to re-derive:

    python -m harness.triage              # every check, human readable
    python -m harness.triage --check ruff # one check
    python -m harness.triage --json       # machine readable

Each probe answers one question with ``ok`` / ``env-broken`` / ``code-broken``
and carries the *expected* result in both worlds, so the runbook's promise
("expected output in both worlds") is testable rather than prose.

The probes are pure over an environment mapping and injected resolvers, so the
tests can exercise every verdict without touching the operator's machine.
"""
import argparse
import json
import os
import sys

#: Verdicts a probe may return.
VERDICTS = ("ok", "env-broken", "code-broken", "unknown")

#: The environment R13 must not leak into its suite child. Kept here so the
#: runbook can name it, and cross-checked against ``audits/self/audit.py`` by
#: ``tests/test_triage_runbook.py`` -- a second copy that silently drifts is
#: worse than no copy.
HERMETIC_ENV_DROP = (
    "HARNESS_USE_FREE",
    "HARNESS_ALLOW_ESCALATION",
    "HARNESS_MAX_COST",
    "HARNESS_TASK_MAX_COST",
    "HARNESS_MIN_CONFIDENCE",
    "HARNESS_JEV_KEY",
    "TYPESAFE_API_KEY",
    "JEV_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENROUTER_API_KEY_FILE",
)

#: Ambient variables that make a local run different from the CI run even
#: though both "pass", because they change which path a test takes.
ROUTING_ENV = ("HARNESS_USE_FREE", "HARNESS_ALLOW_ESCALATION", "HARNESS_MAX_COST",
               "HARNESS_TASK_MAX_COST", "HARNESS_MIN_CONFIDENCE")


def _result(check, verdict, detail, env_broken, code_broken):
    assert verdict in VERDICTS
    return {"check": check, "verdict": verdict, "detail": detail,
            "expected": {"env-broken": env_broken, "code-broken": code_broken}}


def probe_python(env=None, which=None, resolve=None):
    """Bare-``python`` gate failures (#278's signature).

    Gates used to shell out to a bare ``python``; where the alias is absent the
    gate fails for every task identically. The cure resolves an interpreter
    (``HARNESS_PYTHON``, then the running executable, then a PATH name), so the
    check is: does the resolver find one, and is the bare alias the thing that
    is missing?
    """
    env = os.environ if env is None else env
    if resolve is None:
        from . import tools as _tools
        resolve = _tools.resolve_python
    if which is None:
        from . import osal as _osal
        which = _osal.which
    try:
        resolved = resolve()
    except Exception as exc:  # noqa: BLE001 - any resolver failure is the finding
        return _result(
            "python", "env-broken",
            f"no interpreter resolved ({type(exc).__name__}: {exc}); every gate "
            f"that shells out to python fails identically",
            "resolver raises; install Python or set HARNESS_PYTHON",
            "resolver works, so a resolution failure is a defect in tools.resolve_python")
    alias = which("python") or (env or {}).get("HARNESS_PYTHON")
    if not alias:
        return _result(
            "python", "env-broken",
            f"resolved {resolved!r} but no `python` on PATH; gates that bypass "
            f"the resolver fail here and pass in CI",
            "`which python` is empty (alias missing) while tools.resolve_python() succeeds",
            "`which python` present and gates still failing -> the gate bypassed "
            "tools.resolve_gate_argv")
    return _result("python", "ok", f"resolved {resolved!r}; bare alias present",
                   "alias missing", "alias present and gates still fail")


def probe_ruff(env=None, ruff_argv=None):
    """S5's signature: ruff not resolvable for this interpreter.

    The decisive check is the strict resolution: it raises one named error when
    neither a binary nor the module is available. If it resolves and S5 still
    fails, the failure is a real lint finding.
    """
    env = os.environ if env is None else env
    if ruff_argv is None:
        from . import tools as _tools
        ruff_argv = _tools.ruff_argv
    try:
        argv = ruff_argv(strict=True)
    except Exception as exc:  # noqa: BLE001
        return _result("ruff", "env-broken", f"ruff unresolved: {exc}",
                       "strict resolution raises `S5 ruff unresolved:`",
                       "resolution succeeds and S5 still reports a lint finding")
    return _result("ruff", "ok", f"ruff resolves via {argv[0]!r}",
                   "strict resolution raises", "resolves, yet a lint finding is reported")


def probe_hermetic(env=None):
    """R13's signature: the operator's key/routing environment reaching the run.

    A live provider key turns an opt-in catalog check on, so the audit fails on
    upstream drift; routing knobs change which lane a test takes, so a green here
    is not the green CI sees. Both are dropped by R13, and the runbook's fix is
    to run under ``scripts/hermetic-env.sh`` (which also gives the child an empty
    home, where a key can also be resolved from a file).
    """
    env = os.environ if env is None else env
    leaked = sorted(name for name in HERMETIC_ENV_DROP if env.get(name))
    if leaked:
        routing = [name for name in leaked if name in ROUTING_ENV]
        keys = [name for name in leaked if name not in ROUTING_ENV]
        parts = []
        if keys:
            parts.append(f"key variable(s): {', '.join(keys)}")
        if routing:
            parts.append(f"routing knob(s): {', '.join(routing)}")
        return _result(
            "hermetic", "env-broken",
            f"{len(leaked)} ambient variable(s) reach the run ({'; '.join(parts)}); "
            f"rerun under scripts/hermetic-env.sh",
            "any of the R13 drop list is set",
            "drop list empty and the failure persists (a real defect)")
    return _result("hermetic", "ok", "no key or routing variable from the drop list",
                   "a drop-list variable is set", "empty drop list, failure persists")


def probe_d12(env=None):
    """D12 baseline staleness (#276's signature).

    D12 no longer trusts a stored baseline: it resolves the merge-base and
    regenerates when the committed document does not name it. What still goes
    wrong locally is a *hand-pinned* baseline that names a different commit, so
    the check compares ``HARNESS_D12_BASE`` with the commit inside
    ``HARNESS_D12_BASELINE`` when both are set.
    """
    env = os.environ if env is None else env
    base = (env or {}).get("HARNESS_D12_BASE")
    baseline = (env or {}).get("HARNESS_D12_BASELINE")
    if base and baseline:
        try:
            with open(baseline, encoding="utf-8") as handle:
                commit = json.load(handle).get("commit")
        except (OSError, ValueError) as exc:
            return _result("d12", "env-broken",
                           f"HARNESS_D12_BASELINE is unreadable ({exc})",
                           "the pinned baseline file is missing or malformed",
                           "the file is valid and D12 still disagrees")
        if commit and not str(base).startswith(str(commit)[:7]) \
                and not str(commit).startswith(str(base)[:7]):
            return _result(
                "d12", "env-broken",
                f"baseline names {commit!r} but HARNESS_D12_BASE is {base!r}; "
                f"drop the pin and let D12 resolve the merge-base",
                "pinned commit != resolved merge-base",
                "commits agree and coverage is still below 95% (a real gap)")
        return _result("d12", "ok",
                       f"baseline {commit!r} matches the declared base",
                       "commits disagree", "commits agree, ratio below 95%")
    return _result("d12", "ok", "no hand-pinned baseline; D12 resolves the merge-base",
                   "a pin names a different commit",
                   "no pin, yet the ratio is below 95% or the audit fails closed")


#: The runbook's entries, in the order it asks them.
PROBES = {
    "python": probe_python,
    "ruff": probe_ruff,
    "hermetic": probe_hermetic,
    "d12": probe_d12,
}


def run_checks(names=None, env=None):
    """Run the named probes (all by default). Returns a list of results."""
    chosen = list(names) if names else list(PROBES)
    unknown = [name for name in chosen if name not in PROBES]
    if unknown:
        raise KeyError(f"unknown check(s): {', '.join(unknown)}; "
                       f"known: {', '.join(PROBES)}")
    return [PROBES[name](env=env) for name in chosen]


def render(results):
    lines = []
    for item in results:
        lines.append(
            f"[triage] {item['check']:<9} {item['verdict']:<10} {item['detail']}"
        )
        expected = item["expected"]
        pad = ""
        lines.append(f"[triage] {pad:<9}   if env-broken: {expected['env-broken']}")
        lines.append(f"[triage] {pad:<9}   if code:      {expected['code-broken']}")
    broken = [item["check"] for item in results if item["verdict"] == "env-broken"]
    summary = (
        "all checks environment-clean"
        if not broken
        else "environment-broken: " + ", ".join(broken)
    )
    lines.append(f"[triage] {summary}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m harness.triage",
        description="Distinguishing checks from docs/audit-triage.md.")
    parser.add_argument("--check", action="append", default=None,
                        choices=sorted(PROBES),
                        help="run only this check (repeatable)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)
    try:
        results = run_checks(args.check)
    except KeyError as exc:
        print(f"[triage] {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(results, indent=1, sort_keys=True))
    else:
        print(render(results))
    return 0 if all(item["verdict"] in ("ok", "code-broken") for item in results) else 1


if __name__ == "__main__":
    sys.exit(main())
