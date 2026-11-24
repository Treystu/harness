"""Tests for the FreeBuff watch, runner, and SCM project census."""

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

try:
    from PIL import Image
except ImportError:
    class _FakeImage:
        def __init__(self, size, color="black"):
            self.size = size
            self.width, self.height = size
            self._color = str(color)

        def crop(self, _region):
            return _FakeImage(self.size, self._color)

        def tobytes(self):
            return self._color.encode("utf-8")

    class Image:  # type: ignore[no-redef]
        @staticmethod
        def new(_mode, size, color="black"):
            return _FakeImage(size, color)

from driver_core.audit import AuditLog
from scripts import windows_freebuff_runner as runner
from scripts import windows_freebuff_t4 as census
from scripts import windows_freebuff_watch as watch
from scripts.windows_freebuff_dispatch import Dispatch


class FreebuffWatchTests(unittest.TestCase):
    def test_legacy_census_pause_does_not_block_queue(self):
        known = {"paused.json", "armed.json"}
        receipts = {}
        write = Mock()
        run = Mock()
        with patch.object(watch, "local_control_state", lambda: {"enabled": True, "paused": False}), \
             patch.object(watch, "worktree_head", lambda: "pushed-head"), \
             patch.dict("os.environ", {"HARNESS_VISION_HEAD": "pushed-head"}), \
             patch.object(watch, "checkpoints", lambda: known), \
             patch.object(watch, "read_checkpoint", lambda name: {"state": "adapter-unavailable"}), \
             patch.object(watch, "pause_requested", lambda: None), \
             patch.object(watch, "validate_receipts", lambda: receipts), \
             patch.object(watch, "checkpoint", write), \
             patch.object(watch, "issue_comment", Mock()), \
             patch.object(watch, "run_restoration", lambda r, k: False), \
             patch.object(watch, "run_burn", run):
            watch.main()

        self.assertEqual(write.call_args.args[0], f"parked-{watch.CENSUS}.json")
        run.assert_called_once_with(receipts, known)

    def test_owner_pause_preempts_any_admission(self):
        write = Mock()
        run = Mock()
        with patch.object(watch, "local_control_state", lambda: {"enabled": True, "paused": False}), \
             patch.object(watch, "worktree_head", lambda: "pushed-head"), \
             patch.object(watch, "checkpoints", lambda: {"armed.json"}), \
             patch.object(watch, "pause_requested", lambda: 123), \
             patch.object(watch, "issue_comment", Mock()), \
             patch.object(watch, "checkpoint", write), \
             patch.object(watch, "run_burn", run):
            watch.main()

        write.assert_called_once_with("owner-paused.json", {"dispatch": 123, "state": "owner-paused"})
        run.assert_not_called()

    def test_github_response_uses_utf8(self):
        result = Mock(returncode=0, stdout='{"body":"RESTART — ready"}')
        run = Mock(return_value=result)
        with patch.object(runner.subprocess, "run", run):
            self.assertEqual(runner.api("example"), {"body": "RESTART — ready"})
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")

    def test_interrupted_items_skip_to_next_unclaimed_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            known = {f"claim-{watch.CENSUS}-2ae32937.json", f"claim-{watch.BURNDOWN}-0d7e2f37.json"}
            receipts = {watch.BURN_QUEUE: {"created_at": datetime.now(timezone.utc).isoformat(), "body": "pinned"}}
            write = Mock()
            execute = Mock(return_value=1)
            with patch.dict("os.environ", {"LOCALAPPDATA": tmp}), \
                 patch.object(watch, "guard_approval", Mock()), \
                 patch.object(watch, "desktop_idle", lambda: True), \
                 patch.object(watch, "checkpoint", write), \
                 patch.object(watch, "execute", execute):
                watch.run_burn(receipts, known)

        self.assertEqual(execute.call_args.args[2]["thread"], "7d4a9b14")
        self.assertEqual(
            [args.args[0] for args in write.call_args_list],
            [f"claim-{watch.BURNDOWN}-7d4a9b14.json", f"result-{watch.BURNDOWN}-7d4a9b14.json"],
        )

    def test_project_roster_rejects_unbounded_accessibility_list(self):
        group = {"name": "SCMessenger", "kind": "ControlType.List", "partial": True,
                 "children": [{"name": "SCMessenger", "kind": "ControlType.ListItem"}]}
        with self.assertRaisesRegex(RuntimeError, "partial"):
            census.project_roster({"groups": [group]})

    def test_census_reidentifies_row_on_fresh_stable_frame(self):
        old = Image.new("RGB", (400, 200), "black")
        fresh = Image.new("RGB", (400, 200), "white")
        driver = Mock()
        driver.frame.side_effect = [fresh, fresh]
        driver.read_roster.return_value = [{"text": "SCMessenger"}]
        driver.locate_exact_text.return_value = [150, 100]
        census.visual_select_row(driver, old, "SCMessenger", 100, "candidate")
        self.assertIs(driver.locate_exact_text.call_args.args[1], fresh)
        self.assertEqual(driver.locate_exact_text.call_args.kwargs["scale"], 2)
        driver.yes.assert_called_once()
        driver.act.assert_called_once()

    def test_census_refuses_row_changed_after_verification(self):
        driver = Mock()
        old = Image.new("RGB", (400, 200), "white")
        driver.frame.side_effect = [old, Image.new("RGB", (400, 200), "black")]
        driver.read_roster.return_value = [{"text": "SCMessenger"}]
        with self.assertRaisesRegex(RuntimeError, "changed before selection"):
            census.visual_select_row(driver, old, "SCMessenger", 100, "candidate")
        driver.act.assert_not_called()

    def test_census_tolerates_only_small_ocr_differences_for_navigation(self):
        self.assertTrue(census.similar_census_label("SCMessenger Audit Lar", "SCMessenger Audit Lan"))
        self.assertFalse(census.similar_census_label("SCMessenger Audit Lar", "SCMessenger Cloud Cure"))

    def test_census_inventory_refuses_duplicate_or_visually_ambiguous_titles(self):
        census.validate_census_inventory(["SCMessenger", "SCMessenger Audit Lar"])
        with self.assertRaisesRegex(RuntimeError, "ambiguous"):
            census.validate_census_inventory(["SCMessenger", "SCMessenger"])
        with self.assertRaisesRegex(RuntimeError, "ambiguous"):
            census.validate_census_inventory(["SCMessenger Audit Lar", "SCMessenger Audit Lan"])

    def test_census_inventories_before_opening_and_tolerates_reordering(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            frame = Image.new("RGB", (400, 200))
            reads = iter([["SCMessenger", "SCMessenger Audit"], ["SCMessenger Audit", "SCMessenger"],
                          ["SCMessenger Audit", "SCMessenger"]])
            selected = []
            driver = Mock()
            driver.output = tmp_path
            driver.scroll_sidebar_to_top.return_value = frame
            driver.frame.return_value = frame
            with patch.object(census, "visual_project_pages",
                              lambda *args: iter([(frame, 0, [(name, 100) for name in next(reads)])])), \
                 patch.object(census, "visual_select_row",
                              lambda drv, frm, label, y, step: selected.append(label) or label), \
                 patch.object(census, "observe_census_candidate",
                              lambda drv, frm, label, index: {"title": label}), \
                 patch.object(census, "census_signature", lambda fields: False), \
                 patch.object(census.time, "sleep", lambda _: None):
                with self.assertRaisesRegex(RuntimeError, "0 verified matches across 2 rows"):
                    census.visual_census(driver, frame)
            self.assertEqual(selected, ["SCMessenger", "SCMessenger Audit"])
            self.assertTrue((tmp_path / "project-roster.json").is_file())

    def test_census_jev_verifies_visible_prefix_without_guessing_clipped_suffix(self):
        frame = Image.new("RGB", (400, 200), "white")
        driver = Mock()
        driver.frame.side_effect = [frame, frame]
        driver.read_roster.return_value = [{"text": "SCMessenger Audit Lar"}]
        census.visual_select_row(driver, frame, "SCMessenger Audit Lar", 100, "candidate")
        self.assertIn("SCMessenger Audit'", driver.yes.call_args.args[2])
        self.assertNotIn("Lar", driver.yes.call_args.args[2])

    def test_census_scrolls_past_sticky_footer_after_project_heading(self):
        def line(text, x, y):
            return {"text": text, "words": [{"text": text, "x": 2 * (x - 95), "y": 2 * (y - 294)}]}

        pages = iter([{"lines": [line("SCMessenger", 120, 960), line("Invite friends", 115, 1040)]},
                      {"lines": [line("SCMessenger", 132, 800), line("Next project", 120, 900)]}])
        driver = Mock()
        first = Image.new("RGB", (1800, 1131), "white")
        second = Image.new("RGB", (1800, 1131), "black")
        driver.frame.return_value = second
        with patch.object(census, "inspect_crop", lambda *args: next(pages)), \
             patch.object(census.time, "sleep", lambda _: None):
            collected = list(census.visual_project_pages(driver, first))
        self.assertEqual([label for _, _, rows in collected for label, _ in rows], ["SCMessenger"])
        driver.act.assert_called_once()

    def test_census_waits_for_capture_geometry_before_navigation(self):
        driver = Mock()
        driver.frame.side_effect = [Image.new("RGB", (400, 194)), Image.new("RGB", (400, 200))]
        driver.compositor_bounds.return_value = Mock(left=0, top=0, right=400, bottom=200)
        with patch.object(census.time, "sleep", lambda _: None):
            self.assertEqual(census.settled_census_frame(driver).size, (400, 200))
        self.assertEqual(driver.frame.call_count, 2)
        driver.act.assert_not_called()

    def test_sidebar_scroll_recaptures_after_geometry_refusal(self):
        driver = Mock()
        driver.act.side_effect = [RuntimeError("FreeBuff compositor geometry changed after capture"), None]
        driver.frame.return_value = Image.new("RGB", (400, 200))
        census.scroll_project_sidebar(driver, Image.new("RGB", (400, 194)), "scroll", -240)
        self.assertEqual(driver.act.call_count, 2)
        self.assertEqual(driver.act.call_args.args[2]["size"], [400, 200])

    def test_sidebar_scroll_does_not_retry_other_refusals(self):
        driver = Mock()
        driver.act.side_effect = RuntimeError("owner desktop activity resumed before input")
        with self.assertRaisesRegex(RuntimeError, "owner desktop activity"):
            census.scroll_project_sidebar(driver, Image.new("RGB", (400, 200)), "scroll", -240)
        driver.frame.assert_not_called()

    def test_census_never_expands_another_project_above_visible_scm_heading(self):
        def line(text, x, y):
            return {"text": text, "words": [{"text": text, "x": 2 * (x - 95), "y": 2 * (y - 294)}]}

        readings = iter([{"lines": [line("SCMessenger", 120, 400), line("SCMessenger", 132, 450)]},
                         {"lines": [line("Show more", 105, 360), line("SCMessenger", 120, 450),
                                    line("SCMessenger", 132, 500), line("Next project", 120, 600)]}])
        driver = Mock()
        first = Image.new("RGB", (1800, 1131), "white")
        driver.frame.return_value = Image.new("RGB", (1800, 1131), "black")
        with patch.object(census, "inspect_crop", lambda *args: next(readings)), \
             patch.object(census.time, "sleep", lambda _: None):
            list(census.visual_project_pages(driver, first))
        self.assertEqual([call.args[1] for call in driver.act.call_args_list], [census.SCROLL])

    def test_census_reacquires_stale_row_only_beneath_project_heading(self):
        def line(text, x, y):
            return {"text": text, "words": [{"text": text, "x": 2 * (x - 95), "y": 2 * (y - 294)}]}

        driver = Mock()
        frame = Image.new("RGB", (1800, 1131), "white")
        driver.frame.return_value = frame
        with patch.object(census, "inspect_crop", lambda *args: {"lines": [
            line("SCMessenger", 120, 400), line("SCMessenger Audit Lar", 132, 450),
            line("SCMessenger CLOUD", 120, 500), line("SCMessenger Audit Lar", 132, 550)]}):
            self.assertEqual(census.reacquire_project_row(driver, "SCMessenger Audit Lar", "row"), (frame, 450))
        driver.act.assert_not_called()
        driver.yes.assert_called_once()

    def test_census_match_requires_active_uuid_and_both_activity_markers(self):
        fields = {"toolbar": "Local DeepSeek V4.1 Flash Slow", "transcript-upper": "#745",
                  "transcript-lower": "Codex #746", "rail_marks": 22,
                  "document_sessions": ["2ae32937-c991-4c33-87d4-68b8c956ba98"]}
        self.assertTrue(census.census_signature(fields))
        self.assertFalse(census.census_signature(fields | {"document_sessions": []}))
        self.assertFalse(census.census_signature(fields | {"transcript-lower": "Older work"}))

    def test_selected_row_ignores_the_leading_status_glyph(self):
        self.assertTrue(Dispatch.row_matches("Ra Vision Driver Standup al V", "Vision Driver Standup and Audit"))

    def test_cure_never_replays_an_uncertain_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            evidence = tmp_path / "send"
            evidence.mkdir()
            receipt = AuditLog(tmp_path / "runner.jsonl")
            receipt.append("verification", step_id="result", state="parked: identify-foreground refused")
            trace = AuditLog(evidence / "driver.jsonl")
            trace.append("action", step_id="observation-foreground", action="focus_freebuff", ok=False)
            self.assertTrue(watch.cure_eligible(tmp_path, ("identify-",)))
            trace.append("action", step_id="send-once", action="send_freebuff", ok=False)
            self.assertFalse(watch.cure_eligible(tmp_path, ("identify-",)))

    def test_scm_timeout_cure_is_admitted_after_vision_seat(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            item = f"restore-{watch.SCM_RESTART}-2ae32937"
            folder = tmp_path / "harness-freebuff-runner" / item
            phase = folder / "search"
            phase.mkdir(parents=True)
            AuditLog(folder / "runner.jsonl").append(
                "verification", step_id="result", state="parked: search: driver tree termination unverified")
            AuditLog(phase / "driver.jsonl").append(
                "action", step_id="scroll", action="scroll_freebuff", ok=True)
            known = {
                f"claim-restore-{watch.STANDUP}-{watch.VISION_THREAD}.json",
                f"claim-restore-{watch.LANE_RESTART}-{watch.THREAD}.json",
                f"claim-{item}.json", f"result-{item}.json",
            }
            execute = Mock(return_value=1)
            with patch.dict("os.environ", {"LOCALAPPDATA": str(tmp_path)}), \
                 patch.object(watch, "desktop_idle", lambda: True), \
                 patch.object(watch, "guard_approval", Mock()), \
                 patch.object(watch, "checkpoint", Mock()), \
                 patch.object(watch, "execute", execute):
                self.assertTrue(watch.run_restoration({watch.SCM_RESTART: {"body": "authorized"}}, known))
            self.assertEqual(execute.call_args.args[1], f"{item}-project-roster-cure")
            self.assertEqual(execute.call_args.args[2]["phases"], ("project-census",))

    def test_runner_propagates_platform_refused_even_on_zero_exit(self):
        """Codex P2: Platform state: refused in child stdout must fail closed."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            audit = AuditLog(tmp_path / "runner.jsonl")
            fake_proc = Mock()
            fake_proc.returncode = 0
            fake_proc.communicate.return_value = ("Platform state: refused: usage limit notice\n", "")
            with patch.object(runner.subprocess, "Popen", return_value=fake_proc) as popen_mock:
                with self.assertRaisesRegex(RuntimeError, "Platform state: refused: usage limit notice"):
                    runner.run_phases(tmp_path, "f90f01e9", audit, phases=("steer-send",), standing=True)
            cmd = popen_mock.call_args.args[0]
            self.assertIn("-WindowStyle", cmd)
            self.assertIn("Hidden", cmd)

    def test_local_control_pause_or_stop_prevents_watch_tick(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            ctl = Path(tmp) / "control.json"
            ctl.write_text(json.dumps({"enabled": True, "paused": True}), encoding="utf-8")
            with patch.dict("os.environ", {"HARNESS_DRIVER_CONTROL_FILE": str(ctl)}), \
                 patch.object(watch, "worktree_head") as head_mock:
                watch.main()
            head_mock.assert_not_called()

    def test_parse_dynamic_dispatch_handles_freebuff_and_antigravity(self):
        now = datetime(2026, 11, 24, 1, 0, tzinfo=timezone.utc)
        scm_comment = {
            "id": 990001,
            "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-24T00:45:00Z",
            "body": (
                "RESTART DISPATCH — episode SCM-STOP-R80\n"
                "Lane: SCMessenger\n"
                'Action for the runner: restart the SCMessenger lane with "continue in full".'
            ),
        }
        parsed = watch.parse_dynamic_dispatch(scm_comment, now=now)
        self.assertEqual(parsed["kind"], "restart")
        self.assertEqual(parsed["thread"], watch.SCM_THREAD)

        agy_comment = {
            "id": 990002,
            "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-24T00:50:00Z",
            "body": (
                "RESTART DISPATCH — Antigravity\n"
                "Target: antigravity\n"
                'Action for the runner: restart the antigravity lane with "continue in full".'
            ),
        }
        parsed_agy = watch.parse_dynamic_dispatch(agy_comment, now=now)
        self.assertEqual(parsed_agy["kind"], "antigravity-park")

    def test_poll_dynamic_dispatches_executes_unclaimed_restart_and_parks_antigravity(self):
        now = datetime(2026, 11, 24, 1, 0, tzinfo=timezone.utc)
        comments = [
            {
                "id": 990002,
                "user": {"id": watch.OWNER_ID},
                "created_at": "2026-11-24T00:50:00Z",
                "body": "RESTART DISPATCH\nTarget: antigravity\nAction for the runner: \"continue in full\"",
            },
            {
                "id": 990003,
                "user": {"id": watch.OWNER_ID},
                "created_at": "2026-11-24T00:52:00Z",
                "body": "RESTART DISPATCH\nLane: SCMessenger\nAction for the runner: \"continue in full\"",
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            write = Mock()
            posted = Mock()
            execute = Mock(return_value=0)
            with patch.dict("os.environ", {"LOCALAPPDATA": tmp}), \
                 patch.object(watch, "api", return_value=comments), \
                 patch.object(watch, "guard_approval", Mock()), \
                 patch.object(watch, "desktop_idle", lambda: True), \
                 patch.object(watch, "checkpoint", write), \
                 patch.object(watch, "issue_comment", posted), \
                 patch.object(watch, "execute", execute):
                self.assertTrue(watch.poll_dynamic_dispatches({"claim-dyn-990002-antigravity.json"}, now=now))
            self.assertEqual(execute.call_args.args[2]["thread"], watch.SCM_THREAD)
            self.assertEqual(write.call_args_list[0].args[0], "claim-dyn-990003-2ae32937.json")
            self.assertEqual(write.call_args_list[1].args[0], "result-dyn-990003-2ae32937.json")

    def test_local_control_state_accepts_utf8_bom_control_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctl = Path(tmp) / "control.json"
            ctl.write_bytes(b'\xef\xbb\xbf{"enabled": true, "paused": false}\n')
            with patch.dict("os.environ", {"HARNESS_DRIVER_CONTROL_FILE": str(ctl)}):
                state = watch.local_control_state()
            self.assertTrue(state["enabled"])
            self.assertFalse(state["paused"])


if __name__ == "__main__":
    unittest.main()
