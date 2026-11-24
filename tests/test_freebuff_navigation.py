"""The class cure for lane standup: settled rosters, unique rows, named refusals."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.windows_freebuff_dispatch import SIDEBAR, Dispatch, same_rows


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
        temp = os.path.join(os.environ.get("TEMP", os.environ.get("LOCALAPPDATA", "")),
                            "harness-notepad-venv-20261122", "Scripts", "python.exe")
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


def walking_dispatch(monkeypatch, pages, advances):
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
    monkeypatch.setattr("scripts.windows_freebuff_dispatch.time.sleep", Mock())
    return dispatch


def test_a_scroll_step_that_does_not_move_the_census_is_retried(tmp_path, monkeypatch):
    """R16: one unchanged page is not the end of the list."""
    dispatch = object.__new__(Dispatch)
    dispatch.output = tmp_path
    dispatch.audit = Mock()
    dispatch.frame = Mock(return_value=Mock())
    dispatch.scroll_by = Mock(return_value=True)
    censuses = iter([[row("B Harness", 120)],
                     [row("B Harness", 120)],
                     [row("B SCMessenger", 120)]])
    dispatch.read_roster = Mock(side_effect=lambda *args: next(censuses))
    monkeypatch.setattr("scripts.windows_freebuff_dispatch.time.sleep", Mock())

    _, moved = dispatch.advance_sidebar("probe", Mock())

    assert moved
    assert dispatch.scroll_by.call_count == 2
    assert dispatch.scroll_by.call_args.args[3] == -900


def test_a_repeated_page_does_not_end_the_session_list_walk(monkeypatch):
    dispatch = walking_dispatch(
        monkeypatch,
        [[row("B Harness", 120), row("Disk Audit", 150)],
         [row("B Harness", 120), row("Disk Audit", 150)],
         [row("B SCMessenger", 120), row("SCMessenger", 150)]],
        [True, True])

    assert dispatch.walk_session_list()
    clicked = dispatch.click_exact_row.call_args.args[2]
    assert clicked["text"] == "SCMessenger"


def test_an_exact_title_on_a_later_page_beats_an_earlier_prefix_rival(monkeypatch):
    """A page holding only "SCMessenger Audit Lar" cannot be the lane."""
    dispatch = walking_dispatch(
        monkeypatch,
        [[row("B SCMessenger", 120), row("SCMessenger Audit Lar", 150)],
         [row("B SCMessenger", 120), row("SCMessenger", 150)]],
        [True])

    assert dispatch.walk_session_list()
    assert dispatch.click_exact_row.call_args.args[2]["text"] == "SCMessenger"


def test_the_only_clipped_candidate_is_picked_after_the_whole_list_is_censused(monkeypatch):
    dispatch = walking_dispatch(
        monkeypatch,
        [[row("B SCMessenger", 120), row("SCMessenger Bumdown Tc", 150)]],
        [False])

    assert dispatch.walk_session_list()
    dispatch.click_exact_row.assert_not_called()
    assert dispatch.click_row_by_text.call_args.args[0] == "SCMessenger Bumdown Tc"


if __name__ == "__main__":
    unittest.main()
