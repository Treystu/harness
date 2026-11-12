"""Tests for the governed project execution envelope (#458).

These exercise real behavior: a real argv runs, a real venv is created, a real
wheel is installed from a local find-links directory, and the project's own
unittest suite runs from the venv interpreter. Nothing here asserts a string
the code does not produce.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
import zipfile
from pathlib import Path

from harness import project_run as pr
from harness.errors import HarnessError
from harness.project_run import (
    HARD_PROJECT_BUDGET_USD, HARD_PROJECT_ROUNDS,
    ProjectRunEnvelope, ProjectRunMeter, ProjectRunRefused, ProjectStep,
    RunRegister, WorkspaceGrant, command_env, discover_test_command,
    governed_argv, plan_digest, run_project, step_digest,
)


def _python_step(code, kind="mutating", **kw):
    return ProjectStep((sys.executable, "-c", code), kind=kind, **kw)


def _repo_python(root):
    """An absolute interpreter path *inside* the workspace (never executed)."""
    return str(Path(root).resolve() / "python")


class EnvelopeTests(unittest.TestCase):
    def test_defaults_are_project_sized_and_distinct_from_edit_caps(self):
        env = ProjectRunEnvelope.from_settings()
        self.assertEqual(env.rounds, pr.DEFAULT_PROJECT_ROUNDS)
        self.assertGreater(env.rounds, 3, "MAX_APPLY_ROUNDS is an edit cap")
        self.assertNotEqual(env.budget_usd, 1.00)
        self.assertEqual(env.as_dict()["wall_clock_s"], pr.DEFAULT_PROJECT_WALL_CLOCK_S)

    def test_settings_win_and_hard_caps_clamp(self):
        class Settings:
            project_rounds = 999
            project_budget_usd = "0.25"
            project_wall_clock_s = 0
            project_max_output_bytes = None

        env = ProjectRunEnvelope.from_settings(Settings(), environ={})
        self.assertEqual(env.rounds, HARD_PROJECT_ROUNDS)
        self.assertEqual(env.budget_usd, 0.25)
        self.assertEqual(env.wall_clock_s, 1)
        self.assertEqual(env.max_output_bytes, pr.DEFAULT_MAX_COMMAND_OUTPUT_BYTES)

    def test_env_is_used_when_settings_are_absent_and_bad_values_fall_back(self):
        env = ProjectRunEnvelope.from_settings(
            environ={"HARNESS_PROJECT_ROUNDS": "not-a-number",
                     "HARNESS_PROJECT_BUDGET_USD": "1e9",
                     "HARNESS_PROJECT_MAX_OUTPUT_BYTES": "1"})
        self.assertEqual(env.rounds, pr.DEFAULT_PROJECT_ROUNDS)
        self.assertEqual(env.budget_usd, HARD_PROJECT_BUDGET_USD)
        self.assertEqual(env.max_output_bytes, 1_000)


class MeterTests(unittest.TestCase):
    def test_charge_and_rounds_enforce_the_envelope(self):
        now = [0.0]
        meter = ProjectRunMeter(ProjectRunEnvelope(rounds=2, budget_usd=0.10,
                                                  wall_clock_s=10),
                                clock=lambda: now[0])
        self.assertEqual(meter.next_round(), 1)
        self.assertAlmostEqual(meter.charge_llm(0.05), 0.05)
        with self.assertRaises(ProjectRunRefused) as ctx:
            meter.charge_llm(0.06)
        self.assertEqual(ctx.exception.reason, "budget_exhausted")
        with self.assertRaises(ProjectRunRefused) as ctx:
            meter.next_round()
            meter.next_round()
            meter.next_round()
        self.assertEqual(ctx.exception.reason, "rounds_exhausted")
        now[0] = 11.0
        with self.assertRaises(ProjectRunRefused) as ctx:
            meter.check_wall_clock()
        self.assertEqual(ctx.exception.reason, "wall_clock_exhausted")


class StepTests(unittest.TestCase):
    def test_kind_and_argv_are_validated(self):
        with self.assertRaises(ProjectRunRefused) as ctx:
            ProjectStep(("python", "-c", "pass"), kind="destructive")
        self.assertEqual(ctx.exception.reason, "bad_step_kind")
        with self.assertRaises(ProjectRunRefused) as ctx:
            ProjectStep(())
        self.assertEqual(ctx.exception.reason, "empty_argv")

    def test_digests_are_stable_and_content_bound(self):
        first = ProjectStep(("python", "-m", "pytest"))
        second = ProjectStep(("python", "-m", "unittest"))
        self.assertEqual(plan_digest([first]), plan_digest([first]))
        self.assertNotEqual(plan_digest([first]), plan_digest([second]))
        self.assertEqual(first.digest, step_digest(("python", "-m", "pytest")))
        self.assertEqual(first.canonical()["kind"], "mutating")


class GovernorTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = self.dir.name

    def test_shell_strings_metacharacters_and_unknown_programs_refuse(self):
        cases = [
            ("python -c pass", "shell_string"),
            ([], "empty_argv"),
            (["python", "-c", "a; rm -rf /"], "shell_metacharacter"),
            (["curl", "http://example.com"], "program_not_allowed"),
        ]
        for argv, reason in cases:
            with self.assertRaises(ProjectRunRefused) as ctx:
                governed_argv(argv, root=self.root)
            self.assertEqual(ctx.exception.reason, reason, argv)

    def test_the_bootstrap_interpreter_may_live_outside_the_workspace(self):
        # ``<host python> -m venv .venv`` is the first step of a project run.
        allowed = governed_argv([sys.executable, "-m", "venv", ".venv"],
                                root=self.root)
        self.assertEqual(allowed, [sys.executable, "-m", "venv", ".venv"])
        inside = governed_argv([_repo_python(self.root), "-c", "pass"],
                               root=self.root)
        self.assertEqual(inside[0], _repo_python(self.root))

    def test_absolute_arguments_must_resolve_inside_the_workspace(self):
        covered = governed_argv([sys.executable, "-c", "pass",
                                 str(Path(self.root) / "notes.txt")],
                                root=self.root)
        self.assertIn("notes.txt", covered[-1])
        outside = str(Path(self.root).resolve().parent / "escape.py")
        with self.assertRaises(ProjectRunRefused) as ctx:
            governed_argv(["pip", "install", outside], root=self.root)
        self.assertEqual(ctx.exception.reason, "outside_workspace")

    def test_environment_is_scrubbed_and_pins_the_workspace(self):
        os.environ["HARNESS_TEST_SECRET_KEY"] = "do-not-leak"
        self.addCleanup(os.environ.pop, "HARNESS_TEST_SECRET_KEY", None)
        env = command_env(self.root)
        self.assertNotIn("HARNESS_TEST_SECRET_KEY", env)
        self.assertEqual(env["HARNESS_PROJECT_ROOT"], str(Path(self.root).resolve()))
        self.assertEqual(env["PYTHONPATH"], str(Path(self.root).resolve()))


class GrantTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = self.dir.name
        self.steps = [ProjectStep((sys.executable, "-c", "print(1)"))]
        self.grant = WorkspaceGrant(self.root, plan_digest(self.steps))

    def test_workspace_must_exist(self):
        with self.assertRaises(ProjectRunRefused) as ctx:
            WorkspaceGrant(str(Path(self.root) / "missing"), "d")
        self.assertEqual(ctx.exception.reason, "workspace_missing")

    def test_inside_paths_resolve_and_outside_refuses(self):
        inside = Path(self.root) / "pkg"
        inside.mkdir()
        self.assertEqual(self.grant.check_inside("pkg"), inside.resolve())
        self.assertEqual(self.grant.check_inside(str(inside)), inside.resolve())
        with self.assertRaises(ProjectRunRefused) as ctx:
            self.grant.check_inside(str(Path(self.root).parent / "escape"))
        self.assertEqual(ctx.exception.reason, "outside_workspace")

    def test_digest_must_match_or_nothing_is_covered(self):
        self.grant.require_digest(plan_digest(self.steps))
        with self.assertRaises(ProjectRunRefused) as ctx:
            self.grant.require_digest("0" * 64)
        self.assertEqual(ctx.exception.reason, "digest_mismatch")
        with self.assertRaises(ProjectRunRefused) as ctx:
            WorkspaceGrant(self.root, "").require_digest(plan_digest(self.steps))
        self.assertEqual(ctx.exception.reason, "digest_mismatch")

    def test_irreversible_keeps_its_own_single_use_approval(self):
        step = ProjectStep((sys.executable, "-c", "print(1)"), kind="irreversible")
        with self.assertRaises(ProjectRunRefused) as ctx:
            self.grant.authorize_step(step)
        self.assertEqual(ctx.exception.reason, "irreversible_needs_approval")
        approved = self.grant.approve_irreversible(step)
        approved.authorize_step(step)
        approved.authorize_step(ProjectStep((sys.executable, "-c", "pass")))


class ReviewCureTests(unittest.TestCase):
    """Each finding the PR review raised, pinned by behavior."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = self.dir.name

    def _grant(self, steps):
        return WorkspaceGrant(self.root, plan_digest(steps))

    def test_direct_construction_is_clamped_by_the_hard_caps(self):
        env = ProjectRunEnvelope(rounds=10 ** 6, budget_usd=10 ** 9,
                                 wall_clock_s=10 ** 6, max_output_bytes=10 ** 9)
        self.assertEqual(env.rounds, HARD_PROJECT_ROUNDS)
        self.assertEqual(env.budget_usd, HARD_PROJECT_BUDGET_USD)
        self.assertEqual(env.wall_clock_s, pr.HARD_PROJECT_WALL_CLOCK_S)
        self.assertEqual(env.max_output_bytes, pr.MAX_COMMAND_OUTPUT_BYTES)

    def test_relative_traversal_cannot_leave_the_workspace(self):
        with self.assertRaises(ProjectRunRefused) as ctx:
            governed_argv([sys.executable, "-c", "pass", "../escape.py"],
                          root=self.root)
        self.assertEqual(ctx.exception.reason, "outside_workspace")

    def test_the_register_must_live_inside_the_workspace(self):
        steps = [ProjectStep((sys.executable, "-c", "print(1)"))]
        outside = Path(self.root).parent / "register.jsonl"
        with self.assertRaises(ProjectRunRefused) as ctx:
            run_project(steps, grant=self._grant(steps),
                        register_path=str(outside))
        self.assertEqual(ctx.exception.reason, "outside_workspace")
        self.assertFalse(outside.exists(), "nothing ran, nothing was written")

    def test_the_default_envelope_comes_from_settings(self):
        steps = [ProjectStep((sys.executable, "-c", "print(1)")),
                 ProjectStep((sys.executable, "-c", "print(2)"))]
        with mock.patch.dict(os.environ, {"HARNESS_PROJECT_ROUNDS": "1"}):
            with self.assertRaises(ProjectRunRefused) as ctx:
                run_project(steps, grant=self._grant(steps))
        self.assertEqual(ctx.exception.reason, "rounds_exhausted")

    def test_each_command_spends_one_round_of_the_meter(self):
        steps = [ProjectStep((sys.executable, "-c", "print(1)")),
                 ProjectStep((sys.executable, "-c", "print(2)"))]
        envelope = ProjectRunEnvelope(rounds=2)
        meter = ProjectRunMeter(envelope)
        result = run_project(steps, grant=self._grant(steps),
                             envelope=envelope, meter=meter)
        self.assertEqual(result.status, "ok")
        self.assertEqual(meter.rounds_used, 2)

    def test_an_exhausted_meter_stops_the_run_before_any_command(self):
        steps = [ProjectStep((sys.executable, "-c", "print(1)"))]
        envelope = ProjectRunEnvelope(rounds=1)
        meter = ProjectRunMeter(envelope)
        meter.next_round()
        with self.assertRaises(ProjectRunRefused) as ctx:
            run_project(steps, grant=self._grant(steps),
                        envelope=envelope, meter=meter)
        self.assertEqual(ctx.exception.reason, "rounds_exhausted")

    def test_one_irreversible_approval_cannot_cover_two_occurrences(self):
        step = ProjectStep((sys.executable, "-c", "print('once')"),
                           kind="irreversible")
        steps = [step, step]
        grant = self._grant(steps).approve_irreversible(step)
        with self.assertRaises(ProjectRunRefused) as ctx:
            run_project(steps, grant=grant)
        self.assertEqual(ctx.exception.reason, "irreversible_needs_approval")
        self.assertFalse((Path(self.root) / ".harness").exists(),
                         "the plan was refused before anything ran")

    def test_an_irreversible_approval_is_spent_by_its_step(self):
        step = ProjectStep((sys.executable, "-c", "print('once')"),
                           kind="irreversible")
        grant = self._grant([step]).approve_irreversible(step)
        self.assertEqual(len(grant.approved_irreversible), 1)
        result = run_project([step], grant=grant)
        self.assertEqual(result.status, "ok")
        self.assertEqual(grant.approved_irreversible, ())
        with self.assertRaises(ProjectRunRefused) as ctx:
            grant.consume_irreversible(step)
        self.assertEqual(ctx.exception.reason, "irreversible_needs_approval")


