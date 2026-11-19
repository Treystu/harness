"""#480 BR6: the acceptance battery reports what it observed, and nothing more.

The battery's whole value is that it cannot be talked into a pass. So the tests
below are mostly about the refusals: a hermetic run is ``blocked`` on probe 1,
a live run with no reader is ``blocked`` rather than met, a reader that raises
is ``failed``, and a receipt always carries every key.
"""
import contextlib
import io
import json
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from driver_core import bridge_battery as bb
from driver_core import capture_hand as hand


def _root():
    directory = tempfile.TemporaryDirectory(prefix="battery-test-")
    return directory


def _reader(directory, payload=b"live-frame"):
    path = os.path.join(directory, "live.png")
    with open(path, "wb") as handle:
        handle.write(payload)
    calls = []

    def capture():
        calls.append(1)
        return path, "captured by the test reader"

    capture.calls = calls
    capture.path = path
    return capture


class HermeticRunTests(unittest.TestCase):
    def test_a_hermetic_run_meets_five_probes_and_blocks_the_live_one(self):
        receipt = bb.run_battery()
        states = {probe["id"]: probe["state"] for probe in receipt["probes"]}
        self.assertEqual(receipt["schema"], bb.BATTERY_SCHEMA)
        self.assertEqual(receipt["total"], 6)
        self.assertEqual(receipt["met"], 5)
        self.assertEqual(states["live_capture"], bb.BLOCKED)
        self.assertFalse(receipt["passed"])
        self.assertEqual(receipt["blocked"], ["live_capture"])
        self.assertEqual(bb.exit_code(receipt), 2)

    def test_the_blocked_receipt_carries_the_owner_runbook(self):
        receipt = bb.run_battery()
        probe = receipt["probes"][0]
        self.assertIn("runbook", probe["evidence"])
        self.assertIn("8765", probe["evidence"]["runbook"])
        self.assertIn("--live", probe["evidence"]["runbook"])

    def test_every_probe_is_present_with_every_key(self):
        receipt = bb.run_battery()
        self.assertEqual(tuple(p["id"] for p in receipt["probes"]), bb.PROBE_IDS)
        for probe in receipt["probes"]:
            self.assertEqual(set(probe), {"id", "state", "detail", "evidence"})
            self.assertIsInstance(probe["evidence"], dict)

    def test_a_named_root_is_used_and_left_in_place(self):
        with _root() as directory:
            receipt = bb.run_battery(root=directory)
            self.assertTrue(os.path.isdir(directory))
            self.assertFalse(receipt["passed"])
            self.assertTrue(os.listdir(directory))

    def test_a_failed_live_probe_does_not_poison_the_other_probes(self):
        """An unanswered live request must not become probe 3's answer."""
        with tempfile.TemporaryDirectory() as directory:
            reader = bb.live_reader(directory, timeout=0.05)
            receipt = bb.run_battery(live=True, capture=reader, root=directory)
        states = {p["id"]: p["state"] for p in receipt["probes"]}
        self.assertEqual(states["live_capture"], bb.FAILED)
        self.assertEqual(receipt["met"], 5)
        self.assertEqual(
            [p["id"] for p in receipt["probes"] if p["state"] == bb.FAILED],
            ["live_capture"])

    def test_a_named_root_can_run_twice(self):
        """A retry on the operator's root must not read the last run's answers."""
        with _root() as directory:
            first = bb.run_battery(root=directory)
            second = bb.run_battery(root=directory)
        self.assertEqual(first["met"], 5)
        self.assertEqual(second["met"], 5)
        self.assertEqual(second["blocked"], ["live_capture"])
        self.assertFalse(
            any(p["state"] == bb.FAILED for p in second["probes"]))


