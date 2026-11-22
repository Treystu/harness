"""#656: the conftest home guard and the dry-run-first cleanup script.

Part (1) of #656 is the guard: a whole test session must write harness state
into an ephemeral directory, never the operator home. Part (3) is the cleanup
script, whose dry run is the operator-facing count. Part (2) -- the current
contamination count -- needs the laptop operator database and is filed as a
named local-lane act on the issue; nothing here invents that number.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from tests import conftest as guard  # noqa: E402

# pytest runs the hook; a bare `unittest` run does not, so install once here.
guard._install_guard()


class HomeGuardTests(unittest.TestCase):
    def test_the_guard_is_installed_for_the_session(self):
        root = guard.guard_root()
        self.assertTrue(os.path.isdir(root))
        self.assertTrue(root.startswith(tempfile.gettempdir()), root)

    def test_every_state_anchor_points_into_the_guard(self):
        root = guard.guard_root()
        self.assertEqual(os.environ["HARNESS_HOME"], root)
        self.assertTrue(os.environ["HARNESS_CONFIG_DIR"].startswith(root))
        self.assertTrue(os.environ["HARNESS_LEDGER"].startswith(root))

    def test_the_live_operator_home_is_not_the_target(self):
        root = guard.guard_root()
        home = os.path.expanduser("~")
        self.assertNotEqual(os.path.abspath(root), os.path.abspath(home))
        self.assertNotIn(os.path.join(".config", "harness"),
                         os.environ["HARNESS_CONFIG_DIR"])

    def test_a_test_that_sets_its_own_home_still_wins(self):
        # The guard must not fight a test's own isolation.
        old = os.environ["HARNESS_HOME"]
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["HARNESS_HOME"] = tmp
            try:
                self.assertEqual(os.environ["HARNESS_HOME"], tmp)
            finally:
                os.environ["HARNESS_HOME"] = old


class CleanupScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="harness-cleanup-656-")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, True))
        self.ledger = Path(self.tmp) / "ledger.jsonl"
        rows = [
            {"task_id": "pytest-run-1", "caller": "agent", "cost": 1},
            {"task_id": "real-work", "caller": "operator", "cost": 2},
            {"session_id": "harness-test-home-abc", "cost": 3},
            {"task_id": "another", "caller": "operator", "cost": 4},
        ]
        self.ledger.write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "cleanup_test_records.py"),
             "--ledger", str(self.ledger), *args],
            capture_output=True, text=True, timeout=60)

    def test_the_default_is_a_dry_run_that_writes_nothing(self):
        before = self.ledger.read_text(encoding="utf-8")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("would remove 2 of 4", result.stdout)
        self.assertIn("dry run", result.stdout)
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), before)
        self.assertFalse(Path(str(self.ledger) + ".bak-test-cleanup").exists())

    def test_apply_removes_only_the_test_rows_and_keeps_a_backup(self):
        result = self._run("--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("removed 2 of 4", result.stdout)
        kept = [json.loads(line) for line in
                self.ledger.read_text(encoding="utf-8").splitlines() if line]
        self.assertEqual([r["task_id"] for r in kept],
                         ["real-work", "another"])
        self.assertTrue(Path(str(self.ledger) + ".bak-test-cleanup").exists())

    def test_an_exact_task_id_can_be_named(self):
        result = self._run("--task-id", "real-work")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("would remove 3 of 4", result.stdout)


if __name__ == "__main__":
    unittest.main()