class RegisterTests(unittest.TestCase):
    def test_rows_append_and_missing_file_reads_empty(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "nested" / "register.jsonl"
            register = RunRegister(path)
            self.assertEqual(register.entries(), [])
            register.record(kind="step", argv=["python", "-c", "pass"])
            register.record(kind="run_end", status="ok")
            rows = register.entries()
        self.assertEqual([row["kind"] for row in rows], ["step", "run_end"])
        self.assertIn("at", rows[0])


class RunProjectTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = self.dir.name
        self.steps = [
            ProjectStep((sys.executable, "-c", "print('one')")),
            ProjectStep((sys.executable, "-c", "print('two' * 900)")),
        ]
        self.grant = WorkspaceGrant(self.root, plan_digest(self.steps))

    def test_off_digest_and_overlong_plans_refuse_before_running(self):
        other = [ProjectStep((sys.executable, "-c", "print('x')"))]
        with self.assertRaises(ProjectRunRefused) as ctx:
            run_project(other, grant=self.grant)
        self.assertEqual(ctx.exception.reason, "digest_mismatch")
        two_steps = other + [ProjectStep((sys.executable, "-c", "print('y')"))]
        grant = WorkspaceGrant(self.root, plan_digest(two_steps))
        with self.assertRaises(ProjectRunRefused) as ctx:
            run_project(two_steps, grant=grant,
                        envelope=ProjectRunEnvelope(rounds=1))
        self.assertEqual(ctx.exception.reason, "rounds_exhausted")

    def test_a_real_run_records_every_command_and_its_output(self):
        result = run_project(
            self.steps, grant=self.grant,
            envelope=ProjectRunEnvelope(max_output_bytes=1_000))
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.steps_run, 2)
        self.assertEqual(result.exit_code, 0)
        rows = RunRegister(result.register_path).entries()
        kinds = [row["kind"] for row in rows]
        self.assertEqual(kinds, ["run_start", "step", "step", "run_end"])
        self.assertEqual(rows[1]["stdout"].strip(), "one")
        # The long line is capped by the envelope, and the cap is real.
        self.assertLessEqual(len(rows[2]["stdout"]), 1_000)
        self.assertEqual(rows[1]["cwd"], str(Path(self.root).resolve()))
        self.assertIn("envelope", rows[0])
        receipt = result.as_dict()
        self.assertEqual(receipt["status"], "ok")
        self.assertEqual(receipt["steps_run"], 2)
        self.assertIsNone(receipt["failed_argv"])

    def test_a_failing_step_stops_the_run_and_is_evidence_not_an_exception(self):
        steps = [ProjectStep((sys.executable, "-c", "raise SystemExit(3)")),
                 ProjectStep((sys.executable, "-c", "print('never')"))]
        grant = WorkspaceGrant(self.root, plan_digest(steps))
        result = run_project(steps, grant=grant)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.exit_code, 3)
        self.assertEqual(result.failed_argv[0], sys.executable)
        self.assertEqual(result.steps_run, 1, "the failed command did run")
        rows = RunRegister(result.register_path).entries()
        self.assertEqual([row["kind"] for row in rows],
                         ["run_start", "step", "run_end"])
        self.assertEqual(rows[-1]["status"], "failed")

    def test_wall_clock_exhaustion_refuses_before_a_step_starts(self):
        steps = [ProjectStep((sys.executable, "-c", "print('x')"))]
        grant = WorkspaceGrant(self.root, plan_digest(steps))
        now = [0.0]
        meter = ProjectRunMeter(ProjectRunEnvelope(wall_clock_s=5),
                                clock=lambda: now[0])
        now[0] = 6.0
        with self.assertRaises(ProjectRunRefused) as ctx:
            run_project(steps, grant=grant, meter=meter, clock=lambda: now[0],
                        runner=lambda *a, **kw: (0, "", ""))
        self.assertEqual(ctx.exception.reason, "wall_clock_exhausted")


class GateDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)

    def test_declared_command_wins(self):
        found = discover_test_command(self.root, declared=["python", "-m", "pytest", "-q"])
        self.assertEqual(found["source"], "declared")
        self.assertFalse(found["fallback"])

    def test_pyproject_pytest_section(self):
        (self.root / "pyproject.toml").write_text(
            "[tool.pytest.ini_options]\naddopts = '-q'\n", encoding="utf-8")
        found = discover_test_command(self.root)
        self.assertEqual(found["source"], "pyproject-pytest")
        self.assertEqual(found["argv"], ["python", "-m", "pytest", "-q"])

    def test_package_json_test_script(self):
        (self.root / "package.json").write_text(
            json.dumps({"scripts": {"test": "node --test"}}), encoding="utf-8")
        self.assertEqual(discover_test_command(self.root)["source"], "package.json")

    def test_package_json_without_a_test_script_falls_through(self):
        (self.root / "package.json").write_text(
            json.dumps({"scripts": {"build": "x"}}), encoding="utf-8")
        (self.root / "main.py").write_text("x = 1\n", encoding="utf-8")
        found = discover_test_command(self.root)
        self.assertEqual(found["source"], "py_compile")

    def test_broken_package_json_falls_through(self):
        (self.root / "package.json").write_text("{not json", encoding="utf-8")
        (self.root / "main.py").write_text("x = 1\n", encoding="utf-8")
        self.assertEqual(discover_test_command(self.root)["source"], "py_compile")

    def test_setup_cfg_pytest_section(self):
        (self.root / "setup.cfg").write_text("[tool:pytest]\naddopts = -q\n",
                                            encoding="utf-8")
        self.assertEqual(discover_test_command(self.root)["source"], "setup.cfg")

    def test_py_compile_is_the_last_resort_and_needs_files(self):
        with self.assertRaises(ProjectRunRefused) as ctx:
            discover_test_command(self.root)
        self.assertEqual(ctx.exception.reason, "no_test_gate")
        (self.root / "a.py").write_text("x = 1\n", encoding="utf-8")
        found = discover_test_command(self.root)
        self.assertTrue(found["fallback"])
        self.assertEqual(found["argv"], ["python", "-m", "py_compile", "a.py"])


