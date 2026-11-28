"""The class cure for lane standup: settled rosters, unique rows, named refusals."""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import windows_freebuff_dispatch as dispatch_module
from scripts import windows_freebuff_runner as runner
from scripts.windows_freebuff_dispatch import SIDEBAR, Dispatch, lookup_local_session_uuid, same_rows


def shim(tmp_path, frames):
    dispatch = object.__new__(Dispatch)
    dispatch.output = tmp_path
    dispatch.audit = Mock()
    dispatch.frame = Mock(side_effect=frames)
    return dispatch


def live_sidebar():
    """The measured 2026-11-23 layout: a CLOUD Lane 1 above the LOCAL one."""
    return [
        {"text": "B GitHub", "x": 60, "y": 250, "x1": 200},
        {"text": "Vision Driver Standu", "x": 72, "y": 270, "x1": 330},
        {"text": "Disk Audit", "x": 72, "y": 290, "x1": 330},
        {"text": "harness CLOUD", "x": 60, "y": 330, "x1": 200},
        {"text": "Lane 2", "x": 72, "y": 350, "x1": 330},
        {"text": "Ra Lane 1", "x": 72, "y": 370, "x1": 330},
        {"text": "Harness", "x": 60, "y": 410, "x1": 200},
        {"text": "Ra Harness Audit Lane", "x": 72, "y": 430, "x1": 330},
        {"text": "Ra Lane 2", "x": 72, "y": 450, "x1": 330},
        {"text": "Ra Lane 1", "x": 72, "y": 470, "x1": 330},
    ]


def foreground_shim(hwnd, sequence, transient):
    dispatch = object.__new__(Dispatch)
    dispatch.standing = True
    dispatch.audit = Mock()
    dispatch.window = Mock()
    dispatch.window.require_window.return_value = hwnd
    dispatch.window.api.foreground = Mock(side_effect=list(sequence))
    dispatch.describe = Mock(return_value="holder")
    dispatch.transient_holder = Mock(return_value=transient)
    return dispatch


