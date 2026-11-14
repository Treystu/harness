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
* an unanswered hand arrives as a named refusal, never an exception;
* BR3: every answered frame carries a declared envelope stamped when the
  reader returned the pixels, and the consumer refuses a frame it cannot
  date, one outside the declared window, and one stamped in the future
  (two clocks that disagree), while tolerating jitter on one machine.
"""
import json
import os
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


class FrameEnvelopeTests(unittest.TestCase):
    def test_envelope_carries_schema_path_stamp_and_state(self):
        frame = capture_hand.frame_envelope(
            path="/tmp/a.png", captured_at=1000.0, state=INTERACTIVE)
        self.assertEqual(frame, {
            "schema": capture_hand.FRAME_SCHEMA, "path": "/tmp/a.png",
            "captured_at": 1000.0, "state": INTERACTIVE})
        self.assertEqual(capture_hand.FRAME_SCHEMA, "frame@1")

    def test_envelope_refuses_a_frame_with_no_path(self):
        for path in (None, "", "   ", 7):
            with self.assertRaises(HandError):
                capture_hand.frame_envelope(
                    path=path, captured_at=1.0, state=INTERACTIVE)

    def test_envelope_refuses_an_undatable_stamp(self):
        for stamp in (None, "soon", True, float("nan"), float("inf")):
            with self.assertRaises(HandError):
                capture_hand.frame_envelope(
                    path="/tmp/a.png", captured_at=stamp, state=INTERACTIVE)

    def test_envelope_refuses_an_undeclared_state(self):
        with self.assertRaises(HandError):
            capture_hand.frame_envelope(
                path="/tmp/a.png", captured_at=1.0, state="half-awake")


class FreshnessGateTests(unittest.TestCase):
    def _result(self, captured_at, *, schema=None, path="/tmp/a.png"):
        return {
            "request_id": "r", "kind": "capture", "state": INTERACTIVE,
            "path": path,
            "frame": {
                "schema": schema or capture_hand.FRAME_SCHEMA,
                "path": path,
                capture_hand.CAPTURED_AT_FIELD: captured_at,
                "state": INTERACTIVE,
            },
        }

    def test_a_fresh_frame_passes_silently(self):
        ok, detail = capture_hand.check_freshness(
            self._result(1000.0), max_age=5.0, now=1001.5)
        self.assertTrue(ok)
        self.assertEqual(detail, "")

    def test_the_window_edge_is_inside_the_window(self):
        ok, _ = capture_hand.check_freshness(
            self._result(1000.0), max_age=5.0, now=1005.0)
        self.assertTrue(ok)

    def test_a_stale_frame_is_refused_by_name_and_age(self):
        ok, detail = capture_hand.check_freshness(
            self._result(1000.0), max_age=5.0, now=1006.25)
        self.assertFalse(ok)
        self.assertIn("stale", detail)
        self.assertIn("6.250s", detail)
        self.assertIn("allows 5s", detail)

    def test_the_default_window_is_five_seconds(self):
        self.assertEqual(capture_hand.DEFAULT_MAX_AGE, 5.0)
        ok, detail = capture_hand.check_freshness(
            self._result(1000.0), now=1000.0 + capture_hand.DEFAULT_MAX_AGE + 1)
        self.assertFalse(ok)
        self.assertIn("stale", detail)

    def test_a_result_with_no_envelope_is_refused(self):
        for result in ({"path": "/tmp/a.png"}, {"frame": None, "path": "x"},
                       "not a record"):
            ok, detail = capture_hand.check_freshness(result, now=1000.0)
            self.assertFalse(ok)
            self.assertIn("no frame envelope", detail)

    def test_an_unknown_envelope_schema_is_refused(self):
        ok, detail = capture_hand.check_freshness(
            self._result(1000.0, schema="frame@0"), now=1000.0)
        self.assertFalse(ok)
        self.assertIn("no frame envelope", detail)

    def test_an_undatable_stamp_is_refused(self):
        ok, detail = capture_hand.check_freshness(
            self._result("soon"), now=1000.0)
        self.assertFalse(ok)
        self.assertIn("cannot be evaluated", detail)

    def test_a_future_stamp_is_a_clock_disagreement_not_a_pass(self):
        ok, detail = capture_hand.check_freshness(
            self._result(1000.0), now=1000.0 - capture_hand.MAX_CLOCK_LEAD - 1)
        self.assertFalse(ok)
        self.assertIn("future", detail)
        self.assertIn("disagree about the clock", detail)

    def test_one_machine_jitter_is_tolerated(self):
        ok, detail = capture_hand.check_freshness(
            self._result(1000.0), now=1000.0 - capture_hand.MAX_CLOCK_LEAD / 2)
        self.assertTrue(ok)
        self.assertEqual(detail, "")

    def test_an_impossible_window_is_the_callers_bug(self):
        for window in (-1, -0.5, True, "5", float("nan")):
            with self.assertRaises(HandError):
                capture_hand.check_freshness(
                    self._result(1000.0), max_age=window, now=1000.0)

    def test_frame_age_reports_and_never_guesses(self):
        self.assertAlmostEqual(
            capture_hand.frame_age(self._result(1000.0)["frame"], now=1002.0),
            2.0)
        self.assertIsNone(capture_hand.frame_age({"path": "/tmp/a.png"}))
        self.assertIsNone(capture_hand.frame_age({
            "schema": capture_hand.FRAME_SCHEMA, "captured_at": "soon"}))
        self.assertIsNone(capture_hand.frame_age(None))


class HandStampTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.root = tempfile.mkdtemp(prefix="hand-stamp-")

    def _hand(self, clock, *, state=INTERACTIVE, capture=None):
        return CaptureHand(
            self.root, session_probe=lambda: state, clock=clock,
            capture=capture or (lambda: ("/tmp/shot.png", "")),
            describe=lambda: ({"window_title": "t"}, ""))

    def test_a_capture_answer_carries_a_stamped_frame(self):
        hand = self._hand(lambda: 500.0)
        post_capture_request(self.root, "s1", "capture")
        result = hand.poll_once()
        self.assertEqual(result["path"], "/tmp/shot.png")
        self.assertEqual(result[capture_hand.FRAME_FIELD], {
            "schema": capture_hand.FRAME_SCHEMA, "path": "/tmp/shot.png",
            capture_hand.CAPTURED_AT_FIELD: 500.0, "state": INTERACTIVE})

    def test_the_stamp_is_the_readers_not_the_writers(self):
        # answered_at is written when the record is stored; captured_at is
        # taken when the pixels existed. They are different facts, and the
        # answer carries both rather than one standing in for the other.
        hand = self._hand(lambda: 500.0)
        post_capture_request(self.root, "s2", "capture")
        result = hand.poll_once()
        self.assertEqual(
            result[capture_hand.FRAME_FIELD][capture_hand.CAPTURED_AT_FIELD],
            500.0)
        self.assertGreater(result["answered_at"], 1.0e9)

    def test_a_locked_answer_carries_no_frame(self):
        hand = self._hand(lambda: 500.0, state=LOCKED)
        post_capture_request(self.root, "s3", "capture")
        result = hand.poll_once()
        self.assertIsNone(result[capture_hand.FRAME_FIELD])
        self.assertIsNone(result["path"])

    def test_an_undatable_clock_offers_no_frame(self):
        hand = self._hand(lambda: "soon")
        post_capture_request(self.root, "s4", "capture")
        result = hand.poll_once()
        self.assertIsNone(result["path"])
        self.assertIsNone(result[capture_hand.FRAME_FIELD])
        self.assertIn("clock", result["detail"])

    def test_a_describe_answer_carries_fields_not_a_frame(self):
        hand = self._hand(lambda: 500.0)
        post_capture_request(self.root, "s5", "describe")
        result = hand.poll_once()
        self.assertEqual(result["fields"], {"window_title": "t"})
        self.assertNotIn(capture_hand.FRAME_FIELD, result)


class ConsumerFreshnessTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.root = tempfile.mkdtemp(prefix="hand-fresh-")
        for platform in osal.SUPPORTED:
            osal.disable_capture_backend(platform)
            self.addCleanup(osal.disable_capture_backend, platform)

    def _answer_with(self, hand):
        import threading

        def answer():
            import time as _time
            while not capture_hand.pending_requests(self.root):
                _time.sleep(0.001)
            hand.poll_once()

        worker = threading.Thread(target=answer, daemon=True)
        worker.start()
        return worker

    def test_a_stale_frame_arrives_as_a_named_refusal(self):
        backend = capture_hand.bus_capture_backend(
            self.root, platform="windows", request_id_factory=_ids("f1"),
            clock=lambda: 1060.0)
        worker = self._answer_with(CaptureHand(
            self.root, session_probe=lambda: INTERACTIVE,
            capture=lambda: ("/tmp/old.png", ""), clock=lambda: 1000.0))
        path, detail = backend.capture()
        worker.join(timeout=10)
        self.assertIsNone(path)
        self.assertIn("stale", detail)

    def test_a_fresh_frame_passes_the_gate(self):
        backend = capture_hand.bus_capture_backend(
            self.root, platform="windows", request_id_factory=_ids("f2"),
            clock=lambda: 1002.0)
        worker = self._answer_with(CaptureHand(
            self.root, session_probe=lambda: INTERACTIVE,
            capture=lambda: ("/tmp/new.png", ""), clock=lambda: 1000.0))
        path, detail = backend.capture()
        worker.join(timeout=10)
        self.assertEqual(path, "/tmp/new.png")
        self.assertEqual(detail, "")

    def test_a_pre_envelope_hand_is_refused_after_upgrade(self):
        # A BR2 hand wrote this exact shape: a path, an answer time, and no
        # captured_at anywhere. It must not be silently treated as fresh.
        results = os.path.join(self.root, "results")
        os.makedirs(results, exist_ok=True)
        with open(os.path.join(results, "old1.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"request_id": "old1", "kind": "capture",
                       "state": INTERACTIVE, "path": "/tmp/legacy.png",
                       "detail": "", "answered_at": 1000.0}, handle)
        backend = capture_hand.bus_capture_backend(
            self.root, platform="windows", request_id_factory=_ids("old1"),
            clock=lambda: 1000.0)
        path, detail = backend.capture()
        self.assertIsNone(path)
        self.assertIn("no frame envelope", detail)

    def test_the_locked_refusal_is_not_overwritten_by_the_gate(self):
        backend = capture_hand.bus_capture_backend(
            self.root, platform="windows", request_id_factory=_ids("f3"),
            clock=lambda: 9999.0)
        worker = self._answer_with(CaptureHand(
            self.root, session_probe=lambda: LOCKED,
            capture=lambda: ("/tmp/evil.png", ""), clock=lambda: 1000.0))
        path, detail = backend.capture()
        worker.join(timeout=10)
        self.assertIsNone(path)
        self.assertIn("locked", detail)

    def test_an_impossible_window_fails_at_build_not_on_a_frame(self):
        with self.assertRaises(HandError):
            capture_hand.bus_capture_backend(self.root, max_age=-1)


if __name__ == "__main__":
    unittest.main()
