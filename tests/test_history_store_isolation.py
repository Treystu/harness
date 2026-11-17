"""The suite must never append to the operator's chat store (issue #589).

3,766 of the 5,254 records in ``~/.config/harness/chat_history/default.jsonl``
were one test prompt, produced by hourglass fixtures that built a real
``AutonomousAgent`` without a ``history_dir`` and so fell back to the default
store. The suite now pins a private config directory (``tests/__init__.py``),
and this module holds the two contracts that keep it pinned: the default
history dir resolves inside the test root, and no hourglass fixture builds an
agent without naming a history dir.
"""
import os
import unittest
from pathlib import Path

import tests
from harness.history import get_default_history_dir, load_chat_history, save_chat_turn


def _norm(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


class DefaultHistoryDirIsIsolatedTests(unittest.TestCase):
    def test_default_history_dir_is_inside_the_pinned_test_root(self):
        resolved = _norm(get_default_history_dir())
        pinned = _norm(tests.CONFIG_ISOLATION_DIR)
        self.assertTrue(
            resolved == pinned or resolved.startswith(pinned + os.sep),
            f"default history dir {resolved} is not under the test root {pinned}")

    def test_default_history_dir_is_not_the_operator_store(self):
        resolved = _norm(get_default_history_dir())
        operator = _norm(Path(os.path.expanduser("~")) / ".config" / "harness")
        self.assertFalse(
            resolved == operator or resolved.startswith(operator + os.sep),
            f"default history dir still resolves to the operator store: {resolved}")

    def test_a_save_without_history_dir_lands_in_the_isolated_store(self):
        path = save_chat_turn("sess_isolation_probe", {"prompt": "isolation probe"})
        self.addCleanup(lambda: Path(path).unlink(missing_ok=True))

        resolved = _norm(path)
        pinned = _norm(tests.CONFIG_ISOLATION_DIR)
        self.assertTrue(resolved.startswith(pinned + os.sep), resolved)
        self.assertEqual(
            load_chat_history("sess_isolation_probe")[0]["prompt"], "isolation probe")


class HourglassFixturesNameAHistoryDirTests(unittest.TestCase):
    """Static guard: the omission is silent, so a new fixture must not repeat it."""

    def test_every_hourglass_agent_build_names_a_history_dir(self):
        root = Path(__file__).resolve().parent
        offenders = []
        for path in sorted(root.glob("test_hourglass_*.py")):
            lines = path.read_text(encoding="utf-8").splitlines()
            for index, line in enumerate(lines):
                if "AutonomousAgent(" not in line:
                    continue
                # The construction can span a few lines; the history_dir must be
                # part of it rather than inherited from the default store.
                window = "\n".join(lines[index:index + 6])
                if "history_dir" not in window:
                    offenders.append(f"{path.name}:{index + 1}")
        self.assertEqual(offenders, [],
                         "agent builds without a history_dir: " + ", ".join(offenders))


if __name__ == "__main__":
    unittest.main()
