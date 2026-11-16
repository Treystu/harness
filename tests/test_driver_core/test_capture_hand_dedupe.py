"""#480 BR3: the frame fingerprint, and the dedupe that saves the describe call.

Acceptance items 5 and 6 of #480 are about the fingerprint doing real work: a
static screen must cost zero describe (therefore zero Jev) calls across N polls,
and a changed screen must produce a new fingerprint whose extraction reads the
*new* value. Neither was provable before this module, because the hand had no
fingerprint at all.

These tests drive the hand directly -- no desktop, no driver-core service -- so
they hold whether or not the machine's vision driver is ready, and they fail if
the dedupe ever becomes silent (a describe that skips a reader it should have
run is worse than a wasted call).
"""
import os
import tempfile
import unittest

from driver_core.capture_hand import (CAPTURED_AT_FIELD, FINGERPRINT_FIELD,
                                      FRAME_FIELD, LOCKED_DETAIL, CaptureHand,
                                      HandError, frame_envelope,
                                      frame_fingerprint, issue_capture_grant,
                                      post_capture_request, read_grant,
                                      read_result, session_state)


class _Rig:
    """A hand over a temp root with a fake screen and a counting reader."""

    def __init__(self, root, *, content=b"screen-A", state="interactive",
                 **hand_kwargs):
        self.root = root
        self.content = content
        self.frame_path = os.path.join(root, "frame.png")
        self.captures = 0
        self.describes = 0
        self._state = state
        self.hand = CaptureHand(
            root,
            session_probe=lambda: self._state,
            capture=self._capture,
            describe=self._describe,
            clock=lambda: 1000.0,
            **hand_kwargs)

    def _capture(self):
        self.captures += 1
        with open(self.frame_path, "wb") as handle:
            handle.write(self.content)
        return self.frame_path, "captured"

    def _describe(self):
        self.describes += 1
        # What a real reader reports: the value currently on the screen.
        return {"model_selection": self.content.decode("utf-8")}, "described"

    def ask_capture(self, rid):
        post_capture_request(self.root, rid, "capture")
        self.hand.poll_once()
        return read_result(self.root, rid, timeout=0)

    def ask_capture_with_grant(self, rid, grant_id):
        post_capture_request(self.root, rid, "capture", grant=grant_id)
        self.hand.poll_once()
        return read_result(self.root, rid, timeout=0)

    def ask_describe(self, rid, fingerprint=None):
        post_capture_request(self.root, rid, "describe", fingerprint=fingerprint)
        self.hand.poll_once()
        return read_result(self.root, rid, timeout=0)


class FingerprintTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "f.bin")

    def _write(self, content):
        with open(self.path, "wb") as handle:
            handle.write(content)
        return self.path

    def test_digest_is_stable_for_identical_bytes(self):
        self.assertEqual(frame_fingerprint(self._write(b"abc")),
                         frame_fingerprint(self._write(b"abc")))

    def test_digest_changes_with_content(self):
        first = frame_fingerprint(self._write(b"screen-A"))
        second = frame_fingerprint(self._write(b"screen-B"))
        self.assertNotEqual(first, second)

    def test_digest_is_a_sha256_hex_string(self):
        digest = frame_fingerprint(self._write(b"abc"))
        self.assertEqual(len(digest), 64)
        int(digest, 16)

    def test_unreadable_frame_is_refused_by_name(self):
        with self.assertRaises(HandError) as ctx:
            frame_fingerprint(os.path.join(self.tmp.name, "missing.png"))
        self.assertIn("could not be read", str(ctx.exception))

    def test_envelope_carries_the_digest_when_given(self):
        env = frame_envelope(path="p.png", captured_at=1.0, state="interactive",
                             fingerprint="ab" * 32)
        self.assertEqual(env[FINGERPRINT_FIELD], "ab" * 32)
        self.assertEqual(env[CAPTURED_AT_FIELD], 1.0)

    def test_envelope_refuses_a_blank_digest(self):
        with self.assertRaises(HandError):
            frame_envelope(path="p.png", captured_at=1.0,
                           state="interactive", fingerprint="  ")


class DedupeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_capture_answer_carries_the_fingerprint(self):
        rig = _Rig(self.tmp.name)
        result = rig.ask_capture("r1")
        envelope = result[FRAME_FIELD]
        self.assertEqual(envelope[FINGERPRINT_FIELD], frame_fingerprint(rig.frame_path))

    def test_static_screen_n_polls_runs_the_reader_once(self):
        # Acceptance item 5, hermetically: N polls of an unchanged screen cost
        # one describe, so N-1 Jev calls are never made.
        rig = _Rig(self.tmp.name)
        fingerprints = []
        for index in range(5):
            result = rig.ask_capture(f"c{index}")
            fingerprints.append(result[FRAME_FIELD][FINGERPRINT_FIELD])
            rig.ask_describe(f"d{index}", fingerprint=fingerprints[-1])
        self.assertEqual(len(set(fingerprints)), 1)
        self.assertEqual(rig.captures, 5)
        self.assertEqual(rig.describes, 1)

    def test_unchanged_describe_is_marked_deduped_and_reuses_fields(self):
        rig = _Rig(self.tmp.name)
        first = rig.ask_capture("c1")[FRAME_FIELD][FINGERPRINT_FIELD]
        one = rig.ask_describe("d1", fingerprint=first)
        two = rig.ask_describe("d2", fingerprint=first)
        self.assertNotIn("deduped", one)
        self.assertTrue(two.get("deduped"))
        self.assertEqual(one["fields"], two["fields"])
        self.assertEqual(rig.describes, 1)
        self.assertIn("unchanged screen", two["detail"])

    def test_changed_screen_gets_a_new_fingerprint_and_new_extraction(self):
        # Acceptance item 6, hermetically: change the selection, the next frame
        # fingerprints differently and the extraction reads the NEW value.
        rig = _Rig(self.tmp.name, content=b"model-A")
        first = rig.ask_capture("c1")[FRAME_FIELD][FINGERPRINT_FIELD]
        rig.ask_describe("d1", fingerprint=first)

        rig.content = b"model-B"
        second = rig.ask_capture("c2")[FRAME_FIELD][FINGERPRINT_FIELD]
        described = rig.ask_describe("d2", fingerprint=second)

        self.assertNotEqual(first, second)
        self.assertNotIn("deduped", described)
        self.assertEqual(described["fields"]["model_selection"], "model-B")
        self.assertEqual(rig.describes, 2)

    def test_a_capture_ending_the_dedupe_window_does_not_reuse_old_fields(self):
        # A new capture of the same pixels is still "the same screen", so the
        # second describe may dedupe -- but with the fields of THAT frame.
        rig = _Rig(self.tmp.name, content=b"same")
        first = rig.ask_capture("c1")[FRAME_FIELD][FINGERPRINT_FIELD]
        one = rig.ask_describe("d1", fingerprint=first)
        second = rig.ask_capture("c2")[FRAME_FIELD][FINGERPRINT_FIELD]
        two = rig.ask_describe("d2", fingerprint=second)
        self.assertEqual(first, second)
        self.assertEqual(one["fields"], two["fields"])
        self.assertEqual(rig.describes, 1)

    def test_no_fingerprint_is_never_deduped(self):
        # Silence must not be read as "unchanged": a caller that names no frame
        # gets a fresh describe every time.
        rig = _Rig(self.tmp.name)
        rig.ask_capture("c1")
        rig.ask_describe("d1")
        rig.ask_describe("d2")
        self.assertEqual(rig.describes, 2)

    def test_a_fingerprint_that_is_not_the_last_frame_is_described(self):
        rig = _Rig(self.tmp.name)
        rig.ask_capture("c1")
        rig.ask_describe("d1", fingerprint="f" * 64)
        self.assertEqual(rig.describes, 1)
        self.assertNotIn("deduped", read_result(self.tmp.name, "d1", timeout=0))

    def test_an_unreadable_frame_is_still_served_without_a_digest(self):
        # The reader owns the path; the hand may not be able to open it (a
        # remote or privilege-held file). The frame is still the frame.
        rig = _Rig(self.tmp.name)
        rig.hand._capture = lambda: (os.path.join(self.tmp.name, "gone.png"),
                                     "captured elsewhere")
        result = rig.ask_capture("c1")
        self.assertTrue(result["path"].endswith("gone.png"))
        self.assertNotIn(FINGERPRINT_FIELD, result[FRAME_FIELD])
        self.assertIn("could not be read", result["unfingerprinted"])
        # ``detail`` stays the reader's own words: the note has its own key.
        self.assertEqual(result["detail"], "captured elsewhere")

    def test_dedupe_can_be_switched_off(self):
        rig = _Rig(self.tmp.name, dedupe=False)
        fingerprint = rig.ask_capture("c1")[FRAME_FIELD][FINGERPRINT_FIELD]
        rig.ask_describe("d1", fingerprint=fingerprint)
        rig.ask_describe("d2", fingerprint=fingerprint)
        self.assertEqual(rig.describes, 2)


