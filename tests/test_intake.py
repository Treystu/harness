"""Tests for project intake (#457): folder + one prompt, routed by mode.

The Build cases run for real: a real folder is created, a real venv is built
from the host interpreter, a real dependency is installed from a local
find-links directory, and the project's own unittest suite runs from the venv
interpreter. Nothing here asserts a string the code does not produce.
"""
import http.client
import tempfile
import unittest
import zipfile
from pathlib import Path

from harness.intake import (
    MODE_BUILD, MODE_CHAT, IntakeRefused, IntakeRequest, build_plan,
    prepare_project, run_intake, venv_python,
)
from harness.project_run import RunRegister
from tests.test_server import ServerHarness, _request

TEST_MODULE = '''"""The project's own test suite."""
import unittest

import demo_dep


class DemoDepTests(unittest.TestCase):
    def test_the_installed_dependency_is_importable(self):
        self.assertEqual(demo_dep.answer(), 42)
'''


def _wheel(directory: Path) -> None:
    """Build a real, installable wheel with no network and no build deps."""
    dist = "demo_dep-0.1.0.dist-info"
    files = {
        "demo_dep/__init__.py": "def answer():\n    return 42\n",
        f"{dist}/METADATA": ("Metadata-Version: 2.1\nName: demo-dep\n"
                             "Version: 0.1.0\n"),
        f"{dist}/WHEEL": ("Wheel-Version: 1.0\nGenerator: harness-tests\n"
                          "Root-Is-Purelib: true\nTag: py3-none-any\n"),
        f"{dist}/RECORD": "",
    }
    with zipfile.ZipFile(directory / "demo_dep-0.1.0-py3-none-any.whl",
                         "w") as archive:
        for name, body in files.items():
            archive.writestr(name, body)


class IntakeContractTests(unittest.TestCase):
    def test_mode_decides_routing_and_chat_executes_nothing(self):
        with tempfile.TemporaryDirectory() as parent:
            target = Path(parent) / "not-created"
            result = run_intake(IntakeRequest(root=str(target), prompt="build it",
                                               mode=MODE_CHAT, create=True))
            self.assertEqual(result["routed"], "chat")
            self.assertFalse(result["executed"])
            self.assertFalse(target.exists(),
                             "chat mode must not create the folder it was given")

    def test_folder_is_created_only_when_asked(self):
        with tempfile.TemporaryDirectory() as parent:
            target = Path(parent) / "nested" / "project"
            request = IntakeRequest(root=str(target), prompt="build it",
                                    mode=MODE_BUILD)
            with self.assertRaises(IntakeRefused) as ctx:
                prepare_project(request)
            self.assertEqual(ctx.exception.reason, "folder_missing")
            created = prepare_project(IntakeRequest(
                root=str(target), prompt="build it", create=True))
            self.assertTrue(created.is_dir())

    def test_inputs_are_validated_with_stable_reasons(self):
        cases = [
            (dict(root="", prompt="x"), "root_required"),
            (dict(root="relative/path", prompt="x"), "root_must_be_absolute"),
            (dict(root=tempfile.gettempdir(), prompt="   "), "empty_prompt"),
            (dict(root=tempfile.gettempdir(), prompt="x", mode="auto"),
             "bad_mode"),
            (dict(root=tempfile.gettempdir(), prompt="x" * 20_001),
             "prompt_too_long"),
        ]
        for kwargs, reason in cases:
            with self.subTest(reason=reason):
                with self.assertRaises(IntakeRefused) as ctx:
                    IntakeRequest(**kwargs)
                self.assertEqual(ctx.exception.reason, reason)

    def test_a_file_where_a_folder_belongs_is_refused(self):
        with tempfile.TemporaryDirectory() as parent:
            target = Path(parent) / "a-file.txt"
            target.write_text("not a project", encoding="utf-8")
            with self.assertRaises(IntakeRefused) as ctx:
                prepare_project(IntakeRequest(root=str(target), prompt="x"))
            self.assertEqual(ctx.exception.reason, "not_a_directory")

    def test_the_venv_interpreter_sits_inside_the_project(self):
        # The two layouts (Scripts/python.exe vs bin/python) are platform-shaped;
        # each CI leg exercises its own, so this pins only the invariant both
        # share: the interpreter belongs to the project's own venv.
        with tempfile.TemporaryDirectory() as root:
            path = Path(venv_python(root))
            self.assertEqual(path.parent.parent, Path(root).resolve() / ".venv")
            self.assertIn(path.parent.name, ("Scripts", "bin"))

    def test_the_plan_is_venv_first_and_a_test_gate_last(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "demo_dep.py").write_text("x = 1\n", encoding="utf-8")
            steps = build_plan(root, request=IntakeRequest(
                root=root, prompt="x", create=True))
            self.assertIn("-m", steps[0].argv)
            self.assertEqual(steps[0].argv[1:], ("-m", "venv", ".venv"))
            self.assertIn("python", Path(steps[-1].argv[0]).name.lower())
            self.assertIn("test gate", steps[-1].label)

    def test_a_declared_command_wins_and_runs_under_the_project_venv(self):
        with tempfile.TemporaryDirectory() as root:
            declared = ("python", "-m", "unittest", "discover", "-s", "tests")
            steps = build_plan(root, request=IntakeRequest(
                root=root, prompt="x", create=True, test_command=declared))
            self.assertEqual(steps[-1].argv[0], venv_python(root))
            self.assertEqual(tuple(steps[-1].argv[1:]), declared[1:])

    def test_requirements_become_an_offline_install_step(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "requirements.txt").write_text(
                "demo-dep==0.1.0\n", encoding="utf-8")
            wheels = Path(root) / "wheels"
            wheels.mkdir()
            steps = build_plan(root, request=IntakeRequest(
                root=root, prompt="x", create=True,
                offline_wheels=str(wheels),
                test_command=("python", "-m", "unittest", "discover",
                              "-s", "tests")))
            install = steps[1]
            self.assertEqual(install.argv[:5], (venv_python(root), "-m", "pip",
                                                "install", "-r"))
            self.assertIn("--no-index", install.argv)
            self.assertIn(str(wheels), install.argv)


