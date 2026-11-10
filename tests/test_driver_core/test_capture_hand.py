"""#480 BR2 — the interactive-session hand + bus-backed consumer.

The bridge's second slice: a hand that runs inside the interactive
session answers capture requests from a private ledger, and the
non-desktop driver resolves through a consumer backend registered on
the BR1 surface. These tests pin the contract hermetically -- no
screen, no session, no second process:

* the LOCK RULE is absolute: locked answers the refusal and the capture
  callable never runs;
* an interactive hand answers capture and describe through the ledger;
* a quiet hand stays quiet: no pending request means no result;
* the consumer backend posts one request and returns what the hand
  answered, and it registers on the BR1 surface so ScreenSource
  resolves through it unchanged;
* an unanswered hand arrives as a named refusal, never an exception.
"""
import unittest

from driver_core import capture_hand, osal
from driver_core.capture_hand import (
    CaptureHand, HandError, INTERACTIVE, LOCKED, NO_FOREGROUND,
    post_capture_request, read_result,
)


def _ids(*values):
    return iter(values).__next__


class SessionStateTests(unittest.TestCase):
    def test_probe_states_pass_through(self):
        for state in (INTERACTIVE, LOCKED, NO_FOREGROUND):
            self.assertEqual(capture_hand.session_state(lambda: state), state)

    def test_unknown_probe_state_is_refused(self):
        with self.assertRaises(HandError):
            capture_hand.session_state(lambda: "half-awake")

    def test_bad_request_kind_is_refused(self):
        with self.assertRaises(HandError):
            post_capture_request(self._tmp(), "r1", kind="pixels")

    def test_bad_request_id_is_refused(self):
        with self.assertRaises(HandError):
            post_capture_request(self._tmp(), "../escape")

    def _tmp(self):
        import tempfile
        return tempfile.mkdtemp(prefix="hand-state-")


class HandPollTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.root = tempfile.mkdtemp(prefix="hand-")
        self.calls = []

    def _hand(self, state=INTERACTIVE, capture=None, describe=None):
        def fake_capture():
            self.calls.append("capture")
            if capture is not None:
                return capture()
            return "/tmp/shot.png", ""

        def fake_describe():
            self.calls.append("describe")
            if describe is not None:
                return describe()
            return {"window_title": "t"}, ""

        return CaptureHand(self.root, session_probe=lambda: state,
                           capture=fake_capture, describe=fake_describe)

    def test_idle_hand_is_quiet(self):
        self.assertIsNone(self._hand().poll_once())

    def test_locked_never_touches_pixels(self):
        def boom():
            raise AssertionError("reader ran while locked")

        hand = CaptureHand(self.root, session_probe=lambda: LOCKED,
                           capture=boom, describe=boom)
        post_capture_request(self.root, "r1", "capture")
        result = hand.poll_once()
        self.assertEqual(result["state"], LOCKED)
        self.assertIsNone(result["path"])
        self.assertIn("locked", result["detail"])
        self.assertEqual(self.calls, [])

    def test_locked_describe_is_also_a_refusal(self):
        hand = self._hand(state=LOCKED)
        post_capture_request(self.root, "r2", "describe")
        result = hand.poll_once()
        self.assertEqual(result["state"], LOCKED)
        self.assertIsNone(result["fields"])
        self.assertEqual(self.calls, [])

    def test_interactive_capture_answers_through_the_ledger(self):
        hand = self._hand()
        post_capture_request(self.root, "r3", "capture")
        result = hand.poll_once()
        self.assertEqual(result["path"], "/tmp/shot.png")
        self.assertEqual(result["state"], INTERACTIVE)
        stored = read_result(self.root, "r3", timeout=0)
        self.assertEqual(stored, result)

    def test_interactive_describe_answers_fields(self):
        hand = self._hand()
        post_capture_request(self.root, "r4", "describe")
        result = hand.poll_once()
        self.assertEqual(result["fields"], {"window_title": "t"})
        self.assertEqual(self.calls, ["describe"])

    def test_no_foreground_still_captures(self):
        hand = self._hand(state=NO_FOREGROUND)
        post_capture_request(self.root, "r5", "capture")
        result = hand.poll_once()
        self.assertEqual(result["state"], NO_FOREGROUND)
        self.assertEqual(result["path"], "/tmp/shot.png")

    def test_reader_bug_arrives_as_refusal(self):
        def boom():
            raise RuntimeError("bridge down")

        hand = self._hand(capture=boom)
        post_capture_request(self.root, "r6", "capture")
        result = hand.poll_once()
        self.assertIsNone(result["path"])
        self.assertIn("bridge down", result["detail"])

    def test_status_reports_state_and_depth(self):
        hand = self._hand()
        self.assertEqual(hand.status(),
                         {"state": INTERACTIVE, "pending": 0})
        post_capture_request(self.root, "r7", "capture")
        self.assertEqual(hand.status()["pending"], 1)

    def test_oldest_request_answers_first(self):
        hand = self._hand()
        post_capture_request(self.root, "r8", "capture")
        post_capture_request(self.root, "r9", "capture")
        first = hand.poll_once()
        self.assertEqual(first["request_id"], "r8")
        second = hand.poll_once()
        self.assertEqual(second["request_id"], "r9")
        self.assertIsNone(hand.poll_once())


class ConsumerBackendTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.root = tempfile.mkdtemp(prefix="hand-consumer-")
        for platform in osal.SUPPORTED:
            osal.disable_capture_backend(platform)
            self.addCleanup(osal.disable_capture_backend, platform)

    def _hand(self, state=INTERACTIVE):
        return CaptureHand(
            self.root, session_probe=lambda: state,
            capture=lambda: ("/tmp/shot.png", ""),
            describe=lambda: ({"window_title": "t"}, ""))

    def test_capture_half_posts_and_returns_the_frame(self):
        backend = capture_hand.bus_capture_backend(
            self.root, platform="windows",
            request_id_factory=_ids("c1"))
        post = backend.capture
        # The request is posted synchronously; answer it, then read back.
        import threading
        answered = threading.Event()

        def answer():
            import time as _time
            while not capture_hand.pending_requests(self.root):
                _time.sleep(0.001)
            self._hand().poll_once()
            answered.set()

        worker = threading.Thread(target=answer, daemon=True)
        worker.start()
        path, detail = post()
        worker.join(timeout=10)
        self.assertEqual(path, "/tmp/shot.png")
        self.assertEqual(detail, "")

    def test_describe_half_returns_fields(self):
        backend = capture_hand.bus_capture_backend(
            self.root, platform="windows",
            request_id_factory=_ids("d1"))
        import threading

        def answer():
            import time as _time
            while not capture_hand.pending_requests(self.root):
                _time.sleep(0.001)
            self._hand().poll_once()

        worker = threading.Thread(target=answer, daemon=True)
        worker.start()
        fields, detail = backend.describe()
        worker.join(timeout=10)
        self.assertEqual(fields, {"window_title": "t"})
        self.assertEqual(detail, "")

    def test_unanswered_hand_is_a_named_refusal(self):
        backend = capture_hand.bus_capture_backend(
            self.root, platform="windows", timeout=0.05,
            request_id_factory=_ids("gone"))
        path, detail = backend.capture()
        self.assertIsNone(path)
        self.assertIn("did not answer", detail)

    def test_consumer_registers_on_the_br1_surface(self):
        backend = capture_hand.register_bus_capture_backend(
            self.root, platform="windows",
            request_id_factory=_ids("r1"))
        self.assertIs(osal.capture_backends()["windows"], backend)
        import threading
        from unittest import mock

        def answer():
            import time as _time
            while not capture_hand.pending_requests(self.root):
                _time.sleep(0.001)
            self._hand().poll_once()

        worker = threading.Thread(target=answer, daemon=True)
        worker.start()
        with mock.patch.object(osal, "platform_name",
                               return_value="windows"):
            path, _ = osal.capture_screen(max_side=None)
        worker.join(timeout=10)
        self.assertEqual(path, "/tmp/shot.png")

    def test_locked_hand_reaches_the_driver_unnamed_frame(self):
        backend = capture_hand.bus_capture_backend(
            self.root, platform="windows",
            request_id_factory=_ids("locked1"))
        import threading

        def answer():
            import time as _time
            while not capture_hand.pending_requests(self.root):
                _time.sleep(0.001)
            CaptureHand(
                self.root, session_probe=lambda: LOCKED,
                capture=lambda: ("/tmp/evil.png", ""),
                describe=lambda: ({"window_title": "evil"}, "")).poll_once()

        worker = threading.Thread(target=answer, daemon=True)
        worker.start()
        path, detail = backend.capture()
        worker.join(timeout=10)
        self.assertIsNone(path)
        self.assertIn("locked", detail)


if __name__ == "__main__":
    unittest.main()