class FreebuffNavigationTests(unittest.TestCase):
    def test_clipped_sidebar_label_matches_but_a_short_prefix_does_not(self):
        self.assertTrue(Dispatch.row_matches("Kalshi Paper Burndov", "Kalshi Paper Burndown"))
        self.assertTrue(Dispatch.row_matches("Kalshi Paper Burndown", "Kalshi Paper Burndown"))
        self.assertFalse(Dispatch.row_matches("Kalshi Paper Rotation at", "Kalshi Paper Burndown"))
        self.assertFalse(Dispatch.row_matches("Lane", "Lane 1"))
        self.assertFalse(Dispatch.row_matches("Lane 1", "Lane 2"))

    def test_selection_waits_for_two_identical_rosters(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = [Mock(name=f"frame-{index}") for index in range(3)]
            dispatch = shim(Path(tmp), frames)
            censuses = [
                [{"text": "Lane 1", "x": 133, "y": 740, "x1": 200}],
                [{"text": "Lane 1", "x": 133, "y": 752, "x1": 200}],
                [{"text": "Lane 1", "x": 133, "y": 752, "x1": 200}],
            ]
            dispatch.read_roster = Mock(side_effect=lambda step, frame, region: censuses.pop(0))
            with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
                frame, rows = dispatch.settled_roster("probe", SIDEBAR)

            self.assertIs(frame, frames[2])
            self.assertEqual(rows[0]["text"], "Lane 1")
            self.assertEqual(censuses, [])

    def test_a_roster_whose_rows_keep_changing_refuses_by_name(self):
        """Geometry churn with the same rows settles; identity churn still refuses."""
        with tempfile.TemporaryDirectory() as tmp:
            dispatch = shim(Path(tmp), [Mock() for _ in range(8)])
            names = iter(["Kalshi Paper Burndown", "Kalshi Paper Rotation", "BigEnergyCo",
                          "Disk Audit", "Lane 2", "Sergeant"])
            dispatch.read_roster = Mock(side_effect=lambda step, frame, region: [
                {"text": next(names), "x": 133, "y": 740, "x1": 200}])
            with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
                with self.assertRaisesRegex(RuntimeError, "did not settle"):
                    dispatch.settled_roster("probe", SIDEBAR, attempts=3)

    def test_a_reordering_roster_settles_on_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            dispatch = shim(Path(tmp), [Mock() for _ in range(8)])
            order = iter([[("B Harness", 120), ("Lane 1", 150)],
                          [("Lane 1", 120), ("B Harness", 150)],
                          [("Lane 1", 132), ("B Harness", 162)]])
            dispatch.read_roster = Mock(side_effect=lambda step, frame, region: [
                {"text": text, "x": 72, "y": y, "x1": 330} for text, y in next(order)])
            with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
                _, rows = dispatch.settled_roster("probe", SIDEBAR, attempts=4)
            self.assertEqual([row["text"] for row in rows], ["Lane 1", "B Harness"])

    def test_a_short_label_matches_its_own_row_through_the_icon_glyph(self):
        self.assertTrue(Dispatch.row_matches("Lane 1", "Lane 1"))
        self.assertTrue(Dispatch.row_matches("B Lane 1", "Lane 1"))
        self.assertTrue(Dispatch.row_matches("Ra Lane 2 Waist Composition Mission Brief", "Lane 2"))
        self.assertFalse(Dispatch.row_matches("Lane 1", "Lane 2"))

    def test_a_phantom_row_settles_but_a_moved_row_does_not(self):
        stationary = (370, 385, 400)
        phantom = (370, 377, 385, 400)
        moved = (370, 391, 400)

        self.assertTrue(same_rows(stationary, stationary))
        self.assertTrue(same_rows(stationary, phantom))
        self.assertFalse(same_rows(stationary, moved))

    def test_ocr_flicker_on_a_stationary_row_still_settles(self):
        """The measured case: one row, two readings, no movement at all."""
        with tempfile.TemporaryDirectory() as tmp:
            frames = [Mock(name=f"frame-{index}") for index in range(3)]
            dispatch = shim(Path(tmp), frames)
            readings = [[{"text": "Kalshi Paper Bumd", "x": 133, "y": 740, "x1": 200}],
                        [{"text": "Kalshi Paper Burndc V", "x": 133, "y": 740, "x1": 200}]]
            calls = []

            def flicker(step, frame, region):
                calls.append(step)
                return readings[(len(calls) - 1) % 2]

            dispatch.read_roster = Mock(side_effect=flicker)
            with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
                frame, rows = dispatch.settled_roster("probe", SIDEBAR)

            self.assertIs(frame, frames[1])
            self.assertIn(rows[0]["text"], {"Kalshi Paper Bumd", "Kalshi Paper Burndc V"})
            self.assertTrue(Dispatch.row_matches(rows[0]["text"], "Kalshi Paper Burndown"))

    def test_ambiguous_row_refusal_names_every_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            dispatch = object.__new__(Dispatch)
            dispatch.output = Path(tmp)
            dispatch.audit = Mock()
            dispatch.frame = Mock(return_value=Mock())
            rows = [{"text": "Lane 1", "x": 133, "y": 700, "x1": 200},
                    {"text": "Lane 2", "x": 133, "y": 724, "x1": 200}]

            with self.assertRaisesRegex(RuntimeError, "matched 0 settled rows"):
                dispatch.click_roster_row("select", Mock(), rows, "Lane 3")

    def test_a_reloaded_window_must_census_non_empty_twice_before_use(self):
        """The empty sidebar after a reload is not a roster: wait for two agreeing ones."""
        with tempfile.TemporaryDirectory() as tmp:
            frames = [Mock(name=f"frame-{index}") for index in range(6)]
            dispatch = shim(Path(tmp), frames)
            censuses = iter([[], [], [{"text": "Lane 1", "x": 133, "y": 740, "x1": 200}],
                             [{"text": "Lane 1", "x": 133, "y": 740, "x1": 200}]])
            dispatch.read_roster = Mock(side_effect=lambda step, frame, region: next(censuses))
            with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
                frame, rows = dispatch.stable_window("reload")

            self.assertEqual(rows[0]["text"], "Lane 1")
            self.assertIs(frame, frames[2])

    def test_a_window_that_never_census_anything_refuses_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            dispatch = shim(Path(tmp), [Mock() for _ in range(6)])
            dispatch.read_roster = Mock(return_value=[])
            with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()), \
                 patch("scripts.windows_freebuff_dispatch.time.monotonic",
                       Mock(side_effect=[0, 1, 2, 3, 40])):
                with self.assertRaisesRegex(RuntimeError, "stable roster"):
                    dispatch.stable_window("reload", seconds=5, attempts=3)

    def test_a_project_heading_and_its_chat_are_separated_by_the_glyph(self):
        """SCMessenger's project heading and one chat share a name; only the chat is plain."""
        rows = [{"text": "B SCMessenger", "x": 133, "y": 517, "x1": 200},
                {"text": "SCMessenger", "x": 133, "y": 561, "x1": 200}]
        self.assertEqual([row for row in rows if Dispatch.row_matches(row["text"], "SCMessenger")], rows)
        self.assertEqual(len([row for row in rows if row["text"].strip() == "SCMessenger"]), 1)

    def test_headings_distinguish_cloud_from_local(self):
        self.assertEqual(Dispatch.heading_name("B GitHub"), "GitHub")
        self.assertEqual(Dispatch.heading_name("harness CLOUD"), "harness CLOUD")
        self.assertEqual(Dispatch.heading_name("Harness"), "Harness")
        self.assertIsNone(Dispatch.heading_name("Ra Lane 1"))

    def test_a_row_is_bound_to_the_heading_above_it(self):
        rows = live_sidebar()
        cloud, local = rows[5], rows[9]
        self.assertEqual(Dispatch.project_of_row(rows, cloud), "harness CLOUD")
        self.assertEqual(Dispatch.project_of_row(rows, local), "Harness")
        # No heading above this row in the frame: unscoped, never guessed.
        above = {"text": "Ra Lane 1", "x": 72, "y": 100, "x1": 330}
        self.assertIsNone(Dispatch.project_of_row(rows, above))

    def test_a_cloud_lane_1_does_not_satisfy_the_local_lane_1(self):
        """The 19:30Z false green: title alone accepted the CLOUD row."""
        rows = live_sidebar()
        cloud, local = rows[5], rows[9]
        self.assertTrue(Dispatch.row_matches(cloud["text"], "Lane 1"))
        self.assertFalse(Dispatch.scoped_row(rows, cloud, "Lane 1", "Harness"))
        self.assertTrue(Dispatch.scoped_row(rows, local, "Lane 1", "Harness"))
        self.assertFalse(Dispatch.scoped_row(rows, local, "Lane 1", "harness CLOUD"))

    def test_a_project_heading_is_never_the_session_it_names(self):
        rows = [{"text": "Projects", "x": 60, "y": 100, "x1": 300},
                {"text": "B SCMessenger", "x": 60, "y": 140, "x1": 300},
                {"text": "SCMessenger", "x": 72, "y": 180, "x1": 330},
                {"text": "B Harness", "x": 60, "y": 260, "x1": 300}]
        found, heading = Dispatch.session_candidates(rows, "SCMessenger", "SCMessenger")
        self.assertEqual([row["text"] for row in found], ["SCMessenger"])
        self.assertEqual(heading["text"], "B SCMessenger")

    def test_only_the_exact_lane_title_counts_as_the_selection(self):
        self.assertTrue(Dispatch.exact_session_title("SCMessenger", "SCMessenger"))
        self.assertTrue(Dispatch.exact_session_title("Ra SCMessenger", "SCMessenger"))
        self.assertFalse(Dispatch.exact_session_title("SCMessenger Audit Lar", "SCMessenger"))
        self.assertFalse(Dispatch.exact_session_title("SCMessenger Fresh Re", "SCMessenger"))
        self.assertFalse(Dispatch.exact_session_title("Lane 1 nightly", "Lane 1"))

    def test_an_exact_title_wins_over_prefix_rivals(self):
        rows = [{"text": "Projects", "x": 60, "y": 80, "x1": 300},
                {"text": "B SCMessenger", "x": 60, "y": 120, "x1": 300},
                {"text": "SCMessenger", "x": 72, "y": 150, "x1": 330},
                {"text": "SCMessenger Audit Lar", "x": 72, "y": 180, "x1": 330},
                {"text": "SCMessenger Fresh Re", "x": 72, "y": 210, "x1": 330},
                {"text": "SCMessenger Bumdown Tc", "x": 72, "y": 240, "x1": 330},
                {"text": "Ra SCMessenger Fast Mode Pc", "x": 72, "y": 270, "x1": 330}]
        found, _ = Dispatch.session_candidates(rows, "SCMessenger", "SCMessenger")
        self.assertEqual([row["text"] for row in found], ["SCMessenger"])

    def test_two_equally_exact_titles_are_still_refused(self):
        rows = [{"text": "B Harness", "x": 60, "y": 120, "x1": 300},
                {"text": "Lane 1", "x": 72, "y": 150, "x1": 330},
                {"text": "Lane 1", "x": 72, "y": 180, "x1": 330}]
        found, _ = Dispatch.session_candidates(rows, "Lane 1", "Harness")
        self.assertEqual(len(found), 2)

    def test_identities_tolerate_ocr_slips_but_not_a_new_roster(self):
        self.assertTrue(Dispatch.identities_compatible(("kalshipaperbumd",), ("kalshipaperburndcv",)))
        self.assertTrue(Dispatch.identities_compatible(("lanel",), ("lanel",)))
        self.assertFalse(Dispatch.identities_compatible(("kalshipaperburndown",), ("kalshipaperrotation",)))
        self.assertFalse(Dispatch.identities_compatible(("lanel",), ("lanel", "lane2")))

    def test_roster_identity_ignores_reordering(self):
        first = [{"text": "B Harness", "x": 60, "y": 120, "x1": 300},
                 {"text": "Lane 1", "x": 72, "y": 150, "x1": 330}]
        moved = [{"text": "Lane 1", "x": 72, "y": 120, "x1": 330},
                 {"text": "B Harness", "x": 60, "y": 150, "x1": 300}]
        self.assertEqual(Dispatch.identity_of(first), Dispatch.identity_of(moved))
        self.assertNotEqual(Dispatch.identity_of(first), Dispatch.identity_of(first[:1]))

    def test_a_collapsed_project_yields_its_heading_only(self):
        rows = [{"text": "B SCMessenger", "x": 60, "y": 140, "x1": 300},
                {"text": "B Harness", "x": 60, "y": 260, "x1": 300}]
        found, heading = Dispatch.session_candidates(rows, "SCMessenger", "SCMessenger")
        self.assertEqual(found, [])
        self.assertEqual(heading["text"], "B SCMessenger")

    def test_a_row_without_a_visible_heading_is_refused(self):
        row = {"text": "Ra Lane 1", "x": 72, "y": 900, "x1": 330}
        self.assertFalse(Dispatch.scoped_row([row], row, "Lane 1", "Harness"))

    def test_a_standing_run_reclaims_a_transient_temp_console(self):
        """R1: the two-minute watch console must not park a valid send."""
        activate = Mock(return_value=True)
        dispatch = foreground_shim(111, [222, 111], transient=True)
        with patch("scripts.windows_freebuff_dispatch.activate_exact", activate), \
             patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
            self.assertEqual(dispatch.require_foreground(), 111)
        activate.assert_called_once()
        self.assertTrue(any(
            call.args[0] == "verification" and call.kwargs.get("step_id") == "foreground-obtained"
            for call in dispatch.audit.append.call_args_list
        ))

    def test_a_standing_run_never_takes_foreground_from_an_owner_surface(self):
        activate = Mock(return_value=True)
        dispatch = foreground_shim(111, [222, 222], transient=False)
        with patch("scripts.windows_freebuff_dispatch.activate_exact", activate):
            with self.assertRaisesRegex(RuntimeError, "not the foreground"):
                dispatch.require_foreground()
        activate.assert_not_called()

    def test_the_watch_console_is_recognised_by_its_temp_python_title(self):
        dispatch = object.__new__(Dispatch)
        dispatch.user = Mock()
        dispatch.window = Mock()
        fake_temp = r"C:\Users\tester\AppData\Local\Temp"
        temp = os.path.join(fake_temp, "harness-notepad-venv-20261122", "Scripts", "python.exe")
        with patch.dict("os.environ", {"TEMP": fake_temp}, clear=False):
            dispatch.window.api.title_of.return_value = temp
            self.assertTrue(dispatch.transient_holder(1))
            dispatch.window.api.title_of.return_value = "C:\\Windows\\explorer.exe"
            self.assertFalse(dispatch.transient_holder(1))

    def test_an_ended_turn_is_not_running_even_when_the_stop_glyph_flickers(self):
        dispatch = object.__new__(Dispatch)
        dispatch.stop_visible = Mock(return_value=True)
        dispatch.turn_ended_banner = Mock(return_value=True)
        self.assertFalse(dispatch.turn_running(Mock()))
        dispatch.turn_ended_banner.return_value = False
        self.assertTrue(dispatch.turn_running(Mock()))

    def test_a_marker_is_released_only_by_a_pre_input_foreground_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            dispatch = object.__new__(Dispatch)
            dispatch.output = tmp_path
            trace = tmp_path / "driver.jsonl"
            trace.write_text(json.dumps({
                "kind": "action", "step_id": "send-once", "ok": False,
                "detail": "executor failed: FreeBuff is not the foreground window; held by hwnd 1"}) + "\n",
                encoding="utf-8")
            self.assertTrue(dispatch.prior_send_refused_before_input())
            trace.write_text(json.dumps({
                "kind": "action", "step_id": "send-once", "ok": True, "detail": ""}) + "\n",
                encoding="utf-8")
            self.assertFalse(dispatch.prior_send_refused_before_input())


def row(text, y):
    return {"text": text, "x": 72, "y": y, "x1": 330}


def walking_dispatch(pages, advances):
    dispatch = object.__new__(Dispatch)
    dispatch.audit = Mock()
    dispatch.label = "SCMessenger"
    dispatch.project = "SCMessenger"
    dispatch.frame = Mock(return_value=Mock(name="frame"))
    dispatch.scroll_sidebar_to_top = Mock(return_value=Mock(name="top"))
    dispatch.settled_roster = Mock(side_effect=[(Mock(name="frame"), rows) for rows in pages])
    dispatch.advance_sidebar = Mock(side_effect=[(Mock(name="advanced"), moved)
                                                 for moved in advances])
    dispatch.click_exact_row = Mock()
    dispatch.click_row_by_text = Mock(return_value=True)
    return dispatch


