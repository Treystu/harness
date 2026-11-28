"""#703: Hermetic tests for windows_antigravity_adapter."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import scripts.windows_antigravity_adapter as agy
from driver_core.audit import AuditLog


class _FakeCrop:
    def __init__(self, payload=b"crop-bytes"):
        self._payload = payload

    def tobytes(self):
        return self._payload


class _FakeFrame:
    def __init__(self, size=(1600, 1000), crop_bytes=b"same-composer"):
        self.size = size
        self._crop_bytes = crop_bytes

    def crop(self, _region):
        return _FakeCrop(self._crop_bytes)


class AntigravityAdapterTests(unittest.TestCase):
    def test_analyze_frame_state_classifies_running_empty_staged_and_foreign(self):
        self.assertTrue(agy.analyze_frame_state(["Running command"], [])["turn_running"])
        self.assertEqual(
            agy.analyze_frame_state(["Idle"], ["Ask anything, Ctrl+L for context"])["composer_route"],
            "empty",
        )
        self.assertEqual(
            agy.analyze_frame_state(["Idle"], ["continue in full"])["composer_route"],
            "staged",
        )
        foreign = agy.analyze_frame_state(["Idle"], ["Drafting PR #280 notes"])
        self.assertEqual(foreign["composer_route"], "foreign")
        self.assertEqual(foreign["draft_excerpt"], "Drafting PR #280 notes")

    def test_load_calibration_requires_valid_calibrated_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cal.json"
            self.assertIsNone(agy.load_calibration(path))
            path.write_text('{"calibrated": false}', encoding="utf-8")
            self.assertIsNone(agy.load_calibration(path))
            path.write_text('{"calibrated": true, "hwnd": 10, "sha256": "abc"}', encoding="utf-8")
            self.assertEqual(agy.load_calibration(path)["hwnd"], 10)

    def test_calibrate_antigravity_is_read_only_and_seals_audit_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "evidence"
            cal = Path(tmp) / "cal.json"
            win = Mock(process=23768, title="Harness - Antigravity")
            frame = _FakeFrame()
            with patch.object(agy, "AntigravityWindow", return_value=win), \
                 patch.object(agy, "capture_window_image", return_value=(frame, out / "cal.png", "deadbeef", 99)), \
                 patch.object(agy, "read_ocr_lines", side_effect=[["Running"], ["Ask anything"]]):
                receipt = agy.calibrate_antigravity(out, calibration_file=cal, head_sha="08ce64fe")
            self.assertTrue(receipt["calibrated"])
            self.assertTrue(receipt["turn_running"])
            self.assertEqual(receipt["composer_route"], "running")
            self.assertEqual(receipt["head_sha"], "08ce64fe")
            self.assertTrue(AuditLog(out / "antigravity-calibration.jsonl").verify().ok)
            self.assertTrue(agy.load_calibration(cal)["calibrated"])

    def test_execute_antigravity_dispatch_refuses_uncalibrated(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "antigravity-adapter-not-calibrated"):
                agy.execute_antigravity_dispatch(tmp, 999, {"thread": "antigravity"}, calibration_file=Path(tmp) / "missing.json")

    def test_execute_antigravity_dispatch_running_turn_sends_zero_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            cal = Path(tmp) / "cal.json"
            cal.write_text('{"calibrated": true, "hwnd": 10, "sha256": "abc"}', encoding="utf-8")
            out = Path(tmp) / "run"
            win = Mock(process=23768, title="Harness - Antigravity", api=Mock(foreground=lambda: 10))
            win.require_window.return_value = 10
            frame = _FakeFrame()
            with patch.object(agy, "AntigravityWindow", return_value=win), \
                 patch.object(agy, "capture_window_image", return_value=(frame, out / "b.png", "h1", 10)), \
                 patch.object(agy, "read_ocr_lines", side_effect=[["Cancel", "Running"], [""]]), \
                 patch.object(agy.osal, "_WindowsInputApi") as inp:
                status = agy.execute_antigravity_dispatch(out, 1001, {"thread": "antigravity"}, calibration_file=cal)
            self.assertIn("already in a turn; no input sent", status)
            inp.assert_not_called()
            self.assertTrue(AuditLog(out / "driver.jsonl").verify().ok)

    def test_execute_antigravity_dispatch_preserves_foreign_draft_send_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            cal = Path(tmp) / "cal.json"
            cal.write_text('{"calibrated": true, "hwnd": 10, "sha256": "abc"}', encoding="utf-8")
            out = Path(tmp) / "run"
            win = Mock(process=23768, title="Harness - Antigravity", api=Mock(foreground=lambda: 10))
            win.require_window.return_value = 10
            frame = _FakeFrame()
            input_mock = Mock()
            input_mock.client_to_screen.side_effect = [(1200, 900), (1540, 940)]
            with patch.object(agy, "AntigravityWindow", return_value=win), \
                 patch.object(agy, "capture_window_image", return_value=(frame, out / "b.png", "h1", 10)), \
                 patch.object(agy, "read_ocr_lines", side_effect=[["Idle"], ["Existing user draft"]]), \
                 patch.object(agy, "activate_exact", return_value=True), \
                 patch.object(agy, "composer_unchanged", return_value=True), \
                 patch.object(agy.osal, "_WindowsInputApi", return_value=input_mock):
                status = agy.execute_antigravity_dispatch(out, 1002, {"thread": "antigravity"}, calibration_file=cal)
            self.assertIn("send-only; foreign staged draft preserved", status)
            input_mock.type_text.assert_not_called()
            self.assertEqual(input_mock.click.call_count, 2)
            marker = json.loads((out / "antigravity-send-1002.json").read_text(encoding="utf-8"))
            self.assertEqual(marker["route"], "foreign")
            self.assertTrue(AuditLog(out / "driver.jsonl").verify().ok)

    def test_execute_antigravity_dispatch_enforces_freshness_and_unchanged_composer(self):
        with tempfile.TemporaryDirectory() as tmp:
            cal = Path(tmp) / "cal.json"
            cal.write_text('{"calibrated": true, "hwnd": 10, "sha256": "abc"}', encoding="utf-8")
            out = Path(tmp) / "run"
            win = Mock(process=23768, title="Harness - Antigravity", api=Mock(foreground=lambda: 10))
            win.require_window.return_value = 10
            frame = _FakeFrame()
            with patch.object(agy, "AntigravityWindow", return_value=win), \
                 patch.object(agy, "capture_window_image", return_value=(frame, out / "b.png", "h1", 10)), \
                 patch.object(agy, "read_ocr_lines", side_effect=[["Idle"], ["Ask anything"]]), \
                 patch.object(agy, "activate_exact", return_value=True), \
                 patch.object(agy.time, "monotonic", side_effect=[100.0, 165.0]):
                with self.assertRaisesRegex(RuntimeError, "expired before send"):
                    agy.execute_antigravity_dispatch(out, 1003, {"thread": "antigravity"}, calibration_file=cal)


if __name__ == "__main__":
    unittest.main()
