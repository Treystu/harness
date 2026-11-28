"""#311: the optional local-fit job is a gate, not a skip-shaped pass.

Hermetic: every dependency-shaped seam is injected, so these tests run in the
default install (which has none of numpy, onnx or onnxruntime) and prove the
gate's rules without needing the extras themselves.
"""
import io
import json
import subprocess
import unittest
from pathlib import Path

from harness.local_fit import optional_ci as gate

ROOT = Path(__file__).resolve().parents[1]


def _suite(*cases):
    suite = unittest.TestSuite()
    for case in cases:
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(case))
    return suite


class _Passes(unittest.TestCase):
    def test_one(self):
        self.assertTrue(True)

    def test_two(self):
        self.assertTrue(True)


# Cases that fail or skip on purpose live in factories: a module-level
# TestCase subclass would be collected (and fail) by the outer suite.
def _skipping_suite():
    class _Skips(unittest.TestCase):
        def test_runs(self):
            self.assertTrue(True)

        def test_skipped(self):
            # A runtime skip, not a decorator: the architecture guard refuses
            # blunt @unittest.skip disables, and this fixture is a test double
            # for exactly the skip the optional job must treat as a failure.
            raise unittest.SkipTest("train-time deps absent in this fixture")

    return _suite(_Skips)


def _failing_suite():
    class _Fails(unittest.TestCase):
        def test_fails(self):
            self.fail("boom")

    return _suite(_Fails)


def _erroring_suite():
    class _Errors(unittest.TestCase):
        def test_errors(self):
            raise RuntimeError("boom")

    return _suite(_Errors)


def _empty_suite():
    class _Empty(unittest.TestCase):
        pass

    return _suite(_Empty)


def _loader(cases):
    return lambda names: _suite(*cases)


def _present(_name):
    return object()


def _absent(*names):
    def importer(name):
        if name in names:
            raise ImportError(name)
        return object()
    return importer


class MissingRequirementTests(unittest.TestCase):
    """The job refuses to run rather than letting the guards fire."""

    def test_all_extras_present_reports_none_missing(self):
        self.assertEqual(gate.missing_requirements(_present), [])
        self.assertEqual(gate.missing_requirements(), list(gate.missing_requirements()))

    def test_only_the_unimportable_extras_are_named(self):
        importer = _absent("onnx")
        self.assertEqual(gate.missing_requirements(importer), ["onnx"])

    def test_every_extra_is_checked_in_order(self):
        importer = _absent("numpy", "onnxruntime")
        self.assertEqual(gate.missing_requirements(importer),
                         ["numpy", "onnxruntime"])
        self.assertEqual(gate.REQUIRED_MODULES,
                         ("numpy", "onnx", "onnxruntime"))


class MissingExtrasTests(unittest.TestCase):
    """A missing extra is exit 2, and no suite is even loaded."""

    def test_gate_refuses_without_running_anything(self):
        def loader(_names):
            raise AssertionError("the suites must not be loaded without extras")

        summary = gate.gate(("tests.sample",), import_module=_absent("numpy"),
                            loader=loader)
        self.assertEqual(summary["verdict"], "missing-extras")
        self.assertIn("local-fit-train", summary["reason"])
        self.assertIn("numpy", summary["reason"])
        self.assertNotIn("tests_run", summary)

    def test_missing_extras_exit_two(self):
        summary = gate.gate(("tests.sample",), import_module=_absent("onnx"),
                            loader=_loader([_Passes]))
        self.assertEqual(gate.exit_code(summary), gate.EXIT_MISSING_EXTRAS)


class SkippedTests(unittest.TestCase):
    """The load-bearing rule: a skip in this job is a failure."""

    def test_a_skip_fails_the_gate_and_names_the_test(self):
        summary = gate.gate(("tests.sample",), import_module=_present,
                            loader=lambda names: _skipping_suite(),
                            stream=io.StringIO())
        self.assertEqual(summary["verdict"], "skipped")
        self.assertEqual(summary["tests_run"], 2)
        self.assertEqual(summary["skipped"], 1)
        self.assertIn("test_skipped", summary["skipped_tests"][0])
        self.assertIn("a skipped test is not a pass", summary["reason"])
        self.assertEqual(gate.exit_code(summary), gate.EXIT_VIOLATION)

    def test_a_clean_run_passes_and_reports_its_counts(self):
        summary = gate.gate(("tests.sample",), import_module=_present,
                            loader=_loader([_Passes]), stream=io.StringIO())
        self.assertEqual(summary["verdict"], "ok")
        self.assertEqual((summary["tests_run"], summary["skipped"],
                          summary["failures"], summary["errors"]), (2, 0, 0, 0))
        self.assertEqual(summary["suites"], ["tests.sample"])
        self.assertEqual(summary["reason"], "2 tests ran, none skipped")
        self.assertEqual(gate.exit_code(summary), gate.EXIT_PASS)


