"""Turn identity in the persisted chat store (issue #570).

A stored turn used to carry no timestamp and no request id, so a session file
dated only its last append and no turn could be attributed to a request. The
cure is additive: every new record is stamped, and a record written before the
keys existed still reads back unchanged and is reported as legacy.
"""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from harness.errors import HarnessError
from harness.history import (
    TURN_REQUEST_KEY,
    TURN_SESSION_KEY,
    TURN_TS_KEY,
    load_chat_history,
    save_chat_turn,
    stamp_turn_identity,
    turn_identity,
)


class TurnIdentityStampTests(unittest.TestCase):
    def test_save_stamps_timestamp_session_and_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            turn = {"prompt": "audit this repo", "response": "done"}
            path = save_chat_turn("sess_identity", turn, Path(tmp))

            stored = json.loads(path.read_text(encoding="utf-8").strip())
            self.assertEqual(stored["prompt"], "audit this repo")
            self.assertEqual(stored[TURN_SESSION_KEY], "sess_identity")
            self.assertTrue(stored[TURN_REQUEST_KEY])
            stamped = datetime.fromisoformat(stored[TURN_TS_KEY])
            self.assertEqual(stamped.tzinfo, timezone.utc)

            # The stamp is additive: the caller's dict is untouched.
            self.assertEqual(set(turn), {"prompt", "response"})

    def test_caller_supplied_request_id_wins_so_a_row_joins_the_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = save_chat_turn(
                "sess_join", {"prompt": "p"}, Path(tmp),
                request_id="lifecycle-request-1")
            stored = json.loads(path.read_text(encoding="utf-8").strip())
            self.assertEqual(stored[TURN_REQUEST_KEY], "lifecycle-request-1")

    def test_request_id_already_on_the_turn_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = save_chat_turn(
                "sess_carried", {"prompt": "p", TURN_REQUEST_KEY: "carried-id"},
                Path(tmp))
            stored = json.loads(path.read_text(encoding="utf-8").strip())
            self.assertEqual(stored[TURN_REQUEST_KEY], "carried-id")

    def test_resaving_a_stamped_record_keeps_its_original_timestamp(self):
        record = stamp_turn_identity("sess_re", {"prompt": "p"})
        restamped = stamp_turn_identity("sess_re", record)
        self.assertEqual(restamped[TURN_TS_KEY], record[TURN_TS_KEY])
        self.assertEqual(restamped[TURN_REQUEST_KEY], record[TURN_REQUEST_KEY])

    def test_identity_is_unique_per_save_when_none_is_supplied(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = save_chat_turn("sess_u", {"prompt": "a"}, Path(tmp))
            second = save_chat_turn("sess_u", {"prompt": "b"}, Path(tmp))
            rows = [json.loads(line) for line in
                    first.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 2)
            self.assertNotEqual(rows[0][TURN_REQUEST_KEY], rows[1][TURN_REQUEST_KEY])
            self.assertEqual(second, first)


class LegacyTurnReadTests(unittest.TestCase):
    """Old records must read as legacy, not be rewritten into the new shape."""

    def _write_legacy(self, directory: Path) -> Path:
        path = directory / "sess_legacy.jsonl"
        path.write_text(json.dumps({
            "cost": 0.0, "intent": "simple-answer", "model": "m",
            "prompt": "old turn", "response": "old answer",
            "simple_request": True, "status": "ok", "workflow_tier": "T1",
        }) + "\n", encoding="utf-8")
        return path

    def test_legacy_record_is_readable_and_reported_as_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self._write_legacy(root)
            before = path.read_bytes()

            loaded = load_chat_history("sess_legacy", root)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["prompt"], "old turn")

            identity = turn_identity(loaded[0])
            self.assertTrue(identity["legacy"])
            self.assertIsNone(identity[TURN_TS_KEY])
            self.assertIsNone(identity[TURN_REQUEST_KEY])

            # Reading never rewrites the record on disk.
            self.assertEqual(path.read_bytes(), before)

    def test_old_and_new_shapes_read_in_one_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_legacy(root)
            save_chat_turn("sess_legacy", {"prompt": "new turn"}, root)

            loaded = load_chat_history("sess_legacy", root)
            identities = [turn_identity(turn) for turn in loaded]
            self.assertEqual([i["legacy"] for i in identities], [True, False])
            self.assertTrue(identities[1][TURN_TS_KEY])
            self.assertTrue(identities[1][TURN_REQUEST_KEY])

    def test_turn_identity_refuses_a_non_object(self):
        with self.assertRaises(HarnessError):
            turn_identity(["not", "a", "turn"])


if __name__ == "__main__":
    unittest.main()
