"""#311: the gate for the optional local-fit train/export path.

The default install is ``.[dev]``. numpy, onnx and onnxruntime arrive only with
the ``local-fit-train`` extra, so the train/export tests carry ``skipUnless``
guards -- correct on a clean runner, and wrong in the one job whose whole
purpose is to exercise the path. The audit that filed this (#311) found the
artifact-generation path could pass the matrix without ever running: a skip
there reads as a pass.

This gate makes the optional job honest:

* it **refuses to run** when the extras are missing (exit 2) instead of
  letting the guards fire and reporting a green run;
* it runs the deterministic local-fit exercise for real through
  ``unittest``;
* it **fails when any test was skipped** (exit 1), naming the tests, so a
  ``skipUnless`` can never be mistaken for coverage;
* it fails when the suites ran no tests at all.

It prints the run/skip/failure counts the issue asks the job to report.
"""
from __future__ import annotations

import argparse
import importlib
import json
import unittest
from typing import Any, Callable, Dict, Iterable, List, Optional

#: Importable only with the ``local-fit-train`` extra.
REQUIRED_MODULES = ("numpy", "onnx", "onnxruntime")

#: The suite that trains, exports, reloads and scores a model artifact from
#: deterministic in-process rows. The older train/export suites read
#: ``audits/scmessenger/_runs/*``, which .gitignore excludes, so they cannot be
#: the exercise a checkout can run; they keep their guards for the default
#: matrix and this suite is the job's real path.
SUITES = ("tests.test_local_fit_optional_311",)

EXIT_PASS = 0
EXIT_VIOLATION = 1
EXIT_MISSING_EXTRAS = 2


def missing_requirements(
        import_module: Callable[[str], Any] = importlib.import_module) -> List[str]:
    """The optional extras that are not importable under this interpreter."""
    missing = []
    for name in REQUIRED_MODULES:
        try:
            import_module(name)
        except ImportError:
            missing.append(name)
    return missing


def run_suites(names: Iterable[str], *,
               loader: Optional[Callable[[List[str]], Any]] = None,
               stream: Any = None) -> Dict[str, Any]:
    """Run the named suites and count what actually executed.

    Skipped tests are recorded by name: in this job the skip is the finding,
    not a footnote. ``stream`` exists so a test can capture the runner's own
    output instead of printing it.
    """
    load = loader or unittest.defaultTestLoader.loadTestsFromNames
    run = unittest.TextTestRunner(verbosity=2, stream=stream).run(load(list(names)))
    skipped = [str(case) for case, _reason in getattr(run, "skipped", [])]
    return {
        "tests_run": int(run.testsRun),
        "skipped": len(skipped),
        "skipped_tests": skipped,
        "failures": len(run.failures),
        "errors": len(run.errors),
    }


def _verdict(counts: Dict[str, Any]) -> tuple:
    if counts["failures"] or counts["errors"]:
        return ("failed", f"{counts['failures']} failure(s) and "
                          f"{counts['errors']} error(s)")
    if counts["skipped"]:
        return ("skipped", "a skipped test is not a pass: "
                           + ", ".join(counts["skipped_tests"]))
    if counts["tests_run"] == 0:
        return ("no-tests", "the optional suites ran no tests at all")
    return ("ok", f"{counts['tests_run']} tests ran, none skipped")


def gate(names: Iterable[str] = SUITES, *,
         import_module: Callable[[str], Any] = importlib.import_module,
         loader: Optional[Callable[[List[str]], Any]] = None,
         stream: Any = None) -> Dict[str, Any]:
    """The job's verdict: prerequisites, real execution, no skips, no failures."""
    suites = list(names)
    missing = missing_requirements(import_module)
    if missing:
        return {
            "verdict": "missing-extras",
            "suites": suites,
            "reason": ("this job must install .[dev,local-fit-train]; "
                       "missing: " + ", ".join(missing)),
        }
    counts = run_suites(suites, loader=loader, stream=stream)
    verdict, reason = _verdict(counts)
    return dict(counts, verdict=verdict, suites=suites, reason=reason)


def exit_code(summary: Dict[str, Any]) -> int:
    """Pass, violation, or "the job was set up wrong" stay distinct."""
    verdict = summary.get("verdict")
    if verdict == "missing-extras":
        return EXIT_MISSING_EXTRAS
    return EXIT_PASS if verdict == "ok" else EXIT_VIOLATION


def main(argv: Optional[List[str]] = None, *,
         gate_fn: Callable[..., Dict[str, Any]] = gate,
         stream: Any = None) -> int:
    """Print the counts as machine JSON and return the gate's exit code."""
    parser = argparse.ArgumentParser(
        prog="harness.local_fit.optional_ci",
        description="Run the local-fit train/export suites with no skips allowed.")
    parser.add_argument("--suite", action="append", dest="suites", default=None,
                        help="suite module to run (repeatable); "
                             "defaults to the train/export suites")
    args = parser.parse_args(argv)
    summary = gate_fn(tuple(args.suites or SUITES), stream=stream)
    print(json.dumps(summary, sort_keys=True))
    return exit_code(summary)


if __name__ == "__main__":  # pragma: no cover - module entrypoint
    raise SystemExit(main())
