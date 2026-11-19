"""#480 BR2: the hand's process entry point obeys the hand's own gates.

The hand was a class the tests could drive, but BR2 describes a *process*
inside the interactive session. These tests run that process hermetically:
the screen reader is patched, the session probe is pinned, and every answer
is read back from the ledger exactly as the driver would.
"""
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from driver_core import capture_hand as hand


class HandCliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="hand-cli-")
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.frame = os.path.join(self.root, "frame.png")
        with open(self.frame, "wb") as handle:
            handle.write(b"frame")

    def _run(self, argv):
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.object(hand, "default_session_probe",
                               return_value=hand.INTERACTIVE), \
                contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            code = hand.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_once_answers_one_posted_request_and_exits(self):
        hand.post_capture_request(self.root, "cli-1", seat="driver")
        with mock.patch.object(hand.osal, "capture_screen",
                               return_value=(self.frame, "")):
            code, out, _ = self._run(["--root", self.root, "--once"])
        self.assertEqual(code, 0)
        result = hand.read_result(self.root, "cli-1", timeout=0.0)
        self.assertEqual(result["state"], hand.INTERACTIVE)
        self.assertEqual(result["path"], self.frame)
        self.assertIn('"answered": "cli-1"', out)

    def test_status_reports_without_answering(self):
        hand.post_capture_request(self.root, "cli-2", seat="driver")
        code, out, _ = self._run(["--root", self.root, "--status"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["pending"], 1)
        self.assertIsNone(hand.read_result(self.root, "cli-2", timeout=0.0))

    def test_the_seat_allowlist_is_read_from_the_command_line(self):
        hand.post_capture_request(self.root, "cli-3", seat="intruder")
        code, out, _ = self._run(["--root", self.root, "--seats", "driver",
                                  "--once"])
        self.assertEqual(code, 0)
        result = hand.read_result(self.root, "cli-3", timeout=0.0)
        self.assertIsNone(result["path"])
        self.assertIn("allowlist", result["detail"])
        self.assertIn('"state": null', out)

    def test_a_required_grant_is_read_from_the_command_line(self):
        hand.post_capture_request(self.root, "cli-4", seat="driver")
        code, _, _ = self._run(["--root", self.root, "--seats", "driver",
                                "--require-grant", "--once"])
        self.assertEqual(code, 0)
        result = hand.read_result(self.root, "cli-4", timeout=0.0)
        self.assertIsNone(result["path"])
        self.assertIn("grant", result["detail"].lower())

    def test_ctrl_c_stops_the_idle_loop_cleanly(self):
        calls = {"n": 0}

        def poll_once(_worker):
            calls["n"] += 1
            if calls["n"] == 1:
                return None
            raise KeyboardInterrupt

        with mock.patch.object(hand.CaptureHand, "poll_once", poll_once):
            code, out, _ = self._run(["--root", self.root, "--poll", "0.01"])
        self.assertEqual(code, 0)
        self.assertIn('"reason": "interrupt"', out)

    def test_an_unusable_root_is_a_named_failure(self):
        blocked = os.path.join(self.root, "not-a-directory")
        with open(blocked, "wb") as handle:
            handle.write(b"")
        code, _, err = self._run(["--root", blocked, "--status"])
        self.assertEqual(code, 1)
        self.assertIn("cannot use the ledger root", err)

    def test_a_root_is_required(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                hand.main(["--status"])
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