class SelectionProjectFamilyTests(unittest.TestCase):
    """Measured 2026-11-27 (dyn-7226574169): the open lane was read as another project."""

    def _dispatch(self, heading):
        row = {"text": "Ra Lane 2", "x": 118, "x1": 300, "y": 495}
        dispatch = object.__new__(Dispatch)
        dispatch.label = "Lane 2"
        dispatch.project = "Harness"
        dispatch.audit = Mock()
        dispatch.settled_roster = Mock(return_value=("frame", [row]))
        dispatch.highlighted_row = Mock(return_value=row)
        dispatch.project_of_row = Mock(return_value=heading)
        return dispatch

    def test_the_cloud_heading_is_the_lane_that_is_open(self):
        dispatch = self._dispatch("harness CLOUD")
        self.assertTrue(dispatch.selected_label_matches())

    def test_the_exact_heading_is_still_accepted(self):
        dispatch = self._dispatch("Harness")
        self.assertTrue(dispatch.selected_label_matches())

    def test_a_heading_outside_the_frame_leaves_the_unique_name(self):
        """Measured on dyn-7226817360: the heading was None and the lane was refused."""
        dispatch = self._dispatch(None)
        self.assertTrue(dispatch.selected_label_matches())
        steps = [c.kwargs.get("step_id") for c in dispatch.audit.append.call_args_list]
        self.assertIn("selected-row-unbound", steps)

    def test_an_unbound_heading_is_refused_when_a_rival_carries_the_name(self):
        dispatch = self._dispatch(None)
        row = {"text": "Ra Lane 2", "x": 118, "x1": 300, "y": 495}
        rival = {"text": "Lane 2 Waist Composition Mission Brief", "x": 118, "x1": 300, "y": 700}
        dispatch.settled_roster = Mock(return_value=("frame", [row, rival]))
        self.assertFalse(dispatch.selected_label_matches())

    def test_a_highlighted_row_in_another_project_is_still_refused(self):
        dispatch = self._dispatch("Kalshi-Trader")
        self.assertFalse(dispatch.selected_label_matches())

class ComposerPlaceholderRouteTests(unittest.TestCase):
    """Measured on dyn-7228544294: the empty composer read as machine text."""

    def _dispatch(self):
        dispatch = object.__new__(Dispatch)
        dispatch.label = "Lane 1"
        dispatch.text = "continue in full"
        dispatch.audit = Mock()
        return dispatch

    def test_the_current_placeholder_is_an_empty_composer(self):
        dispatch = self._dispatch()
        # The app's current placeholder, as the OCR delivered it.
        written = ["typeamessagesentbeforethequeue"]
        self.assertIsNone(dispatch.composer_written_route(written, "Ask Freebuff... Use / for commands"))

    def test_the_legacy_placeholder_still_reads_as_empty(self):
        dispatch = self._dispatch()
        written = ["askfreebuffuseforcommandsforfiles"]
        self.assertIsNone(dispatch.composer_written_route(written, "Ask Freebuff... Use / for commands"))

    def test_the_continuation_is_staged_text(self):
        dispatch = self._dispatch()
        self.assertEqual(dispatch.composer_written_route(["continue in full"], "x"), "staged")

    def test_a_real_foreign_draft_is_still_foreign(self):
        dispatch = self._dispatch()
        self.assertEqual(dispatch.composer_written_route(["owner module with an owner test"], "x"),
                         "foreign")


    def test_the_executor_reanchors_only_on_an_unchanged_composer(self):
        source = Path(dispatch_module.__file__).read_text(encoding="utf-8")
        start = source.index("step_id=\"send-window-reanchor\"")
        window = source.rindex("if self.send_deadline is None", 0, start)
        guard = source[window:start]
        self.assertIn("composer_unchanged(self.send_composer, recheck.crop(COMPOSER))", guard)
        self.assertIn("raise RuntimeError", guard)


class SidebarTopSettleTests(unittest.TestCase):
    """Measured 2026-11-28: an entire search budget spent scrolling a still list."""

    def _dispatch(self, readings):
        dispatch = object.__new__(Dispatch)
        dispatch.audit = Mock()
        dispatch.frame = Mock(return_value="frame")
        dispatch.scroll_by = Mock(return_value=True)
        dispatch.read_roster = Mock(side_effect=[
            [{"text": text, "y": 100 + index * 60} for index, text in enumerate(reading)]
            for reading in readings])
        return dispatch

    def test_a_still_list_settles_while_its_text_alternates(self):
        # The same three stationary rows, read two ways: text can never match.
        dispatch = self._dispatch([["B Harness", "Lane 1", "Carrier Census Verifica-"],
                                   ["Harness", "Lane 1", "Carrier Census Verificat"],
                                   ["Harness", "Lane 1", "Carrier Census Verificat"]])
        with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
            dispatch.scroll_sidebar_to_top(steps=4)
        self.assertLessEqual(dispatch.scroll_by.call_count, 1)


class SessionNameBindingTests(unittest.TestCase):
    """Measured on dyn-7230285733: search and query picked the row, select did not."""

    def test_no_matcher_is_bound_to_the_dispatch_label(self):
        source = Path(dispatch_module.__file__).read_text(encoding="utf-8")
        for matcher in ("row_matches(", "_prefix_matches(", "exact_session_title("):
            start = 0
            while True:
                index = source.find(matcher, start)
                if index < 0:
                    break
                line = source[index:source.find(chr(10), index)]
                self.assertNotIn("self.label", line, line.strip())
                start = index + len(matcher)

    def test_a_lane_without_a_title_alias_matches_its_label(self):
        dispatch = object.__new__(Dispatch)
        dispatch.label = "Lane 1"
        dispatch.thread = "315608d2"
        self.assertEqual(dispatch.session_name, "Lane 1")


class PreSendReanchorTests(unittest.TestCase):
    """Measured on dyn-7229598525: identity outlasted the window, send refused."""

    def test_an_expired_window_is_extended_only_on_an_unchanged_composer(self):
        source = Path(dispatch_module.__file__).read_text(encoding="utf-8")
        start = source.index("step_id=\"pre-send-reanchor\"")
        window = source.rindex("if age > 60:", 0, start)
        guard = source[window:start]
        self.assertIn("composer_unchanged(frame.crop(COMPOSER), fresh.crop(COMPOSER))", guard)
        self.assertIn("raise RuntimeError", guard)


class SendArrowLightThemeTests(unittest.TestCase):
    """Measured on dyn-7229334626: a white control on a white page."""

    def _frame(self, arrow=True):
        from PIL import Image
        frame = Image.new("RGB", (1800, 1131), (249, 249, 249))
        if arrow:
            left, top, _, _ = dispatch_module.SEND_CONTROL
            for x in range(left + 20, left + 33):
                for y in range(top + 11, top + 18):
                    frame.putpixel((x, y), (30, 30, 30))
        return frame

    def test_a_dark_glyph_on_a_white_page_is_the_send_control(self):
        point = dispatch_module._send_arrow_bbox(self._frame())
        self.assertIsNotNone(point)
        control = dispatch_module.SEND_CONTROL
        self.assertTrue(control[0] <= point[0] <= control[2])

    def test_a_plain_white_page_has_no_send_control(self):
        self.assertIsNone(dispatch_module._send_arrow_bbox(self._frame(arrow=False)))


class SendArrowPixelsFirstTests(unittest.TestCase):
    """Measured on dyn-7229043019: a staged draft parked on a 0.31 arrow guess."""

    def test_the_send_outline_is_located_before_any_model_is_asked(self):
        source = Path(dispatch_module.__file__).read_text(encoding="utf-8")
        measured = source.index("point = _send_arrow_bbox(frame, region=region)")
        asked = source.index('"verify-send-arrow"')
        self.assertLess(measured, asked)


class ComposerFocusBeforeClearTests(unittest.TestCase):
    """Measured on dyn-7228279746: the clear had no renderer because nothing clicked."""

    def test_the_relay_route_focuses_the_composer_before_clearing_it(self):
        source = Path(dispatch_module.__file__).read_text(encoding="utf-8")
        focus = source.index('"focus-machine-composer"')
        clear = source.index('"clear-machine-composer"')
        self.assertLess(focus, clear)
        # The click must name the composer, which is what records the renderer.
        window = source[focus:clear]
        self.assertIn("composer", window)


