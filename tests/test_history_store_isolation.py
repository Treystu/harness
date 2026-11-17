"""Hourglass fixtures must name their own chat-history store (issue #589).

3,766 of the 5,254 records in ``~/.config/harness/chat_history/default.jsonl``
were one test prompt, produced by hourglass fixtures that built a real
``AutonomousAgent`` without a ``history_dir`` and so fell back to the
operator's default store. Every offending construction now passes its own
temporary store, and this module holds that shape in place: the omission is
silent at runtime -- the save simply lands somewhere else -- so it has to be
caught structurally rather than by watching a store.
"""
import json
import tempfile
import unittest
from pathlib import Path

from harness.history import load_chat_history, save_chat_turn


class ExplicitStoreTests(unittest.TestCase):
    """A fixture that passes a store writes there and nowhere else."""

    def test_an_explicit_store_receives_the_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = root / ".hist"
            store.mkdir()
            save_chat_turn("sess_fixture", {"prompt": "fixture turn"}, store)

            rows = [json.loads(line) for line in
                    (store / "sess_fixture.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows[0]["prompt"], "fixture turn")
            self.assertEqual(load_chat_history("sess_fixture", store)[0]["prompt"],
                             "fixture turn")


class HourglassFixturesNameAHistoryDirTests(unittest.TestCase):
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