class FailureTests(unittest.TestCase):
    """Failures, errors and an empty run are violations, never green."""

    def test_a_failure_fails_the_gate(self):
        summary = gate.gate(("tests.sample",), import_module=_present,
                            loader=lambda names: _failing_suite(),
                            stream=io.StringIO())
        self.assertEqual(summary["verdict"], "failed")
        self.assertEqual(summary["failures"], 1)
        self.assertIn("1 failure(s)", summary["reason"])
        self.assertEqual(gate.exit_code(summary), gate.EXIT_VIOLATION)

    def test_an_error_fails_the_gate(self):
        summary = gate.gate(("tests.sample",), import_module=_present,
                            loader=lambda names: _erroring_suite(),
                            stream=io.StringIO())
        self.assertEqual(summary["verdict"], "failed")
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(gate.exit_code(summary), gate.EXIT_VIOLATION)

    def test_an_empty_run_fails_the_gate(self):
        summary = gate.gate(("tests.sample",), import_module=_present,
                            loader=lambda names: _empty_suite(),
                            stream=io.StringIO())
        self.assertEqual(summary["verdict"], "no-tests")
        self.assertEqual(summary["tests_run"], 0)
        self.assertEqual(gate.exit_code(summary), gate.EXIT_VIOLATION)

    def test_an_unknown_verdict_is_a_violation(self):
        self.assertEqual(gate.exit_code({}), gate.EXIT_VIOLATION)
        self.assertEqual(gate.exit_code({"verdict": "anything-else"}),
                         gate.EXIT_VIOLATION)


class EntrypointTests(unittest.TestCase):
    """`python -m harness.local_fit.optional_ci` prints JSON and exits."""

    def test_main_defaults_to_the_train_export_suites(self):
        seen = {}

        def gate_fn(names, stream=None):
            seen["names"] = names
            return {"verdict": "ok", "tests_run": 1, "skipped": 0}

        printed = io.StringIO()
        import contextlib
        with contextlib.redirect_stdout(printed):
            code = gate.main([], gate_fn=gate_fn)
        self.assertEqual(code, gate.EXIT_PASS)
        self.assertEqual(seen["names"], gate.SUITES)
        self.assertEqual(json.loads(printed.getvalue())["verdict"], "ok")

    def test_main_honours_repeated_suite_arguments(self):
        seen = {}

        def gate_fn(names, stream=None):
            seen["names"] = names
            return {"verdict": "skipped", "skipped_tests": ["x"]}

        printed = io.StringIO()
        import contextlib
        with contextlib.redirect_stdout(printed):
            code = gate.main(["--suite", "tests.a", "--suite", "tests.b"],
                             gate_fn=gate_fn)
        self.assertEqual(seen["names"], ("tests.a", "tests.b"))
        self.assertEqual(code, gate.EXIT_VIOLATION)
        self.assertEqual(json.loads(printed.getvalue())["verdict"], "skipped")


class ContractTests(unittest.TestCase):
    """The job's scope is pinned to the issue's acceptance criteria."""

    def test_the_suite_is_the_deterministic_train_export_exercise(self):
        self.assertEqual(gate.SUITES, ("tests.test_local_fit_optional_311",))
        self.assertTrue((ROOT / "tests" / "test_local_fit_optional_311.py").is_file())

    def test_training_dependencies_stay_out_of_the_default_install(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        project = text[text.index("[project]"):text.index("[project.urls]")]
        self.assertNotIn("\ndependencies =", project)
        for required in ("numpy", "onnx", "onnxruntime"):
            self.assertNotIn(required, project)
        extra_start = text.index("local-fit-train = [")
        extra = text[extra_start:text.index("]", extra_start)]
        for required in ("numpy", "onnx", "onnxruntime"):
            self.assertIn(required, extra)

    def test_the_optional_job_is_declared_in_the_circleci_config(self):
        config = (ROOT / ".circleci" / "config.yml").read_text(encoding="utf-8")
        self.assertIn("local-fit-optional:", config)
        self.assertIn(".[dev,local-fit-train]", config)
        self.assertIn("python -m harness.local_fit.optional_ci", config)

    def test_the_audit_fixture_the_old_suites_read_is_not_committed(self):
        """Why the job runs a deterministic suite instead of the old ones.

        The assertion is about committed fixtures, not about a directory: a
        developer checkout legitimately holds the gitignored run artifacts
        (``tests/test_local_fit_extract.py`` supports them being present), so
        testing existence would fail the default suite on a valid tree.
        """
        tracked = subprocess.run(
            ["git", "ls-files", "--", "audits/scmessenger/_runs"],
            cwd=str(ROOT), capture_output=True, text=True)
        if tracked.returncode == 0:
            self.assertEqual(tracked.stdout.strip(), "",
                             "no audit-run fixture may be committed")
        self.assertIn("audits/scmessenger/_runs/",
                      (ROOT / ".gitignore").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