class SelectionHandoffTests(unittest.TestCase):
    """Measured 2026-11-27: the select phase proved what prepare could not re-derive."""

    def _dispatch(self, record, root):
        dispatch = object.__new__(Dispatch)
        dispatch.label = "Lane 1"
        dispatch.thread = "315608d2"
        dispatch.audit = Mock()
        dispatch.output = Path(root) / "prepare"
        dispatch.output.mkdir(parents=True, exist_ok=True)
        if record is not None:
            (Path(root) / "selection.json").write_text(json.dumps(record), encoding="utf-8")
        return dispatch

    def test_this_runs_fresh_selection_for_this_lane_is_accepted(self):
        with tempfile.TemporaryDirectory() as root:
            record = {"thread": "315608d2", "at": datetime.now(timezone.utc).isoformat()}
            dispatch = self._dispatch(record, root)
            self.assertTrue(dispatch.selection_handoff())

    def test_another_lane_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            record = {"thread": "9ecc3453", "at": datetime.now(timezone.utc).isoformat()}
            dispatch = self._dispatch(record, root)
            self.assertFalse(dispatch.selection_handoff())

    def test_a_stale_selection_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            record = {"thread": "315608d2", "at": old}
            dispatch = self._dispatch(record, root)
            self.assertFalse(dispatch.selection_handoff())

    def test_no_record_means_no_proof(self):
        with tempfile.TemporaryDirectory() as root:
            dispatch = self._dispatch(None, root)
            self.assertFalse(dispatch.selection_handoff())

    def test_the_runner_records_the_select_proof(self):
        source = Path(runner.__file__).read_text(encoding="utf-8")
        self.assertIn('"selection.json"', source)


class OpenTabIdentityTests(unittest.TestCase):
    """Measured on dyn-7227546381: the title OCR drops the lane numeral."""

    def _dispatch(self, located):
        dispatch = object.__new__(Dispatch)
        dispatch.label = "Lane 1"
        dispatch.project = "Harness"
        dispatch.audit = Mock()
        dispatch.frame = Mock(return_value="frame")
        dispatch.read_lines = Mock(return_value=["Code Chat lanelv"])
        if located is None:
            dispatch.locate_exact_text = Mock(side_effect=RuntimeError("not located"))
        else:
            dispatch.locate_exact_text = Mock(return_value=located)
        return dispatch

    def test_the_exact_locator_proves_the_open_title(self):
        dispatch = self._dispatch([430, 20])
        self.assertTrue(dispatch.open_tab_matches())

    def test_an_unlocated_title_is_never_read_as_a_match(self):
        """lanelv cannot be told from Lane 2, so it must not decide."""
        dispatch = self._dispatch(None)
        self.assertFalse(dispatch.open_tab_matches())
        steps = [c.kwargs.get("step_id") for c in dispatch.audit.append.call_args_list]
        self.assertIn("open-tab", steps)

class PickPassTests(unittest.TestCase):
    """Measured 2026-11-27: the pick lost the row the census had resolved."""

    def _dispatch(self, heading="harness CLOUD"):
        dispatch = object.__new__(Dispatch)
        dispatch.label = "Lane 2"
        dispatch.project = "Harness"
        dispatch.audit = Mock()
        dispatch._located_rows = {}
        dispatch.project_of_row = Mock(return_value=heading)
        return dispatch

    def test_a_cloud_heading_row_is_the_lane_the_census_resolved(self):
        """The strict rule the pick used dropped exactly this row."""
        dispatch = self._dispatch()
        row = {"text": "Lane 2", "x": 100, "x1": 300, "y": 200}
        self.assertIs(dispatch._lane_row_in([row], "Lane 2"), row)

    def test_a_heading_scrolled_out_of_frame_leaves_the_exact_row(self):
        dispatch = self._dispatch(heading=None)
        row = {"text": "Lane 2", "x": 100, "x1": 300, "y": 200}
        self.assertIs(dispatch._lane_row_in([row], "Lane 2"), row)

    def test_two_rows_for_one_name_stay_unresolved(self):
        dispatch = self._dispatch()
        rows = [{"text": "Lane 2", "x": 100, "y": 200},
                {"text": "Lane 2", "x": 100, "y": 300}]
        self.assertIsNone(dispatch._lane_row_in(rows, "Lane 2"))

    def test_an_unrelated_heading_is_never_the_lane(self):
        dispatch = self._dispatch(heading="Kalshi-Trader")
        row = {"text": "Lane 2", "x": 100, "x1": 300, "y": 200}
        self.assertIsNone(dispatch._lane_row_in([row], "Lane 2"))

    def test_the_pick_clicks_the_census_row_and_says_so(self):
        dispatch = self._dispatch()
        dispatch._census_prefix_walk = Mock(return_value=(True, [(8, "Lane 2")]))
        dispatch.scroll_sidebar_to_top = Mock(return_value="top")
        row = {"text": "Lane 2", "x": 100, "x1": 300, "y": 200}
        dispatch.settled_roster = Mock(return_value=("frame", [row]))
        dispatch.click_exact_row = Mock()
        with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
            self.assertTrue(dispatch.navigate_by_unique_prefix(narrow=False))
        dispatch.click_exact_row.assert_called_once()
        steps = [c.kwargs.get("step_id") for c in dispatch.audit.append.call_args_list]
        self.assertIn("prefix-pick-census-row", steps)

class ProjectFamilyHeadingTests(unittest.TestCase):
    """Measured 2026-11-27: Lane 2 sits under "harness CLOUD", bound as "Harness"."""

    def _dispatch(self, headings, label="Lane 2", project="Harness"):
        dispatch = object.__new__(Dispatch)
        dispatch.label = label
        dispatch.project = project
        dispatch.audit = Mock()
        dispatch.project_of_row = Mock(side_effect=headings)
        return dispatch

    def test_the_cloud_variant_of_the_bound_project_is_the_same_lane(self):
        dispatch = self._dispatch(["harness CLOUD"])
        found = dispatch.candidates_in([{"text": "Lane 2"}], 1, [])
        self.assertEqual([name for _, name in found], ["Lane 2"])
        steps = [c.kwargs.get("step_id") for c in dispatch.audit.append.call_args_list]
        self.assertIn("project-family-heading", steps)

    def test_an_exact_heading_still_outranks_the_cloud_variant(self):
        dispatch = self._dispatch(["harness CLOUD", "Harness"], label="Lane 1", project="Harness")
        rows = [{"text": "Lane 1"}, {"text": "Lane 1"}]
        found = dispatch.candidates_in(rows, 1, [])
        self.assertEqual(len(found), 1)

    def test_an_unrelated_heading_is_never_the_lane(self):
        dispatch = self._dispatch(["Kalshi-Trader"])
        self.assertEqual(dispatch.candidates_in([{"text": "Lane 2"}], 1, []), [])

class PanelFirstSearchTests(unittest.TestCase):
    """Measured 2026-11-27: the roster walk can never match a clipped lane."""

    def _dispatch(self, rows):
        dispatch = object.__new__(Dispatch)
        dispatch.label = "Lane 2"
        dispatch.thread = "9ecc3453"
        dispatch.project = "Harness"
        dispatch.audit = Mock()
        dispatch.narrow_session_list = Mock(return_value=("frame", rows))
        dispatch.click_roster_row = Mock()
        return dispatch

    def test_the_panel_route_clicks_the_apps_own_title(self):
        # Measured 2026-11-27 from the live sidebar: the row is the app's title,
        # clipped, and no row anywhere reads "Lane 2".
        dispatch = self._dispatch([{"text": "Carrier Census Verifica-"},
                                   {"text": "Carrier Census Verification Review"}])
        with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
            self.assertTrue(dispatch.navigate_by_panel_exact())
        dispatch.click_roster_row.assert_called_once()
        self.assertEqual(dispatch.click_roster_row.call_args.args[3],
                         "Carrier Census Verifica-")

    def test_the_dispatch_label_is_not_what_the_app_prints(self):
        dispatch = self._dispatch([{"text": "Carrier Census Verifica-"}])
        self.assertEqual(dispatch.label, "Lane 2")
        self.assertEqual(dispatch.session_name, "Carrier Census Verification Mission")
        self.assertFalse(Dispatch.row_matches("Carrier Census Verifica-", "Lane 2"))

    def test_a_panel_without_the_exact_row_falls_through_to_the_census(self):
        dispatch = self._dispatch([{"text": "Lane 2 Waist Composition Mission Brief"}])
        self.assertFalse(dispatch.navigate_by_panel_exact())
        dispatch.click_roster_row.assert_not_called()

    def test_open_search_consults_the_panel_before_the_roster_walk(self):
        dispatch = object.__new__(Dispatch)
        dispatch.thread = "9ecc3453"
        dispatch.standing = False
        dispatch.audit = Mock()
        dispatch.window = Mock()
        dispatch.window.handle = "h"
        dispatch.window.api.foreground = Mock(return_value="h")
        dispatch.frame = Mock(return_value="frame")
        dispatch.require_foreground = Mock()
        dispatch.navigate_by_panel_exact = Mock(return_value=True)
        dispatch.navigate_by_session_list = Mock(side_effect=AssertionError("walk"))
        dispatch.scroll_sidebar_to_top = Mock(return_value="frame")
        dispatch.open_search()
        dispatch.navigate_by_panel_exact.assert_called_once()
        # Measured on dyn-7227021046: from the state the previous claim left
        # behind, the panel route was unavailable, so the phase must reset first.
        dispatch.scroll_sidebar_to_top.assert_called_once()

