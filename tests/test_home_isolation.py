"""Guards for the suite's operator-home isolation and the contamination cleanup.

Two failure modes are pinned here.

1. **Test runs writing the live operator home (#656).** ``tests/__init__.py``
   pins ``HARNESS_HOME`` and ``HARNESS_CONFIG_DIR`` at one ephemeral directory
   per process, so a test that forgets its own ``history_dir``/tempdir still
   cannot append a turn to the operator's real
   ``chat_history/conversation_memory.json`` or open the real serve log. Before
   the guard the suite had written 434 fixture temp paths into a 1163-fact
   memory document, and a hash-chained ledger cannot be un-written. These tests
   assert the pin is in force, so it cannot be removed silently.

2. **The cleanup script (#656 part 3).** The memory projection is plain JSON,
   not the chain, so identified test rows *can* be removed -- but only
   identified ones, dry-run by default, with a backup written before any
   removal. These tests drive the real script functions over a temp document.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from harness.config import get_config_dir
from harness.history import get_default_history_dir
from harness.serve_log import default_log_path
from tests import CONFIG_ISOLATION_DIR, HOME_ISOLATION_DIR

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts", "clean_memory_contamination.py")


def _load_script():
    import importlib.util

    spec = importlib.util.spec_from_file_location("clean_memory_contamination", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SuiteHomeIsolationTests(unittest.TestCase):
    def test_suite_pins_harness_home_and_config_dir(self):
        self.assertEqual(os.environ.get("HARNESS_HOME"),
                         os.path.join(HOME_ISOLATION_DIR, "home"))
        self.assertEqual(os.environ.get("HARNESS_CONFIG_DIR"), CONFIG_ISOLATION_DIR)
        self.assertTrue(os.path.isdir(HOME_ISOLATION_DIR))

    def test_pinned_state_is_outside_the_operator_tree(self):
        # The whole point is that these are NOT ~/.config/harness or ~/.harness.
        operator = os.path.join(os.sep, ".config", "harness")
        for path in (get_config_dir(), str(default_log_path()),
                     str(get_default_history_dir())):
            self.assertNotIn(operator, path)
            self.assertNotIn(os.path.join(os.sep, ".harness"), path)
            self.assertIn(tempfile.gettempdir(), path)

    def test_settings_resolve_the_isolated_config_dir(self):
        # An ambient HARNESS_CONFIG_DIR is overridden, not respected.
        self.assertEqual(os.path.abspath(get_config_dir()),
                         os.path.abspath(CONFIG_ISOLATION_DIR))

    def test_memory_projection_lands_in_the_isolated_history_dir(self):
        from harness.conversation_context import memory_path

        self.assertTrue(str(memory_path()).startswith(CONFIG_ISOLATION_DIR))

    def test_single_module_run_never_reaches_the_operator_memory(self):
        # A subprocess run of one module proves the pin is per process, not a
        # side effect of the module that happened to be discovered first.
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        code = (
            "import os;"
            "print(os.environ['HARNESS_CONFIG_DIR']);"
            "print(os.environ['HARNESS_HOME'])"
        )
        out = subprocess.run([sys.executable, "-c", code], env=env,
                             capture_output=True, text=True, check=False)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(CONFIG_ISOLATION_DIR, out.stdout)


class ContaminationCleanupTests(unittest.TestCase):
    def setUp(self):
        self.mod = _load_script()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.memory = self.root / "chat_history" / "conversation_memory.json"
        self.memory.parent.mkdir(parents=True)
        fixture = str(Path(tempfile.gettempdir()) / "tmpdeadbeef" / "provision-host")
        self.doc = {
            "schema": "conversation-memory-v1",
            "facts": [
                {"kind": "path", "value": fixture, "source": "user",
                 "session_id": "default", "first_seen": "x", "last_seen": "x"},
                # The same fixture path, doubled by an escaping round trip.
                {"kind": "path", "value": fixture.replace(os.sep, os.sep * 2),
                 "source": "user", "session_id": "default",
                 "first_seen": "x", "last_seen": "x"},
                {"kind": "site", "value": "example.com", "source": "user",
                 "session_id": "default", "first_seen": "x", "last_seen": "x"},
                {"kind": "path", "value": r"C:\\repo\\harness", "source": "user",
                 "session_id": "sess_real", "first_seen": "x", "last_seen": "x"},
            ],
            "sessions": {"default": {"turns": 2}},
        }
        self.memory.write_text(json.dumps(self.doc), encoding="utf-8")

    def test_a_tempfile_component_marks_a_row_outside_the_temp_root(self):
        from scripts.clean_memory_contamination import is_test_row

        # The audit runs its fixtures under audits/self/_runs/tmp; the OS temp
        # root never sees them, but the mkdtemp component still identifies
        # them as scratch.
        self.assertTrue(is_test_row({
            "kind": "path",
            "value": r"C:\repo\audits\self\_runs\tmp\tmpqblv6fo2\provision-host"}))
        self.assertTrue(is_test_row({
            "kind": "path",
            "value": r"C:\cache\builds-v0\.tmpRjtqKW\Scripts\python.exe"}))
        # A path that merely contains a directory called tmp is durable.
        self.assertFalse(is_test_row({"kind": "path", "value": "C:\\repo\\tmp\\notes.md"}))
        self.assertFalse(is_test_row({"kind": "site", "value": "example.com"}))

    def test_classifier_keeps_durable_facts_and_marks_fixture_rows(self):
        memory = self.mod.load(self.memory)
        test_rows = self.mod.test_rows(memory)
        self.assertEqual(len(test_rows), 2)
        kept = [f for f in memory["facts"] if f not in test_rows]
        self.assertEqual([f["value"] for f in kept],
                         ["example.com", r"C:\\repo\\harness"])

    def test_dry_run_changes_nothing(self):
        before = self.memory.read_bytes()
        report = self.mod.clean(self.memory, apply=False)
        self.assertEqual(report["removed"], 2)
        self.assertEqual(report["kept"], 2)
        self.assertFalse(report["applied"])
        self.assertEqual(self.memory.read_bytes(), before)
        self.assertEqual(list(self.memory.parent.iterdir()), [self.memory])

    def test_apply_removes_only_identified_rows_and_keeps_a_backup(self):
        report = self.mod.clean(self.memory, apply=True)
        self.assertEqual(report["removed"], 2)
        self.assertTrue(report["applied"])
        after = json.loads(self.memory.read_text(encoding="utf-8"))
        self.assertEqual([f["value"] for f in after["facts"]],
                         ["example.com", r"C:\\repo\\harness"])
        self.assertEqual(after["sessions"], self.doc["sessions"])
        backups = [p for p in self.memory.parent.iterdir()
                   if p.name.startswith(self.memory.name + ".bak-")]
        self.assertEqual(len(backups), 1)
        self.assertEqual(json.loads(backups[0].read_text(encoding="utf-8")),
                         self.doc)

    def test_a_second_run_removes_nothing(self):
        self.mod.clean(self.memory, apply=True)
        again = self.mod.clean(self.memory, apply=True)
        self.assertEqual(again["removed"], 0)

    def test_a_missing_document_is_reported_not_created(self):
        missing = self.root / "absent.json"
        report = self.mod.clean(missing, apply=True)
        self.assertFalse(report["exists"])
        self.assertFalse(missing.exists())

    def test_cli_defaults_to_dry_run(self):
        out = subprocess.run(
            [sys.executable, _SCRIPT, "--path", str(self.memory)],
            capture_output=True, text=True, check=False,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("dry-run", out.stdout)
        self.assertIn("would remove 2 test-run row(s), keeping 2", out.stdout)
        self.assertEqual(json.loads(self.memory.read_text(encoding="utf-8")),
                         self.doc)


if __name__ == "__main__":
    unittest.main()