class GrantTests(unittest.TestCase):
    """Acceptance item 4: an ungranted or wrong-seat ask is refused by name."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_no_grant_is_refused_by_name_and_takes_no_frame(self):
        rig = _Rig(self.tmp.name, require_grant=True)
        result = rig.ask_capture("r1")
        self.assertIn("no capture grant", result["detail"])
        self.assertIsNone(result[FRAME_FIELD])
        self.assertEqual(rig.captures, 0)

    def test_a_grant_issued_to_another_seat_is_refused(self):
        rig = _Rig(self.tmp.name, require_grant=True, seats=("driver",))
        grant = issue_capture_grant(self.tmp.name, seat="other",
                                    clock=lambda: 1000.0)
        post_capture_request(self.tmp.name, "r1", "capture", seat="driver",
                             grant=grant["grant_id"])
        rig.hand.poll_once()
        result = read_result(self.tmp.name, "r1", timeout=0)
        self.assertIn("was issued to seat 'other'", result["detail"])
        self.assertEqual(rig.captures, 0)

    def test_one_grant_buys_exactly_one_frame(self):
        rig = _Rig(self.tmp.name, require_grant=True)
        grant = issue_capture_grant(self.tmp.name, clock=lambda: 1000.0)
        first = rig.ask_capture_with_grant("r1", grant["grant_id"])
        second = rig.ask_capture_with_grant("r2", grant["grant_id"])
        self.assertIsNotNone(first[FRAME_FIELD])
        self.assertIsNone(second[FRAME_FIELD])
        self.assertIn("already been used", second["detail"])
        self.assertEqual(rig.captures, 1)
        self.assertIsNotNone(read_grant(self.tmp.name,
                                        grant["grant_id"])["used_at"])


class LockRuleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_locked_returns_the_condition_and_takes_no_frame(self):
        rig = _Rig(self.tmp.name, state="locked")
        result = rig.ask_capture("r1")
        self.assertEqual(result["state"], "locked")
        self.assertEqual(result["detail"], LOCKED_DETAIL)
        self.assertIsNone(result[FRAME_FIELD])
        self.assertEqual(rig.captures, 0)

    def test_locked_describe_runs_no_reader(self):
        rig = _Rig(self.tmp.name, state="locked")
        rig.ask_describe("d1")
        self.assertEqual(rig.describes, 0)

    def test_seat_outside_the_allowlist_is_refused_by_name(self):
        rig = _Rig(self.tmp.name, seats=("driver",))
        post_capture_request(self.tmp.name, "r1", "capture", seat="intruder")
        rig.hand.poll_once()
        result = read_result(self.tmp.name, "r1", timeout=0)
        self.assertIn("not on this bridge's allowlist", result["detail"])
        self.assertEqual(rig.captures, 0)

    def test_kill_switch_stops_the_bridge_before_any_reader(self):
        rig = _Rig(self.tmp.name)
        with open(os.path.join(self.tmp.name, "STOP"), "w", encoding="utf-8") as fh:
            fh.write("stopped")
        rig.ask_capture("r1")
        result = read_result(self.tmp.name, "r1", timeout=0)
        self.assertIn("kill switch", result["detail"])
        self.assertEqual(rig.captures, 0)

    def test_status_reports_the_gates_without_touching_the_screen(self):
        rig = _Rig(self.tmp.name, seats=("driver",))
        status = rig.hand.status()
        self.assertEqual(status["state"], session_state(lambda: "interactive"))
        self.assertEqual(status["seats"], ["driver"])
        self.assertFalse(status["stopped"])
        self.assertEqual(rig.captures, 0)


if __name__ == "__main__":
    unittest.main()