class NarrowedPrefixWalkTests(unittest.TestCase):
    """The unique-prefix proof over a search-filtered roster.

    Measured 2026-11-24T04:48-04:52Z: the exhaustive walk (8 pages at ~30 s)
    spent the register's whole 240 s bound before it could pick, so no dispatch
    reached its phases. Narrowing with the app's own field keeps the same proof
    over the rows that could carry the label, and never falls back silently.
    """

    def _dispatch(self, *, rows, typed="", locate_error=False):
        rows = [dict(row, x=100, x1=300, y=200 + index * 40) if "x" not in row else row
                for index, row in enumerate(rows)]
        dispatch = object.__new__(Dispatch)
        dispatch.label = "Lane 1"
        dispatch.thread = "315608d2"
        dispatch.project = "Harness"
        dispatch.audit = Mock()
        dispatch.require_foreground = Mock()
        dispatch.frame = Mock(return_value=Mock(size=(1800, 1131)))
        dispatch.ensure_search_dialog = Mock(side_effect=lambda current: current)
        dispatch.scroll_sidebar_to_top = Mock(return_value=Mock(size=(1800, 1131)))
        dispatch.read_lines = Mock(return_value=[typed] if typed else [])
        dispatch.locate_exact_text = Mock(
            side_effect=RuntimeError("field missing") if locate_error else None,
            return_value=[700, 200])
        dispatch.act = Mock()
        dispatch.scroll_by = Mock(return_value=False)
        dispatch.settled_roster = Mock(return_value=(Mock(size=(1800, 1131)), rows))
        dispatch.read_roster = Mock(return_value=rows)
        dispatch.click_exact_row = Mock()
        dispatch.click_roster_row = Mock()
        dispatch.project_of_row = Mock(return_value="Harness")
        return dispatch

    def test_one_candidate_on_the_filtered_roster_is_picked(self):
        rows = [{"text": "Harness"}, {"text": "Lane 1"}, {"text": "Vision Driver Standu"}]
        dispatch = self._dispatch(rows=rows, typed="Lane 1")
        with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
            self.assertTrue(dispatch.navigate_by_unique_prefix(narrow=True))
        dispatch.click_roster_row.assert_called_once()
        self.assertEqual(dispatch.click_roster_row.call_args.args[3], "Lane 1")

    def test_two_rivals_are_refused_not_guessed(self):
        """Neither row carries the exact title, so nothing may be picked."""
        rows = [{"text": "Lane 1 Copy"}, {"text": "Lane 1 Second Copy"}]
        dispatch = self._dispatch(rows=rows, typed="Lane 1")
        with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
            self.assertFalse(dispatch.navigate_by_unique_prefix(narrow=True))
        dispatch.click_roster_row.assert_not_called()
        steps = [c.kwargs.get("step_id") for c in dispatch.audit.append.call_args_list]
        self.assertIn("prefix-census", steps)

    def test_the_exact_title_wins_over_a_rival_that_merely_opens_with_it(self):
        """Measured: five chats open with "SCMessenger", one IS SCMessenger."""
        rows = [{"text": "Lane 1"}, {"text": "Lane 1 Second Copy"}]
        dispatch = self._dispatch(rows=rows, typed="Lane 1")
        with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
            self.assertTrue(dispatch.navigate_by_unique_prefix(narrow=True))
        dispatch.click_roster_row.assert_called_once()
        self.assertEqual(dispatch.click_roster_row.call_args.args[3], "Lane 1")
        steps = [c.kwargs.get("step_id") for c in dispatch.audit.append.call_args_list]
        self.assertIn("narrow-exact-rows", steps)

    def test_an_empty_filtered_roster_is_refused(self):
        dispatch = self._dispatch(rows=[{"text": "Harness"}], typed="Lane 1")
        with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
            self.assertFalse(dispatch.navigate_by_unique_prefix(narrow=True))
        dispatch.click_roster_row.assert_not_called()

    def test_typing_that_never_lands_is_refused_not_censused(self):
        """Claim 7123056197 read four stale panel rows because the keystrokes
        never reached the field; the field's own text is now the gate."""
        dispatch = self._dispatch(rows=[{"text": "Lane 1"}], typed="")
        with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
            with self.assertRaises(RuntimeError) as caught:
                dispatch.query_search_field(Mock(size=(1800, 1131)))
        self.assertIn("never showed the query", str(caught.exception))
        steps = [c.kwargs.get("step_id") for c in dispatch.audit.append.call_args_list]
        self.assertNotIn("narrow-query-landed", steps)

    def test_a_field_holding_foreign_text_is_not_typed_over(self):
        dispatch = self._dispatch(rows=[{"text": "Lane 1"}], typed="GitHub Lane Oversight")
        with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
            with self.assertRaises(RuntimeError) as caught:
                dispatch.query_search_field(Mock(size=(1800, 1131)))
        self.assertIn("holds text this query did not write", str(caught.exception))

    def test_typing_that_lands_is_proven_by_the_readback(self):
        dispatch = self._dispatch(rows=[{"text": "Lane 1"}], typed="Lane 1")
        with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
            dispatch.query_search_field(Mock(size=(1800, 1131)))
        steps = [c.kwargs.get("step_id") for c in dispatch.audit.append.call_args_list]
        self.assertIn("narrow-query-landed", steps)

    def test_the_narrowed_walk_is_opt_in_and_off_without_the_flag(self):
        """Unproven live, so no flag means the exhaustive walk runs."""
        import inspect
        signature = inspect.signature(Dispatch.navigate_by_unique_prefix)
        self.assertIsNone(signature.parameters["narrow"].default)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(dispatch_module.narrowing_enabled(tmp))
            (Path(tmp) / "harness-freebuff-runner").mkdir()
            (Path(tmp) / "harness-freebuff-runner" / dispatch_module.NARROW_FLAG).write_text("", encoding="utf-8")
            self.assertTrue(dispatch_module.narrowing_enabled(tmp))

    def test_a_query_already_in_the_field_is_not_typed_again(self):
        dispatch = self._dispatch(rows=[{"text": "Lane 1"}], typed="Lane 1")
        with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
            dispatch.narrow_session_list()
        typed_controls = [c.args[2].get("control") for c in dispatch.act.call_args_list
                          if len(c.args) > 2 and isinstance(c.args[2], dict)]
        self.assertNotIn("Search chats field", typed_controls)
        steps = [c.kwargs.get("step_id") for c in dispatch.audit.append.call_args_list]
        self.assertIn("narrow-reused-query", steps)

    def test_a_missing_field_falls_back_to_the_full_census(self):
        """A3 (2026-11-27): an unreadable field is not a census of the list.

        The walk used to conclude "not found" the moment the search field could
        not be located, which turned one unreadable control into a lane verdict.
        The exhaustive scroll walk now runs before any not-found verdict, and it
        is the census that decides.
        """
        dispatch = self._dispatch(rows=[{"text": "Lane 1"}], typed="", locate_error=True)
        with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
            self.assertTrue(dispatch.navigate_by_unique_prefix(narrow=True))
        dispatch.click_roster_row.assert_not_called()
        dispatch.settled_roster.assert_called()
        dispatch.click_exact_row.assert_called()
        steps = [c.kwargs.get("step_id") for c in dispatch.audit.append.call_args_list]
        self.assertIn("narrow-walk", steps)
        self.assertIn("prefix-unique", steps)

    def test_a_narrowed_walk_with_no_unique_row_still_censuses_before_refusing(self):
        dispatch = self._dispatch(rows=[{"text": "Harness"}], typed="Lane 1")
        with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
            self.assertFalse(dispatch.navigate_by_unique_prefix(narrow=True))
        steps = [c.kwargs.get("step_id") for c in dispatch.audit.append.call_args_list]
        self.assertIn("narrow-no-unique-row", steps)
        self.assertIn("prefix-census", steps)


class _BandFrame:
    """A frame with a selection band painted over one row (measured 47 vs 24)."""

    def __init__(self, band=None):
        self.band = band
        self.width = 1800
        self.height = 1131

    def convert(self, _mode):
        return self

    def getpixel(self, point):
        x, y = point
        if self.band and self.band[0] <= y <= self.band[1] and 88 <= x <= 390:
            return 47
        return 24


class SelectionBandTests(unittest.TestCase):
    """Claim 7124952240: the band was on screen at 47/24 and read as no selection,
    because the old probe compared two pixels at a fixed offset from the OCR box."""

    def test_the_band_over_a_row_is_found(self):
        dispatch = object.__new__(Dispatch)
        frame = _BandFrame(band=(480, 512))
        row = dispatch.highlighted_row(frame, [{"text": "Lane 1", "x": 118, "y": 495, "x1": 300}])
        self.assertEqual(row["text"], "Lane 1")

    def test_a_row_outside_the_band_is_not_selected(self):
        dispatch = object.__new__(Dispatch)
        frame = _BandFrame(band=(480, 512))
        self.assertIsNone(
            dispatch.highlighted_row(frame, [{"text": "Lane 1", "x": 118, "y": 620, "x1": 300}]))

    def test_no_band_means_no_selected_row(self):
        dispatch = object.__new__(Dispatch)
        frame = _BandFrame(band=None)
        self.assertIsNone(
            dispatch.highlighted_row(frame, [{"text": "Lane 1", "x": 118, "y": 495, "x1": 300}]))