class LiveProbeTests(unittest.TestCase):
    def test_a_live_run_with_a_reader_meets_all_six(self):
        with _root() as directory:
            capture = _reader(directory)
            receipt = bb.run_battery(live=True, capture=capture,
                                     root=directory)
            self.assertEqual(receipt["met"], 6)
            self.assertTrue(receipt["passed"])
            self.assertEqual(bb.exit_code(receipt), 0)
            self.assertEqual(len(capture.calls), 1)

    def test_live_mode_without_a_reader_is_blocked_not_met(self):
        with _root() as directory:
            receipt = bb.run_battery(live=True, root=directory)
            self.assertEqual(receipt["probes"][0]["state"], bb.BLOCKED)
            self.assertFalse(receipt["passed"])
            self.assertEqual(bb.exit_code(receipt), 2)

    def test_a_live_reader_that_raises_is_a_failure(self):
        def capture():
            raise RuntimeError("display gone")

        with _root() as directory:
            receipt = bb.run_battery(live=True, capture=capture,
                                     root=directory)
            probe = receipt["probes"][0]
            self.assertEqual(probe["state"], bb.FAILED)
            self.assertIn("display gone", probe["detail"])
            self.assertEqual(bb.exit_code(receipt), 1)

    def test_a_live_reader_that_returns_no_frame_is_a_failure(self):
        with _root() as directory:
            receipt = bb.run_battery(live=True,
                                     capture=lambda: (None, "lock race"),
                                     root=directory)
            probe = receipt["probes"][0]
            self.assertEqual(probe["state"], bb.FAILED)
            self.assertIn("lock race", probe["detail"])
            self.assertEqual(bb.exit_code(receipt), 1)

    def test_a_live_frame_outside_the_window_is_a_failure(self):
        with _root() as directory:
            capture = _reader(directory)
            receipt = bb.run_battery(
                live=True, capture=capture, root=directory,
                max_age=0.0, clock=lambda: time.time() + 30.0)
            probe = receipt["probes"][0]
            self.assertEqual(probe["state"], bb.FAILED)
            self.assertFalse(probe["evidence"]["fresh"])
            self.assertIn("stale", probe["detail"])


class StaleProbeTests(unittest.TestCase):
    def test_a_delayed_frame_refuses_and_names_its_age(self):
        with _root() as directory:
            probe = bb.probe_stale_frame(root=directory,
                                         clock=time.time, max_age=5.0)
            self.assertEqual(probe["state"], bb.MET)
            self.assertIn("stale", probe["detail"])
            self.assertEqual(probe["evidence"]["age_s"], 30.0)
            self.assertEqual(probe["evidence"]["window_s"], 5.0)

    def test_the_gate_still_accepts_a_fresh_frame(self):
        with _root() as directory:
            path = os.path.join(directory, "fresh.png")
            with open(path, "wb") as handle:
                handle.write(b"fresh")
            envelope = hand.frame_envelope(path=path, captured_at=time.time(),
                                           state=hand.INTERACTIVE)
            ok, why = hand.check_freshness({"path": path, "frame": envelope},
                                           max_age=5.0)
            self.assertTrue(ok, why)


class LockedProbeTests(unittest.TestCase):
    def test_a_locked_hand_returns_the_condition_and_never_reads(self):
        with _root() as directory:
            probe = bb.probe_locked(root=directory, clock=time.time)
            self.assertEqual(probe["state"], bb.MET)
            self.assertEqual(probe["evidence"]["reader_calls"], 0)
            self.assertIsNone(probe["evidence"]["path"])
            self.assertIsNone(probe["evidence"]["frame"])
            self.assertEqual(probe["evidence"]["state"], hand.LOCKED)


class WrongTokenProbeTests(unittest.TestCase):
    def test_all_three_refusals_name_their_gate(self):
        with _root() as directory:
            probe = bb.probe_wrong_token(root=directory, clock=time.time)
            self.assertEqual(probe["state"], bb.MET)
            evidence = probe["evidence"]
            self.assertIn("not on this bridge's allowlist",
                          evidence["intruder_seat"])
            self.assertIn("no capture grant", evidence["ungranted"])
            self.assertIn("was issued to seat",
                          evidence["grant_for_other_seat"])
            self.assertEqual(evidence["frames_returned"], [None, None, None])


class FingerprintProbeTests(unittest.TestCase):
    def test_a_static_screen_costs_one_describe_across_polls(self):
        with _root() as directory:
            probe = bb.probe_fingerprint_stability(
                root=directory, clock=time.time, polls=6)
            self.assertEqual(probe["state"], bb.MET)
            self.assertEqual(probe["evidence"]["describe_runs"], 1)
            self.assertEqual(probe["evidence"]["deduped"], 5)

    def test_one_poll_is_refused_as_a_stability_probe(self):
        with _root() as directory:
            probe = bb.probe_fingerprint_stability(
                root=directory, clock=time.time, polls=1)
            self.assertEqual(probe["state"], bb.FAILED)


class NegativeContentProbeTests(unittest.TestCase):
    def test_changed_content_yields_a_new_fingerprint_and_value(self):
        with _root() as directory:
            probe = bb.probe_negative_content(root=directory,
                                              clock=time.time)
            self.assertEqual(probe["state"], bb.MET)
            self.assertNotEqual(probe["evidence"]["fingerprint_before"],
                                probe["evidence"]["fingerprint_after"])
            self.assertEqual(probe["evidence"]["fields_after"]["model"],
                             "model-B")
            self.assertFalse(probe["evidence"]["deduped_after"])


