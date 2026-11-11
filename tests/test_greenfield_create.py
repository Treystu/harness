"""#456 greenfield file creation: create-mode across the apply engine.

A new-file target gets the same governance as an edit (atomic write via
the OSAL path, diff authorization, the verification gate in the new
file's directory) without requiring a pre-existing original or backup.

Hermetic throughout: the FakeTransport stands in for providers and the
scripted gate runner stands in for shell gates -- except the acceptance
test, which runs REAL gate subprocesses (py_compile per file, the unittest
suite as the final gate) in a REAL empty workspace, proving the full
plan -> apply -> gate chain creates files instead of mocking them.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

from harness.continuation import gate_id
from harness.dag import DAGNode, TaskDAG
from harness.errors import HarnessError
from harness.executor import PlanExecutor
from harness.filesafety import validate_target_file
from harness.repo_scope import discover_target_files
from harness.waist import heuristic_decompose_goal
from tests._applyfixture import (ApplyFixture)
from tests._fake import comp


class ValidateCreateTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def path(self, *parts):
        return os.path.join(self.dir.name, *parts)

    def test_missing_target_is_creatable_with_existing_parent(self):
        validate_target_file(self.path("new.py"), allow_create=True)

    def test_missing_target_still_refused_without_create(self):
        with self.assertRaisesRegex(HarnessError, "file not found"):
            validate_target_file(self.path("new.py"))

    def test_missing_parent_dir_fails_fast(self):
        with self.assertRaisesRegex(HarnessError, "parent directory"):
            validate_target_file(self.path("nodir", "new.py"),
                                 allow_create=True)

    def test_existing_file_refuses_create(self):
        p = self.path("old.py")
        with open(p, "w", encoding="utf-8") as f:
            f.write("x = 1\n")
        with self.assertRaisesRegex(HarnessError, "already exists"):
            validate_target_file(p, allow_create=True)
        # ... while the edit path still accepts it.
        validate_target_file(p)

    def test_symlink_at_target_refuses_create(self):
        if os.name == "nt":
            self.skipTest("symlink creation needs privilege on Windows")
        real = self.path("real.py")
        with open(real, "w", encoding="utf-8") as f:
            f.write("x = 1\n")
        link = self.path("link.py")
        os.symlink(real, link)
        with self.assertRaisesRegex(HarnessError, "symlink"):
            validate_target_file(link, allow_create=True)

    def test_directory_at_target_refuses_create(self):
        with self.assertRaisesRegex(HarnessError, "not a regular file"):
            validate_target_file(self.dir.name, allow_create=True)


class EngineCreateTests(ApplyFixture):
    NEW = "def double(n):\n    return n * 2\n"

    def test_create_writes_new_file_with_gate_in_its_dir(self):
        seen = {}

        def run(cmd, timeout=None, cwd=None):
            seen["cwd"] = cwd
            return (0, "")

        target = os.path.join(self.dir.name, "sub", "made.py")
        os.mkdir(os.path.join(self.dir.name, "sub"))
        _, _, _, engine = self.make_env(
            posts=[comp(self.NEW)], run=run)
        result = engine.apply_edit(
            task_id="t1", file_path=target, instruction="create doubler",
            verify_cmd="gate-cmd", require_consent=False, create=True)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["changed"])
        with open(target, encoding="utf-8") as f:
            self.assertEqual(f.read(), self.NEW)
        # No original to back up, and the gate ran in the NEW file's dir.
        self.assertIsNone(result["backup"])
        self.assertEqual(seen["cwd"], os.path.join(self.dir.name, "sub"))

    def test_create_refuses_existing_file(self):
        p = self.make_file()
        _, _, _, engine = self.make_env()
        with self.assertRaisesRegex(HarnessError, "already exists"):
            engine.apply_edit(task_id="t1", file_path=p,
                              instruction="overwrite", require_consent=False,
                              create=True)
        with open(p, encoding="utf-8") as f:
            from tests._applyfixture import ORIGINAL
            self.assertEqual(f.read(), ORIGINAL)

    def test_create_refuses_continuation_resume(self):
        """A create can never resume: its baseline is 'no file', so a saved
        continuation (whose gate was verified against another baseline) has
        nothing to resume against. Continuation validation already refuses a
        missing target, so the engine's own guard is the second line --
        exercised here with a validated continuation so the message is the
        create-specific one."""
        _, _, _, engine = self.make_env()
        target = os.path.join(self.dir.name, "fresh.py")
        validated = {"task_id": "t1", "file_path": target,
                     "verify_cmd": "gate-cmd",
                     "verify_gate_id": gate_id("gate-cmd")}
        with mock.patch("harness.apply.validate_continuation",
                        return_value=validated):
            with self.assertRaisesRegex(HarnessError, "cannot resume"):
                engine.apply_edit(task_id="t1", file_path=target,
                                  instruction="create", require_consent=False,
                                  create=True, verify_cmd="gate-cmd",
                                  continuation=validated)

    def test_continuation_validation_alone_refuses_a_missing_target(self):
        """The first line of defence: a continuation can never name a file
        that does not exist, so create+resume is refused two ways."""
        _, _, _, engine = self.make_env()
        target = os.path.join(self.dir.name, "fresh.py")
        with self.assertRaises(HarnessError):
            engine.apply_edit(
                task_id="t1", file_path=target, instruction="create",
                require_consent=False, create=True, verify_cmd="gate-cmd",
                continuation={"task_id": "t1", "file_path": target,
                              "verify_cmd": "gate-cmd",
                              "verify_gate_id": gate_id("gate-cmd")})

    def test_edit_path_still_requires_existence(self):
        _, _, _, engine = self.make_env()
        with self.assertRaisesRegex(HarnessError, "file not found"):
            engine.apply_edit(
                task_id="t1",
                file_path=os.path.join(self.dir.name, "nope.py"),
                instruction="change it", require_consent=False)


class DispatchCreateTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def test_apply_dispatch_allows_missing_with_create(self):
        from harness.server import validate_dispatch
        args = validate_dispatch(
            "apply", {"root_dir": self.dir.name,
                      "file": "pkg/new.py",
                      "instruction": "create it",
                      "create": True})
        self.assertTrue(args["create"])
        self.assertTrue(args["file"].endswith("new.py"))

    def test_apply_dispatch_refuses_missing_without_create(self):
        from harness.server import validate_dispatch
        # The edit path still refuses a missing target (the message comes
        # from resolve_workspace_path's must_exist resolution).
        with self.assertRaisesRegex(HarnessError, "unavailable|must be a file"):
            validate_dispatch(
                "apply", {"root_dir": self.dir.name,
                          "file": "pkg/new.py",
                          "instruction": "create it"})

    def test_apply_dispatch_create_refuses_existing(self):
        from harness.server import validate_dispatch
        p = os.path.join(self.dir.name, "old.py")
        with open(p, "w", encoding="utf-8") as f:
            f.write("x = 1\n")
        with self.assertRaisesRegex(HarnessError, "already exists"):
            validate_dispatch(
                "apply", {"root_dir": self.dir.name,
                          "file": "old.py",
                          "instruction": "overwrite",
                          "create": True})

    def test_apply_dispatch_create_refuses_a_directory_target(self):
        from harness.server import validate_dispatch
        os.mkdir(os.path.join(self.dir.name, "pkgdir.py"))
        with self.assertRaisesRegex(HarnessError, "must not be a directory"):
            validate_dispatch(
                "apply", {"root_dir": self.dir.name,
                          "file": "pkgdir.py",
                          "instruction": "create it",
                          "create": True})

    def test_apply_dispatch_create_refuses_a_symlink_target(self):
        from harness.server import validate_dispatch
        if os.name == "nt":
            self.skipTest("symlink creation needs privilege on Windows")
        real = os.path.join(self.dir.name, "real_mod.py")
        with open(real, "w", encoding="utf-8") as f:
            f.write("x = 1\n")
        os.symlink(real, os.path.join(self.dir.name, "link_mod.py"))
        # The refusal is the shared workspace rule, so assert its wording --
        # not a second spelling invented here (#486 CI failure).
        with self.assertRaisesRegex(HarnessError, "symlink targets are excluded"):
            validate_dispatch(
                "apply", {"root_dir": self.dir.name,
                          "file": "link_mod.py",
                          "instruction": "create it",
                          "create": True})

    def test_apply_dispatch_create_refuses_traversal(self):
        from harness.server import validate_dispatch
        with self.assertRaises(HarnessError):
            validate_dispatch(
                "apply", {"root_dir": self.dir.name,
                          "file": "../outside.py",
                          "instruction": "escape",
                          "create": True})


class TriageCreateTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def test_empty_workspace_returns_named_new_targets(self):
        found = discover_target_files(
            "build a tiny package: create pkg/calc.py with an add function",
            self.dir.name)
        self.assertIn("pkg/calc.py", found)

    def test_nonempty_workspace_ignores_missing_names(self):
        p = os.path.join(self.dir.name, "real.py")
        with open(p, "w", encoding="utf-8") as f:
            f.write("x = 1\n")
        found = discover_target_files(
            "also create pkg/calc.py alongside real.py", self.dir.name)
        self.assertIn("real.py", found)
        self.assertNotIn("pkg/calc.py", found)

    def test_a_directory_named_like_a_file_is_not_creatable(self):
        """A match that already exists on disk (here: a directory named
        like a module) is never returned as a create-intent target."""
        os.mkdir(os.path.join(self.dir.name, "pkg.py"))
        found = discover_target_files("create pkg.py now", self.dir.name)
        self.assertNotIn("pkg.py", found)

    def test_traversal_mention_dropped_on_empty_workspace(self):
        found = discover_target_files(
            "create ../evil.py now", self.dir.name)
        self.assertNotIn("../evil.py", found)
        self.assertFalse([f for f in found if f.startswith("..")])


class DagCreateTests(unittest.TestCase):
    def test_create_files_round_trip(self):
        dag = TaskDAG.from_dict({"nodes": [{
            "node_id": "task_1",
            "instruction": "Create pkg/a.py",
            "target_files": ["pkg/a.py"],
            "create_files": ["pkg/a.py"],
            "dependencies": []}]})
        node = dag.nodes["task_1"]
        self.assertEqual(node.create_files, ("pkg/a.py",))
        self.assertIn("pkg/a.py", dag.to_dict()["nodes"][0]["create_files"])

    def test_create_outside_targets_is_rejected(self):
        with self.assertRaisesRegex(HarnessError, "create_files"):
            TaskDAG.from_dict({"nodes": [{
                "node_id": "task_1",
                "instruction": "Create pkg/a.py",
                "target_files": ["pkg/b.py"],
                "create_files": ["pkg/a.py"],
                "dependencies": []}]})

    def test_executor_passes_create_only_for_marked_targets(self):
        # The executor's real default apply callback is engine.apply_edit;
        # a recording stub proves exactly what it forwards per target.
        seen = []

        class Engine:
            def apply_edit(self, **kwargs):
                seen.append(kwargs)
                return {"status": "ok"}

        node = DAGNode(node_id="task_1", instruction="Create x",
                       target_files=("new/a.py", "old/b.py"),
                       create_files=("new/a.py",))
        plan = PlanExecutor(Engine(), {}, parallel=False, isolate=False,
                            base_apply_kwargs={})
        plan._apply_edit("new/a.py", node, {}, None)
        plan._apply_edit("old/b.py", node, {}, None)
        by_target = {os.path.basename(k["file_path"]): k.get("create", False)
                     for k in seen}
        self.assertTrue(by_target["a.py"])
        self.assertFalse(by_target["b.py"])


class WaistHeuristicCreateTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def test_missing_candidates_marked_create_with_root(self):
        dag = heuristic_decompose_goal(
            "Build pkg/calc.py", ["pkg/calc.py"], root_dir=self.dir.name)
        self.assertEqual(dag.nodes["task_1"].create_files, ("pkg/calc.py",))

    def test_existing_candidates_not_marked(self):
        p = os.path.join(self.dir.name, "have.py")
        with open(p, "w", encoding="utf-8") as f:
            f.write("x = 1\n")
        dag = heuristic_decompose_goal(
            "Change have.py", ["have.py"], root_dir=self.dir.name)
        self.assertEqual(dag.nodes["task_1"].create_files, ())

    def test_no_root_marks_nothing(self):
        dag = heuristic_decompose_goal("Build pkg/calc.py", ["pkg/calc.py"])
        self.assertEqual(dag.nodes["task_1"].create_files, ())


TESTS_INIT = '"""Tests package."""\n'
CALC = "def add(a, b):\n    return a + b\n"
INIT = "from pkg.calc import add\n\n__all__ = [\"add\"]\n"
CALC_TEST = ("import unittest\n"
             "from pkg.calc import add\n\n\n"
             "class AddTests(unittest.TestCase):\n"
             "    def test_add(self):\n"
             "        self.assertEqual(add(2, 3), 5)\n\n\n"
             'if __name__ == "__main__":\n'
             "    unittest.main()\n")


class GreenfieldAcceptanceTests(ApplyFixture):
    """#456 acceptance: plan -> apply -> gate in an empty folder builds a
    real multi-file package. Empty directories are made up front (the
    engine creates files, never directory trees); zero files pre-exist.
    Every gate is a real subprocess in the new tree."""

    def test_plan_apply_gate_builds_package_from_nothing(self):
        for sub in ("pkg", "tests"):
            os.mkdir(os.path.join(self.dir.name, sub))
        fake, gov, ledger, engine = self.make_env(
            posts=[comp(INIT), comp(CALC), comp(TESTS_INIT), comp(CALC_TEST)])
        for task_id in ("t1", "t2", "t3", "t4"):
            ledger.ensure_offered_task_id(task_id, source="test_setup")
        gate = f"{sys.executable} -m py_compile"
        dag = TaskDAG(nodes={
            "task_1": DAGNode(
                node_id="task_1", instruction="Create pkg/__init__.py",
                target_files=("pkg/__init__.py",),
                create_files=("pkg/__init__.py",),
                local_gate=f"{gate} __init__.py"),
            "task_2": DAGNode(
                node_id="task_2", instruction="Create pkg/calc.py",
                target_files=("pkg/calc.py",),
                create_files=("pkg/calc.py",),
                dependencies=("task_1",),
                local_gate=f"{gate} calc.py"),
            "task_3": DAGNode(
                node_id="task_3", instruction="Create tests/__init__.py",
                target_files=("tests/__init__.py",),
                create_files=("tests/__init__.py",),
                dependencies=("task_2",),
                local_gate=f"{gate} __init__.py"),
            "task_4": DAGNode(
                node_id="task_4", instruction="Create tests/test_calc.py",
                target_files=("tests/test_calc.py",),
                create_files=("tests/test_calc.py",),
                dependencies=("task_3",),
                local_gate=f"{gate} test_calc.py"),
        })
        plan = PlanExecutor(
            engine, {}, parallel=False, isolate=False, repo=self.dir.name,
            base_apply_kwargs={"require_consent": False,
                               "task_id": "t1"},
            final_gate=(f"{sys.executable} -m unittest discover "
                        f"-s tests -t ."))
        results = plan.execute(dag)
        for node_id in ("task_1", "task_2", "task_3", "task_4"):
            self.assertEqual(results[node_id]["status"], "ok", node_id)
        self.assertEqual(results["final_gate"]["status"], "ok")
        for rel, body in (("pkg/__init__.py", INIT),
                          ("pkg/calc.py", CALC),
                          ("tests/__init__.py", TESTS_INIT),
                          ("tests/test_calc.py", CALC_TEST)):
            with open(os.path.join(self.dir.name, rel),
                      encoding="utf-8") as f:
                self.assertEqual(f.read(), body)


if __name__ == "__main__":
    unittest.main()