class IntakeRunTests(unittest.TestCase):
    """The acceptance path: fresh folder + one prompt -> set up, run, verdict."""

    def test_a_fresh_folder_is_set_up_and_its_suite_runs_to_a_verdict(self):
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "fresh"
            root.mkdir()
            # Vendored inside the project: the governor refuses any argument
            # that resolves outside the granted workspace, wheels included.
            wheels = root / "wheels"
            wheels.mkdir()
            _wheel(wheels)
            (root / "requirements.txt").write_text(
                "demo-dep==0.1.0\n", encoding="utf-8")
            (root / "tests").mkdir()
            (root / "tests" / "__init__.py").write_text("", encoding="utf-8")
            (root / "tests" / "test_demo.py").write_text(TEST_MODULE,
                                                        encoding="utf-8")
            result = run_intake(IntakeRequest(
                root=str(root), prompt="build a demo package consumer",
                create=True, offline_wheels=str(wheels),
                test_command=("python", "-m", "unittest", "discover",
                              "-s", "tests", "-t", ".")))

            self.assertEqual(result["verdict"], "passed", result)
            self.assertTrue((root / ".venv").is_dir(), "a real venv exists")
            rows = RunRegister(result["register_path"]).entries()
            kinds = [row["kind"] for row in rows]
            self.assertEqual(kinds[0], "run_start")
            self.assertEqual(kinds[-1], "run_end")
            self.assertEqual(len([k for k in kinds if k == "step"]),
                             result["steps_run"])
            last = rows[-2]
            # unittest reports its summary on stderr, so the evidence is both
            # streams, exactly as the register records them.
            self.assertIn("OK", last["stdout"] + last["stderr"])
            self.assertEqual(rows[-1]["status"], "ok")
            self.assertEqual([step["label"].split()[0] for step in result["plan"]],
                             ["create", "install", "run"])

    def test_a_failing_suite_is_a_failed_verdict_not_an_exception(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "tests").mkdir()
            (Path(root) / "tests" / "__init__.py").write_text("", encoding="utf-8")
            (Path(root) / "tests" / "test_bad.py").write_text(
                "import unittest\n\n\nclass Bad(unittest.TestCase):\n"
                "    def test_bad(self):\n        self.fail('no')\n",
                encoding="utf-8")
            result = run_intake(IntakeRequest(
                root=root, prompt="build it", create=True,
                test_command=("python", "-m", "unittest", "discover",
                              "-s", "tests", "-t", ".")))
            self.assertEqual(result["verdict"], "failed")
            self.assertNotEqual(result["exit_code"], 0)
            self.assertEqual(result["steps_run"], 2, "venv and the gate both ran")


class IntakeHttpTests(ServerHarness):
    """/api/intake is the GUI's only intake door."""

    def _post(self, body):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        try:
            return _request(conn, "POST", "/api/intake", body)
        finally:
            conn.close()

    def test_chat_mode_through_the_endpoint_executes_nothing(self):
        with tempfile.TemporaryDirectory() as parent:
            target = Path(parent) / "chat-only"
            status, data = self._post({"root": str(target), "prompt": "hi",
                                       "mode": "chat", "create": True})
            self.assertEqual(status, 200, data)
            self.assertEqual(data["routed"], "chat")
            self.assertFalse(target.exists())

    def test_bad_input_is_a_400_with_the_reason(self):
        status, data = self._post({"root": "relative", "prompt": "x"})
        self.assertEqual(status, 400, data)
        self.assertEqual(data.get("error_kind"), "root_must_be_absolute")

    def test_a_build_intake_returns_a_verdict_and_a_register(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "tests").mkdir()
            (Path(root) / "tests" / "__init__.py").write_text("", encoding="utf-8")
            (Path(root) / "tests" / "test_ok.py").write_text(
                "import unittest\n\n\nclass Ok(unittest.TestCase):\n"
                "    def test_ok(self):\n        self.assertTrue(True)\n",
                encoding="utf-8")
            status, data = self._post({
                "root": root, "prompt": "build it", "mode": "build",
                "create": True,
                "test_command": ["python", "-m", "unittest", "discover",
                                 "-s", "tests", "-t", "."]})
            self.assertEqual(status, 200, data)
            self.assertEqual(data["verdict"], "passed", data)
            self.assertTrue(Path(data["register_path"]).is_file())
            self.assertEqual(data["gate"]["source"], "declared")


if __name__ == "__main__":
    unittest.main()