class LiveWiringTests(unittest.TestCase):
    """Probe 1 must run the bridge's consumer, not a reader built here."""

    def test_live_reader_is_the_bus_consumer(self):
        class _Backend:
            def capture(self):
                return "/tmp/frame.png", "captured"

        with mock.patch.object(bb.hand, "bus_capture_backend",
                               return_value=_Backend()) as build:
            reader = bb.live_reader("/tmp/ledger", seat="driver",
                                    grant="g1", timeout=3.0, max_age=2.5)
            self.assertEqual(reader(), ("/tmp/frame.png", "captured"))
        build.assert_called_once()
        kwargs = build.call_args.kwargs
        self.assertEqual(kwargs["seat"], "driver")
        self.assertEqual(kwargs["grant"], "g1")
        self.assertEqual(kwargs["timeout"], 3.0)
        self.assertEqual(kwargs["max_age"], 2.5)

    def test_the_live_cli_refuses_a_temporary_root(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                bb.main(["--live"])
        self.assertEqual(caught.exception.code, 2)

    def test_the_live_cli_runs_probe_one_through_the_reader(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "live.png")
            with open(path, "wb") as handle:
                handle.write(b"live-frame")
            out = os.path.join(directory, "receipt.json")
            with mock.patch.object(
                    bb, "live_reader",
                    return_value=lambda: (path, "captured")) as build:
                with contextlib.redirect_stdout(io.StringIO()):
                    code = bb.main(["--live", "--root", directory,
                                    "--max-age", "1.5", "--out", out])
            self.assertEqual(code, 0)
            self.assertEqual(build.call_args.kwargs["max_age"], 1.5)
            with open(out, encoding="utf-8") as handle:
                receipt = json.load(handle)
            self.assertTrue(receipt["live"])
            self.assertEqual(receipt["met"], 6)
            probe = receipt["probes"][0]
            self.assertEqual(probe["evidence"]["path"], path)
            self.assertEqual(len(probe["evidence"]["fingerprint"]), 64)

    def test_probe_one_travels_the_bus_to_a_hand_and_back(self):
        """The whole wire, with a fake reader where the desktop would be.

        Probe 1 is run against the real ``live_reader`` and a real
        :class:`CaptureHand` in another thread over one ledger root; only
        the pixels are a fixture, so no unsupervised capture happens.
        """
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "frame.png")
            with open(path, "wb") as handle:
                handle.write(b"live-frame")
            worker = bb.hand.CaptureHand(
                directory, session_probe=lambda: bb.hand.INTERACTIVE,
                capture=lambda: (path, ""), describe=lambda: ({}, ""),
                seats=("driver",), require_grant=True)
            stop = threading.Event()

            def answer():
                while not stop.is_set():
                    worker.poll_once()
                    time.sleep(0.005)

            thread = threading.Thread(target=answer, daemon=True)
            thread.start()
            try:
                grant = bb.hand.issue_capture_grant(directory, seat="driver")
                reader = bb.live_reader(directory, seat="driver",
                                        grant=grant["grant_id"], timeout=5.0)
                probe = bb.probe_live_capture(
                    live=True, capture=reader, clock=time.time,
                    max_age=bb.hand.DEFAULT_MAX_AGE)
            finally:
                stop.set()
                thread.join(timeout=5.0)
            self.assertEqual(probe["state"], bb.MET, probe["detail"])
            self.assertEqual(probe["evidence"]["path"], path)
            self.assertTrue(probe["evidence"]["fresh"])

    def test_a_live_reader_refusal_is_a_failed_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            out = os.path.join(directory, "receipt.json")
            with mock.patch.object(
                    bb, "live_reader",
                    return_value=lambda: (None, "locked")):
                with contextlib.redirect_stdout(io.StringIO()):
                    code = bb.main(["--live", "--root", directory,
                                    "--out", out])
            self.assertEqual(code, 1)
            with open(out, encoding="utf-8") as handle:
                receipt = json.load(handle)
            self.assertEqual(receipt["probes"][0]["state"], bb.FAILED)


class ReceiptRenderingTests(unittest.TestCase):
    def test_the_receipt_is_json_serialisable_and_renders(self):
        receipt = bb.run_battery()
        text = json.dumps(receipt, sort_keys=True)
        self.assertIn(bb.BATTERY_SCHEMA, text)
        rendered = bb.format_receipt(receipt)
        self.assertIn("live=False", rendered)
        self.assertIn("blocked: live_capture", rendered)

    def test_run_battery_reports_a_dated_run(self):
        before = time.time()
        receipt = bb.run_battery()
        self.assertGreaterEqual(receipt["ran_at"], before)


if __name__ == "__main__":
    unittest.main()