class AcceptanceChainTests(unittest.TestCase):
    """The #458 acceptance: venv + dependency install + the project's suite,
    unattended, under ONE intake grant, every command in the register."""

    def _build_wheel(self, target):
        target.mkdir(parents=True, exist_ok=True)
        wheel = target / "demo_dep-0.1-py3-none-any.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("demo_dep/__init__.py", "VALUE = 41\n")
            archive.writestr("demo_dep-0.1.dist-info/METADATA",
                             "Metadata-Version: 2.1\nName: demo-dep\n"
                             "Version: 0.1\n")
            archive.writestr("demo_dep-0.1.dist-info/WHEEL",
                             "Wheel-Version: 1.0\nGenerator: test\n"
                             "Root-Is-Purelib: true\nTag: py3-none-any\n")
            archive.writestr("demo_dep-0.1.dist-info/RECORD", "")
        return wheel

    def test_unattended_project_run_from_an_empty_workspace(self):
        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root)
            (workspace / "wheels").mkdir()
            self._build_wheel(workspace / "wheels")
            (workspace / "tests").mkdir()
            (workspace / "tests" / "test_demo.py").write_text(
                "import unittest\nimport demo_dep\n\n"
                "class DemoTests(unittest.TestCase):\n"
                "    def test_value(self):\n"
                "        self.assertEqual(demo_dep.VALUE + 1, 42)\n\n"
                "if __name__ == '__main__':\n"
                "    unittest.main()\n", encoding="utf-8")
            (workspace / "pyproject.toml").write_text(
                "[tool.pytest.ini_options]\n", encoding="utf-8")

            venv_dir = workspace / ".venv"
            venv_python = (venv_dir / "Scripts" / "python.exe" if os.name == "nt"
                           else venv_dir / "bin" / "python")
            gate = discover_test_command(
                workspace, declared=[str(venv_python), "-m", "unittest",
                                     "discover", "-s", "tests"])
            steps = [
                ProjectStep((sys.executable, "-m", "venv", ".venv"),
                            label="venv"),
                ProjectStep((str(venv_python), "-m", "pip", "install",
                             "--no-index", "--find-links", "wheels",
                             "--disable-pip-version-check", "demo-dep"),
                            label="install"),
                ProjectStep(tuple(gate["argv"]), label="test suite"),
            ]
            grant = WorkspaceGrant(str(workspace), plan_digest(steps))
            result = run_project(steps, grant=grant)
            rows = RunRegister(result.register_path).entries()

        self.assertEqual(result.status, "ok", rows)
        self.assertEqual(result.exit_code, 0)
        step_rows = [row for row in rows if row["kind"] == "step"]
        self.assertEqual([row["label"] for row in step_rows],
                         ["venv", "install", "test suite"])
        self.assertTrue(all(row["exit_code"] == 0 for row in step_rows))
        self.assertIn("demo_dep", step_rows[1]["stdout"])
        self.assertIn("OK", step_rows[2]["stderr"] + step_rows[2]["stdout"])

    def test_stepping_outside_the_workspace_needs_fresh_consent(self):
        with tempfile.TemporaryDirectory() as root, \
                tempfile.TemporaryDirectory() as outside:
            steps = [ProjectStep((sys.executable, "-c", "pass",
                                  os.path.join(outside, "payload.py")))]
            grant = WorkspaceGrant(root, plan_digest(steps))
            with self.assertRaises(HarnessError) as ctx:
                run_project(steps, grant=grant)
            self.assertEqual(ctx.exception.reason, "outside_workspace")


if __name__ == "__main__":
    unittest.main()