class RevealLaneRowTests(unittest.TestCase):
    """Claim 7124457637 opened the lane, then prepare refused identity because
    the walk had left the list scrolled away from the row."""

    def _dispatch(self, pages):
        dispatch = object.__new__(Dispatch)
        dispatch.label = "Lane 1"
        dispatch.thread = "315608d2"
        dispatch.project = "Harness"
        dispatch.audit = Mock()
        dispatch.scroll_sidebar_to_top = Mock(return_value=Mock(size=(1800, 1131)))
        dispatch.frame = Mock(return_value=Mock(size=(1800, 1131)))
        dispatch.settled_roster = Mock(side_effect=[(Mock(), page) for page in pages])
        dispatch.scroll_by = Mock(return_value=True)
        return dispatch

    def test_the_row_is_revealed_on_a_later_page(self):
        rows = [
            [{"text": "Harness"}, {"text": "BigEnergyCo Audit"}],
            [{"text": "Harness"}, {"text": "Lane 1"}],
        ]
        dispatch = self._dispatch(rows)
        with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
            _, found = dispatch.reveal_lane_row()
        self.assertEqual(found[1]["text"], "Lane 1")
        steps = [c.kwargs.get("step_id") for c in dispatch.audit.append.call_args_list]
        self.assertIn("reveal-lane-visible", steps)

    def test_a_row_that_is_never_visible_is_refused_by_name(self):
        dispatch = self._dispatch([[{"text": "Harness"}]] * 4)
        with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
            _, found = dispatch.reveal_lane_row()
        self.assertEqual(found, [])
        steps = [c.kwargs.get("step_id") for c in dispatch.audit.append.call_args_list]
        self.assertIn("reveal-lane", steps)

    def test_reveal_never_runs_in_the_send_phase(self):
        dispatch = self._dispatch([[{"text": "Lane 1"}]])
        dispatch.routes = Mock(return_value=[])
        dispatch.phase = "send"
        dispatch.standing = False
        dispatch.text = "continue in full"
        dispatch.allow_navigation = True
        dispatch.reveal_lane_row = Mock()
        dispatch.selected_label_matches = Mock(return_value=False)
        dispatch.navigate_by_session_list = Mock(return_value=False)
        dispatch.find_highlighted_row = Mock(return_value=None)
        dispatch.saw_text = Mock(return_value=False)
        dispatch.open_tab_matches = Mock(return_value=False)
        dispatch.selection_handoff = Mock(return_value=False)
        with self.assertRaises(RuntimeError):
            dispatch.verify_session_identity()
        dispatch.reveal_lane_row.assert_not_called()
        # The refusal is only reachable when the open title does not name the lane.
        dispatch.open_tab_matches.assert_called_once()


class FreebuffSessionWalkAndDispatchFixTests(unittest.TestCase):
    def test_an_empty_sidebar_never_settles_into_a_roster(self):
        """R17: three empty reads are a re-render, not a census."""
        with tempfile.TemporaryDirectory() as tmp:
            dispatch = object.__new__(Dispatch)
            dispatch.output = Path(tmp)
            dispatch.audit = Mock()
            dispatch.frame = Mock(side_effect=[Mock() for _ in range(6)])
            dispatch.read_roster = Mock(return_value=[])
            with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
                with self.assertRaisesRegex(RuntimeError, "did not settle"):
                    dispatch.settled_roster("probe", SIDEBAR, attempts=3)

    def test_a_scroll_step_that_does_not_move_the_census_is_retried(self):
        """R16: one unchanged page is not the end of the list."""
        with tempfile.TemporaryDirectory() as tmp:
            dispatch = object.__new__(Dispatch)
            dispatch.output = Path(tmp)
            dispatch.audit = Mock()
            dispatch.frame = Mock(return_value=Mock())
            dispatch.scroll_by = Mock(return_value=True)
            censuses = iter([[row("B Harness", 120)],
                             [row("B Harness", 120)],
                             [row("B SCMessenger", 120)]])
            dispatch.read_roster = Mock(side_effect=lambda *args: next(censuses))
            with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
                _, moved = dispatch.advance_sidebar("probe", Mock())

        self.assertTrue(moved)
        self.assertEqual(dispatch.scroll_by.call_count, 2)
        self.assertEqual(dispatch.scroll_by.call_args.args[3], -900)

    def test_the_composer_text_decides_the_route_before_any_model(self):
        """R18: a staged mission preamble is not the 'stop' Jev saw at 0.67."""
        dispatch = object.__new__(Dispatch)
        dispatch.text = "continue in full"
        placeholder = "Ask Freebuff... Use / for commands, @ for files"
        assert dispatch.composer_written_route([], placeholder) is None
        assert dispatch.composer_written_route([placeholder], placeholder) is None
        assert dispatch.composer_written_route(["continue in full"], placeholder) == "staged"
        assert dispatch.composer_written_route(
            ["MISSION START", "SCMESSENGER LANE - FRESH SESSION CARRIER"],
            placeholder) == "foreign"

    def test_a_repeated_page_does_not_end_the_session_list_walk(self):
        dispatch = walking_dispatch(
            [[row("B Harness", 120), row("Disk Audit", 150)],
             [row("B Harness", 120), row("Disk Audit", 150)],
             [row("B SCMessenger", 120), row("SCMessenger", 150)]],
            [True, True])
        with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
            self.assertTrue(dispatch.walk_session_list())
        clicked = dispatch.click_exact_row.call_args.args[2]
        self.assertEqual(clicked["text"], "SCMessenger")

    def test_an_exact_title_on_a_later_page_beats_an_earlier_prefix_rival(self):
        """A page holding only 'SCMessenger Audit Lar' cannot be the lane."""
        dispatch = walking_dispatch(
            [[row("B SCMessenger", 120), row("SCMessenger Audit Lar", 150)],
             [row("B SCMessenger", 120), row("SCMessenger", 150)]],
            [True])
        with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
            self.assertTrue(dispatch.walk_session_list())
        self.assertEqual(dispatch.click_exact_row.call_args.args[2]["text"], "SCMessenger")

    def test_the_only_clipped_candidate_is_picked_after_the_whole_list_is_censused(self):
        dispatch = walking_dispatch(
            [[row("B SCMessenger", 120), row("SCMessenger Bumdown Tc", 150)]],
            [False])
        with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
            self.assertTrue(dispatch.walk_session_list())
        dispatch.click_exact_row.assert_not_called()
        self.assertEqual(dispatch.click_row_by_text.call_args.args[0], "SCMessenger Bumdown Tc")

    def test_prepare_draft_clicks_and_types_when_placeholder_ocr_matches(self):
        """Regression e768fc24: route=='placeholder' must click and type, not abort."""
        dispatch = object.__new__(Dispatch)
        dispatch.recovering = False
        dispatch.scoped_input = True
        dispatch.label = "SCMessenger"
        dispatch.text = "continue in full"
        dispatch.audit = Mock()
        frame = Mock(size=(1800, 1131))
        ready = Mock(size=(1800, 1131))
        dispatch.reestablish_if_reloaded = Mock(return_value=False)
        dispatch.settle_view = Mock(return_value=frame)
        dispatch.verify_lane = Mock()
        dispatch.verify_tier = Mock(return_value="paid")
        dispatch.turn_running = Mock(return_value=False)
        dispatch.locate_exact_text = Mock(return_value=[780, 980])
        dispatch.choose = Mock()
        dispatch.act = Mock()
        dispatch.frame = Mock(return_value=ready)
        dispatch.verify_draft = Mock(return_value=ready)
        with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
            dispatch.prepare_draft()
        dispatch.choose.assert_not_called()
        self.assertEqual([c.args[0] for c in dispatch.act.call_args_list],
                         ["focus-verified-composer", "type-continuation"])
        self.assertEqual(dispatch.act.call_args_list[0].args[2]["point"], [780, 980])

    def test_prepare_draft_resumes_expired_session_with_staged_mission(self):
        """R7: expired free session + staged /mission is resumed, not refused.

        The old refusal protected the owner's staged mission but left the lane
        down, so the register's cure is Resume -> Start with no continuation sent
        after it. The staged mission is never overwritten and no typing happens.
        """
        dispatch = object.__new__(Dispatch)
        dispatch.recovering = False
        dispatch.scoped_input = True
        dispatch.label = "SCMessenger"
        dispatch.text = "continue in full"
        dispatch.audit = Mock()
        frame = Mock(size=(1800, 1131))
        dispatch.reestablish_if_reloaded = Mock(return_value=False)
        dispatch.settle_view = Mock(return_value=frame)
        dispatch.verify_lane = Mock()
        dispatch.verify_tier = Mock(return_value="paid")
        dispatch.turn_running = Mock(return_value=False)
        dispatch.locate_exact_text = Mock(side_effect=RuntimeError("placeholder missing"))
        dispatch.read_lines = Mock(side_effect=[
            ["Your free session has expired. Send your message again to start a new one.", "Retry", "Resume mission"],
            ["/mission ---MISSION START--- SCMESSENGER LANE - FRESH SESSION CARRIER"],
        ])
        dispatch.choose = Mock()
        dispatch.type_literal = Mock()
        dispatch.frame = Mock(return_value=frame)
        dispatch.stop_visible = Mock(return_value=True)
        dispatch.act = Mock()
        with patch("scripts.windows_freebuff_dispatch.resume_staged_session",
                   return_value="resumed") as resume:
            dispatch.prepare_draft()
        resume.assert_called_once()
        self.assertEqual(dispatch.resume_outcome, "resumed")
        dispatch.choose.assert_not_called()
        dispatch.type_literal.assert_not_called()
        self.assertIn("composer-expired-staged-mission",
                      [c.kwargs.get("step_id") for c in dispatch.audit.append.call_args_list])

    def test_disk_audit_verify_lane_refuses_unmatched_active_session(self):
        """Codex P1: Disk tab + cached UUID must not pass while another Disk chat is active."""
        dispatch = object.__new__(Dispatch)
        dispatch.thread = "f90f01e9"
        dispatch.audit = Mock()
        dispatch.require_foreground = Mock(return_value=1)
        dispatch.routes = Mock(return_value=["/chats/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"])
        dispatch.yes = Mock()
        dispatch.require_cached_session = Mock()
        with self.assertRaisesRegex(RuntimeError, "does not match Disk Audit"):
            dispatch.verify_lane(Mock())
        dispatch.yes.assert_not_called()
        dispatch.require_cached_session.assert_not_called()

        dispatch.routes = Mock(return_value=[])
        dispatch.selected_exact_session = Mock(return_value=False)
        with self.assertRaisesRegex(RuntimeError, "could not be bound"):
            dispatch.verify_lane(Mock())

        dispatch.selected_exact_session = Mock(return_value=True)
        dispatch.verify_lane(Mock())
        dispatch.yes.assert_called_once()
        dispatch.require_cached_session.assert_called_once()

    def test_lookup_local_session_uuid_reads_partitions_readonly(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "freebuff-hosted" / "Local Storage" / "leveldb"
            store.mkdir(parents=True)
            (store / "0001.ldb").write_bytes(b'{"id":"2ae32937-c991-4c33-87d4-68b8c956ba98"}')
            self.assertEqual(
                lookup_local_session_uuid("2ae32937", appdata=tmp),
                "2ae32937-c991-4c33-87d4-68b8c956ba98",
            )
            self.assertIsNone(lookup_local_session_uuid("not-hex", appdata=tmp))

    def test_working_banner_and_corroborates_running_guard_against_home_reload(self):
        dispatch = object.__new__(Dispatch)
        dispatch.audit = Mock()
        dispatch.read_lines = Mock(return_value=["Working for 14s", "Queue"])
        self.assertEqual(dispatch.working_banner("w", Mock()), 14)

        dispatch.reloaded = Mock(return_value=True)
        self.assertFalse(dispatch.corroborates_running(Mock(), github_advanced=False))
        self.assertTrue(dispatch.corroborates_running(Mock(), github_advanced=True))


class ComposerTextVerdictTests(unittest.TestCase):
    """A1: the owner's ruling of 2026-11-26 (#684 c.7208601549).

    Four Lane 1 restarts parked in one afternoon on a composer that read
    'typeamessagesentbeforethequeue' - the platform's own control labels glued
    together by the renderer. That is machine text, not an owner draft: relay it
    verbatim, clear it, and keep steering. Parking stays reserved for a person's
    writing.
    """

    def test_the_measured_run_together_label_is_machine_text(self):
        self.assertEqual(dispatch_module.composer_text_verdict(
            "storingagentrequeststate"), "machine")

    def test_a_label_that_lost_only_its_spaces_is_still_machine_text(self):
        self.assertEqual(dispatch_module.composer_text_verdict(
            ["type a message sent before the queue"]), "machine")

    def test_a_person_s_writing_is_a_draft_and_is_never_typed_over(self):
        for reading in (["owner module with an owner test"],
                        ["continue in full after the merge"],
                        ["fix the ledger and file the result"]):
            self.assertEqual(dispatch_module.composer_text_verdict(reading), "draft")
        self.assertEqual(dispatch_module.composer_text_verdict([]), "empty")

    def test_a_single_short_word_is_not_machine_text(self):
        self.assertEqual(dispatch_module.composer_text_verdict(["yes"]), "draft")
        self.assertEqual(dispatch_module.composer_text_verdict(["continue"]), "draft")


class ComposerMachineTextGateTests(unittest.TestCase):
    """A1 end to end over the prepare phase: relay, clear, replace, keep going."""

    def _dispatch(self, written, cleared=()):
        dispatch = object.__new__(Dispatch)
        dispatch.recovering = False
        dispatch.scoped_input = True
        dispatch.standing = True
        dispatch.label = "Lane 1"
        dispatch.text = "continue in full"
        dispatch.audit = Mock()
        dispatch.reestablish_if_reloaded = Mock(return_value=False)
        dispatch.settle_view = Mock(return_value=Mock(size=(1800, 1131)))
        dispatch.verify_lane = Mock()
        dispatch.verify_tier = Mock(return_value="paid")
        dispatch.turn_running = Mock(return_value=False)
        dispatch.locate_exact_text = Mock(side_effect=RuntimeError("no placeholder"))

        def read_lines(step, frame, region):
            if step == "composer-written":
                return written
            if step == "composer-cleared-readback":
                return list(cleared)
            return []

        dispatch.read_lines = Mock(side_effect=read_lines)
        dispatch.relay_composer_text = Mock()
        dispatch.act = Mock()
        dispatch.frame = Mock(return_value=Mock(size=(1800, 1131)))
        dispatch.verify_draft = Mock()
        return dispatch

    def test_machine_text_is_relayed_then_cleared_and_the_continuation_typed(self):
        dispatch = self._dispatch(["storingagentrequeststate"])
        with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
            dispatch.prepare_draft()
        dispatch.relay_composer_text.assert_called_once()
        # The focus step is the renderer the clear posts to: measured on
        # dyn-7228279746, the clear had none because nothing had clicked.
        self.assertEqual([c.args[0] for c in dispatch.act.call_args_list],
                         ["focus-machine-composer", "clear-machine-composer",
                          "focus-verified-composer", "type-continuation"])
        steps = [c.kwargs.get("step_id") for c in dispatch.audit.append.call_args_list]
        self.assertIn("composer-machine-text-replaced", steps)

    def test_a_composer_that_still_holds_machine_text_after_the_clear_refuses(self):
        dispatch = self._dispatch(["storingagentrequeststate"],
                                  cleared=["storingagentrequeststate"])
        with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
            with self.assertRaisesRegex(RuntimeError, "survived the clear"):
                dispatch.prepare_draft()
        self.assertEqual([c.args[0] for c in dispatch.act.call_args_list],
                         ["focus-machine-composer", "clear-machine-composer"])

    def test_an_empty_composer_is_typed_into_not_put_to_a_verdict(self):
        """Measured on dyn-7228809373: the empty composer reached a 0.45 stop guess."""
        dispatch = self._dispatch(["typeamessagesentbeforethequeue"])
        dispatch.yes = Mock(side_effect=AssertionError("a model verdict was asked for"))
        with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
            dispatch.prepare_draft()
        dispatch.relay_composer_text.assert_not_called()
        self.assertEqual([c.args[0] for c in dispatch.act.call_args_list],
                         ["focus-verified-composer", "type-continuation"])
        steps = [c.kwargs.get("step_id") for c in dispatch.audit.append.call_args_list]
        self.assertIn("composer-route-empty", steps)

    def test_an_unrecognised_draft_still_parks_without_any_input(self):
        dispatch = self._dispatch(["owner module with an owner test"])
        with patch("scripts.windows_freebuff_dispatch.time.sleep", Mock()):
            with patch("scripts.windows_freebuff_dispatch.has_send_arrow_outline",
                       return_value=False):
                with self.assertRaisesRegex(RuntimeError, "foreign draft"):
                    dispatch.prepare_draft()
        dispatch.relay_composer_text.assert_not_called()
        self.assertEqual([c.args[0] for c in dispatch.act.call_args_list], [])

class CaptureBudgetTests(unittest.TestCase):
    """A3 (2026-11-27, #684 c.7219862556): a slow frame is retaken, not parked."""

    @staticmethod
    def _clock_and_capture(seconds):
        state = {"t": 0.0}

        def clock():
            return state["t"]

        def capture():
            state["t"] += seconds
            return "payload"

        return clock, capture

    def test_a_capture_just_past_the_old_last_budget_is_retaken_and_succeeds(self):
        clock, capture = self._clock_and_capture(5.321)
        payload, elapsed, attempts = dispatch_module.bounded_capture(capture, clock=clock)
        self.assertEqual(payload, "payload")
        self.assertEqual(attempts, 3)
        self.assertAlmostEqual(elapsed, 5.321, places=3)

    def test_a_capture_that_exceeds_every_budget_still_refuses_by_name(self):
        clock, capture = self._clock_and_capture(20.0)
        with self.assertRaisesRegex(RuntimeError, "capture exceeded"):
            dispatch_module.bounded_capture(capture, clock=clock)


class TierPrecheckTests(unittest.TestCase):
    """A4: a restart never lands a lane on the free tier."""

    def test_a_free_marker_disqualifies_and_a_paid_reading_is_the_seat_of_record(self):
        self.assertEqual(dispatch_module.tier_verdict("DeepSeek V4.1 Flash :free"), "free")
        self.assertEqual(dispatch_module.tier_verdict("GPT-6 Luna High"), "paid")
        self.assertEqual(dispatch_module.tier_verdict(""), "unknown")

    def test_the_gate_refuses_before_any_input_on_a_free_reading(self):
        dispatch = object.__new__(Dispatch)
        dispatch.audit = Mock()
        dispatch.read_lines = Mock(return_value=["DeepSeek V4.1 Flash Free"])
        with patch.dict(os.environ, {"HARNESS_FREEBUFF_MODEL_CHIP": "1200,40,1560,120"}):
            with self.assertRaisesRegex(RuntimeError, "free tier"):
                dispatch.verify_tier(Mock())

    def test_an_uncalibrated_chip_refuses_the_restart(self):
        """Fail-closed: no chip box, no proof of tier, no restart."""
        dispatch = object.__new__(Dispatch)
        dispatch.audit = Mock()
        dispatch.read_lines = Mock()
        with patch.object(dispatch_module, "CHIP_CALIBRATION",
                          Path(tempfile.gettempdir()) / "no-such-model-chip.json"):
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("HARNESS_FREEBUFF_MODEL_CHIP", None)
                with self.assertRaisesRegex(RuntimeError, "cannot be read"):
                    dispatch.verify_tier(Mock())
        dispatch.read_lines.assert_not_called()
        steps = [c.kwargs.get("step_id") for c in dispatch.audit.append.call_args_list]
        self.assertIn("tier-unverified", steps)

    def test_a_chip_that_cannot_be_read_at_all_refuses_the_restart(self):
        dispatch = object.__new__(Dispatch)
        dispatch.audit = Mock()
        dispatch.read_lines = Mock(side_effect=RuntimeError("OCR refused"))
        with patch.dict(os.environ, {"HARNESS_FREEBUFF_MODEL_CHIP": "1200,40,1560,120"}):
            with self.assertRaisesRegex(RuntimeError, "could not be read"):
                dispatch.verify_tier(Mock())

    def test_a_chip_that_reads_as_noise_refuses_the_restart(self):
        dispatch = object.__new__(Dispatch)
        dispatch.audit = Mock()
        dispatch.read_lines = Mock(return_value=["...", "- -"])
        with patch.dict(os.environ, {"HARNESS_FREEBUFF_MODEL_CHIP": "1200,40,1560,120"}):
            with self.assertRaisesRegex(RuntimeError, "no recognizable tier"):
                dispatch.verify_tier(Mock())

    def test_a_paid_reading_is_the_only_restart_the_gate_lets_through(self):
        dispatch = object.__new__(Dispatch)
        dispatch.audit = Mock()
        dispatch.read_lines = Mock(return_value=["DeepSeek V4.1 Flash Slow"])
        with patch.dict(os.environ, {"HARNESS_FREEBUFF_MODEL_CHIP": "1200,40,1560,120"}):
            self.assertEqual(dispatch.verify_tier(Mock()), "paid")

    def test_a_reading_with_no_word_at_all_is_unknown_not_paid(self):
        self.assertEqual(dispatch_module.tier_verdict("... :: --"), "unknown")
        self.assertEqual(dispatch_module.tier_verdict("Free"), "free")
    def test_an_exact_row_wins_in_the_narrowed_panel(self):
        """Measured 2026-11-27: the "Lane 2" panel held a rival and a placeholder."""
        dispatch = object.__new__(Dispatch)
        dispatch.label = "Lane 2"
        dispatch.project = "Harness"
        dispatch.audit = Mock()
        rows = [{"text": "Lane 2"},
                {"text": "Lane 2 Waist Composition Mission Brief"},
                {"text": "Loading..."}]
        found = dispatch.exact_label_rows(rows, 1, [])
        self.assertEqual([name for _, name in found], ["Lane 2"])
        steps = [c.kwargs.get("step_id") for c in dispatch.audit.append.call_args_list]
        self.assertIn("narrow-exact-rows", steps)

    def test_a_prefix_only_row_is_not_this_lane(self):
        dispatch = object.__new__(Dispatch)
        dispatch.label = "Lane 2"
        dispatch.project = "Harness"
        dispatch.audit = Mock()
        rows = [{"text": "Lane 20"}, {"text": "Loading..."}]
        self.assertEqual(dispatch.exact_label_rows(rows, 1, []), [])

    def test_two_exact_rows_stay_ambiguous_and_are_never_guessed(self):
        dispatch = object.__new__(Dispatch)
        dispatch.label = "Lane 2"
        dispatch.project = "Harness"
        dispatch.audit = Mock()
        rows = [{"text": "Lane 2"}, {"text": "Lane 2"}]
        found = dispatch.exact_label_rows(rows, 1, [])
        self.assertEqual(len(found), 2)
        self.assertIsNone(dispatch.resolve_unique(found))

    def test_the_panel_pick_replaces_the_whole_census(self):
        dispatch = object.__new__(Dispatch)
        dispatch.label = "Lane 2"
        dispatch.project = "Harness"
        dispatch.audit = Mock()
        dispatch.narrow_session_list = Mock(return_value=("frame", [
            {"text": "Lane 2"}, {"text": "Lane 2 Waist Composition Mission Brief"}]))
        dispatch.click_roster_row = Mock()
        dispatch._census_prefix_walk = Mock(
            side_effect=AssertionError("the exhaustive walk must not run"))
        self.assertTrue(dispatch.navigate_by_unique_prefix(narrow=True))
        dispatch.click_roster_row.assert_called_once()
        dispatch._census_prefix_walk.assert_not_called()

    def test_a_recorded_calibration_file_is_used_when_the_env_is_unset(self):
        """The watch runs from Task Scheduler: calibration must survive a tick."""
        import tempfile
        from pathlib import Path as _Path
        with tempfile.TemporaryDirectory() as tmp:
            record = _Path(tmp) / "model-chip.json"
            record.write_text('{"region": [925, 1048, 1185, 1088]}', encoding="utf-8")
            with patch.object(dispatch_module, "CHIP_CALIBRATION", record):
                with patch.dict(os.environ, {}, clear=False):
                    os.environ.pop("HARNESS_FREEBUFF_MODEL_CHIP", None)
                    self.assertEqual(dispatch_module.model_chip_region(),
                                     (925, 1048, 1185, 1088))

    def test_the_env_still_overrides_a_recorded_calibration(self):
        import tempfile
        from pathlib import Path as _Path
        with tempfile.TemporaryDirectory() as tmp:
            record = _Path(tmp) / "model-chip.json"
            record.write_text('{"region": [1, 2, 3, 4]}', encoding="utf-8")
            with patch.object(dispatch_module, "CHIP_CALIBRATION", record):
                with patch.dict(os.environ, {"HARNESS_FREEBUFF_MODEL_CHIP": "10,20,30,40"}):
                    self.assertEqual(dispatch_module.model_chip_region(), (10, 20, 30, 40))

    def test_a_missing_or_malformed_calibration_leaves_the_tier_unproven(self):
        import tempfile
        from pathlib import Path as _Path
        with tempfile.TemporaryDirectory() as tmp:
            record = _Path(tmp) / "model-chip.json"
            with patch.object(dispatch_module, "CHIP_CALIBRATION", record):
                with patch.dict(os.environ, {}, clear=False):
                    os.environ.pop("HARNESS_FREEBUFF_MODEL_CHIP", None)
                    self.assertIsNone(dispatch_module.model_chip_region())
            record.write_text("not json", encoding="utf-8")
            with patch.object(dispatch_module, "CHIP_CALIBRATION", record):
                with patch.dict(os.environ, {}, clear=False):
                    os.environ.pop("HARNESS_FREEBUFF_MODEL_CHIP", None)
                    self.assertIsNone(dispatch_module.model_chip_region())

    def test_an_uncalibrated_chip_refuses_before_any_input_is_sent(self):
        """The whole point of the gate: no chip proof, no keystrokes."""
        dispatch = object.__new__(Dispatch)
        dispatch.recovering = True
        dispatch.scoped_input = False
        dispatch.audit = Mock()
        dispatch.settle_view = Mock(return_value="frame")
        dispatch.verify_lane = Mock()
        dispatch.act = Mock()
        dispatch.turn_running = Mock(return_value=False)
        with patch.object(dispatch_module, "CHIP_CALIBRATION",
                          Path(tempfile.gettempdir()) / "no-such-model-chip.json"):
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("HARNESS_FREEBUFF_MODEL_CHIP", None)
                with self.assertRaisesRegex(RuntimeError, "^tier-unverified:"):
                    dispatch.prepare_draft()
        dispatch.act.assert_not_called()
        dispatch.turn_running.assert_not_called()

    def test_a_paid_chip_lets_the_prepare_reach_its_next_step(self):
        dispatch = object.__new__(Dispatch)
        dispatch.recovering = True
        dispatch.scoped_input = True
        dispatch.audit = Mock()
        dispatch.settle_view = Mock(return_value="frame")
        dispatch.verify_lane = Mock()
        dispatch.read_lines = Mock(return_value=["DeepSeek V4.1 Flash Slow"])
        dispatch.turn_running = Mock(side_effect=RuntimeError("sentinel-next-step"))
        with patch.dict(os.environ, {"HARNESS_FREEBUFF_MODEL_CHIP": "1200,40,1560,120"}):
            with self.assertRaisesRegex(RuntimeError, "sentinel-next-step"):
                dispatch.prepare_draft()
        dispatch.turn_running.assert_called_once()

    def test_a_malformed_chip_box_is_refused_rather_than_guessed(self):
        with patch.dict(os.environ, {"HARNESS_FREEBUFF_MODEL_CHIP": "1200,40"}):
            with self.assertRaisesRegex(RuntimeError, "left,top,right,bottom"):
                dispatch_module.model_chip_region()


if __name__ == "__main__":
    unittest.main()
