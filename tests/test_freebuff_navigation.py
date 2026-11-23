"""The class cure for lane standup: settled rosters, unique rows, named refusals."""

import json
import os
from unittest.mock import Mock

import pytest

from scripts.windows_freebuff_dispatch import SIDEBAR, Dispatch, same_rows


def shim(tmp_path, frames):
    dispatch = object.__new__(Dispatch)
    dispatch.output = tmp_path
    dispatch.audit = Mock()
    dispatch.frame = Mock(side_effect=frames)
    return dispatch


def test_clipped_sidebar_label_matches_but_a_short_prefix_does_not():
    assert Dispatch.row_matches("Kalshi Paper Burndov", "Kalshi Paper Burndown")
    assert Dispatch.row_matches("Kalshi Paper Burndown", "Kalshi Paper Burndown")
    assert not Dispatch.row_matches("Kalshi Paper Rotation at", "Kalshi Paper Burndown")
    assert not Dispatch.row_matches("Lane", "Lane 1")
    assert not Dispatch.row_matches("Lane 1", "Lane 2")


def test_selection_waits_for_two_identical_rosters(tmp_path, monkeypatch):
    frames = [Mock(name=f"frame-{index}") for index in range(3)]
    dispatch = shim(tmp_path, frames)
    censuses = [
        [{"text": "Lane 1", "x": 133, "y": 740, "x1": 200}],
        [{"text": "Lane 1", "x": 133, "y": 752, "x1": 200}],
        [{"text": "Lane 1", "x": 133, "y": 752, "x1": 200}],
    ]
    dispatch.read_roster = Mock(side_effect=lambda step, frame, region: censuses.pop(0))
    monkeypatch.setattr("scripts.windows_freebuff_dispatch.time.sleep", Mock())

    frame, rows = dispatch.settled_roster("probe", SIDEBAR)

    assert frame is frames[2]
    assert rows[0]["text"] == "Lane 1"
    assert not censuses


def test_a_roster_that_never_settles_refuses_by_name(tmp_path, monkeypatch):
    dispatch = shim(tmp_path, [Mock() for _ in range(8)])
    positions = iter([740, 752, 764, 726, 738, 750])
    dispatch.read_roster = Mock(side_effect=lambda step, frame, region: [
        {"text": "Kalshi Paper Burndown", "x": 133, "y": next(positions), "x1": 200}])
    monkeypatch.setattr("scripts.windows_freebuff_dispatch.time.sleep", Mock())

    with pytest.raises(RuntimeError, match="did not settle"):
        dispatch.settled_roster("probe", SIDEBAR, attempts=3)


def test_a_short_label_matches_its_own_row_through_the_icon_glyph():
    assert Dispatch.row_matches("Lane 1", "Lane 1")
    assert Dispatch.row_matches("B Lane 1", "Lane 1")
    assert Dispatch.row_matches("Ra Lane 2 Waist Composition Mission Brief", "Lane 2")
    assert not Dispatch.row_matches("Lane 1", "Lane 2")


def test_a_phantom_row_settles_but_a_moved_row_does_not():
    stationary = (370, 385, 400)
    phantom = (370, 377, 385, 400)
    moved = (370, 391, 400)

    assert same_rows(stationary, stationary)
    assert same_rows(stationary, phantom)
    assert not same_rows(stationary, moved)


def test_ocr_flicker_on_a_stationary_row_still_settles(tmp_path, monkeypatch):
    """The measured case: one row, two readings, no movement at all."""
    frames = [Mock(name=f"frame-{index}") for index in range(3)]
    dispatch = shim(tmp_path, frames)
    readings = [[{"text": "Kalshi Paper Bumd", "x": 133, "y": 740, "x1": 200}],
                [{"text": "Kalshi Paper Burndc V", "x": 133, "y": 740, "x1": 200}]]
    calls = []

    def flicker(step, frame, region):
        calls.append(step)
        return readings[(len(calls) - 1) % 2]

    dispatch.read_roster = Mock(side_effect=flicker)
    monkeypatch.setattr("scripts.windows_freebuff_dispatch.time.sleep", Mock())

    frame, rows = dispatch.settled_roster("probe", SIDEBAR)

    assert frame is frames[1]
    assert rows[0]["text"] in {"Kalshi Paper Bumd", "Kalshi Paper Burndc V"}
    assert Dispatch.row_matches(rows[0]["text"], "Kalshi Paper Burndown")


def test_ambiguous_row_refusal_names_every_candidate(tmp_path):
    dispatch = object.__new__(Dispatch)
    dispatch.output = tmp_path
    dispatch.audit = Mock()
    dispatch.frame = Mock(return_value=Mock())
    rows = [{"text": "Lane 1", "x": 133, "y": 700, "x1": 200},
            {"text": "Lane 2", "x": 133, "y": 724, "x1": 200}]

    with pytest.raises(RuntimeError, match="matched 0 settled rows"):
        dispatch.click_roster_row("select", Mock(), rows, "Lane 3")


def test_a_reloaded_window_must_census_non_empty_twice_before_use(tmp_path, monkeypatch):
    """The empty sidebar after a reload is not a roster: wait for two agreeing ones."""
    frames = [Mock(name=f"frame-{index}") for index in range(6)]
    dispatch = shim(tmp_path, frames)
    censuses = iter([[], [], [{"text": "Lane 1", "x": 133, "y": 740, "x1": 200}],
                     [{"text": "Lane 1", "x": 133, "y": 740, "x1": 200}]])
    dispatch.read_roster = Mock(side_effect=lambda step, frame, region: next(censuses))
    monkeypatch.setattr("scripts.windows_freebuff_dispatch.time.sleep", Mock())

    frame, rows = dispatch.stable_window("reload")

    assert rows[0]["text"] == "Lane 1"
    assert frame is frames[2]


def test_a_window_that_never_census_anything_refuses_by_name(tmp_path, monkeypatch):
    dispatch = shim(tmp_path, [Mock() for _ in range(6)])
    dispatch.read_roster = Mock(return_value=[])
    monkeypatch.setattr("scripts.windows_freebuff_dispatch.time.sleep", Mock())
    monkeypatch.setattr("scripts.windows_freebuff_dispatch.time.monotonic",
                        Mock(side_effect=[0, 1, 2, 3, 40]))

    with pytest.raises(RuntimeError, match="stable roster"):
        dispatch.stable_window("reload", seconds=5, attempts=3)


def test_a_project_heading_and_its_chat_are_separated_by_the_glyph():
    """SCMessenger's project heading and one chat share a name; only the chat is plain."""
    rows = [{"text": "B SCMessenger", "x": 133, "y": 517, "x1": 200},
            {"text": "SCMessenger", "x": 133, "y": 561, "x1": 200}]
    assert [row for row in rows if Dispatch.row_matches(row["text"], "SCMessenger")] == rows
    assert len([row for row in rows if row["text"].strip() == "SCMessenger"]) == 1


def live_sidebar():
    """The measured 2026-11-23 layout: a CLOUD Lane 1 above the LOCAL one."""
    return [{"text": "B GitHub", "x": 60, "y": 250, "x1": 200},
            {"text": "Vision Driver Standu", "x": 72, "y": 270, "x1": 330},
            {"text": "Disk Audit", "x": 72, "y": 290, "x1": 330},
            {"text": "harness CLOUD", "x": 60, "y": 330, "x1": 200},
            {"text": "Lane 2", "x": 72, "y": 350, "x1": 330},
            {"text": "Ra Lane 1", "x": 72, "y": 370, "x1": 330},
            {"text": "Harness", "x": 60, "y": 410, "x1": 200},
            {"text": "Ra Harness Audit Lane", "x": 72, "y": 430, "x1": 330},
            {"text": "Ra Lane 2", "x": 72, "y": 450, "x1": 330},
            {"text": "Ra Lane 1", "x": 72, "y": 470, "x1": 330}]


def test_headings_distinguish_cloud_from_local():
    assert Dispatch.heading_name("B GitHub") == "GitHub"
    assert Dispatch.heading_name("harness CLOUD") == "harness CLOUD"
    assert Dispatch.heading_name("Harness") == "Harness"
    assert Dispatch.heading_name("Ra Lane 1") is None


def test_a_row_is_bound_to_the_heading_above_it():
    rows = live_sidebar()
    cloud, local = rows[5], rows[9]
    assert Dispatch.project_of_row(rows, cloud) == "harness CLOUD"
    assert Dispatch.project_of_row(rows, local) == "Harness"
    # No heading above this row in the frame: unscoped, never guessed.
    above = {"text": "Ra Lane 1", "x": 72, "y": 100, "x1": 330}
    assert Dispatch.project_of_row(rows, above) is None


def test_a_cloud_lane_1_does_not_satisfy_the_local_lane_1():
    """The 19:30Z false green: title alone accepted the CLOUD row."""
    rows = live_sidebar()
    cloud, local = rows[5], rows[9]
    assert Dispatch.row_matches(cloud["text"], "Lane 1")
    assert not Dispatch.scoped_row(rows, cloud, "Lane 1", "Harness")
    assert Dispatch.scoped_row(rows, local, "Lane 1", "Harness")
    assert not Dispatch.scoped_row(rows, local, "Lane 1", "harness CLOUD")


def test_a_row_without_a_visible_heading_is_refused():
    row = {"text": "Ra Lane 1", "x": 72, "y": 900, "x1": 330}
    assert not Dispatch.scoped_row([row], row, "Lane 1", "Harness")


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


def test_a_standing_run_reclaims_a_transient_temp_console(tmp_path, monkeypatch):
    """R1: the two-minute watch console must not park a valid send."""
    activate = Mock(return_value=True)
    monkeypatch.setattr("scripts.windows_freebuff_dispatch.activate_exact", activate)
    monkeypatch.setattr("scripts.windows_freebuff_dispatch.time.sleep", Mock())
    dispatch = foreground_shim(111, [222, 111], transient=True)

    assert dispatch.require_foreground() == 111
    activate.assert_called_once()
    assert any(call.args[0] == "verification" and call.kwargs.get("step_id") == "foreground-obtained"
               for call in dispatch.audit.append.call_args_list)


def test_a_standing_run_never_takes_foreground_from_an_owner_surface(tmp_path, monkeypatch):
    activate = Mock(return_value=True)
    monkeypatch.setattr("scripts.windows_freebuff_dispatch.activate_exact", activate)
    dispatch = foreground_shim(111, [222, 222], transient=False)

    with pytest.raises(RuntimeError, match="not the foreground"):
        dispatch.require_foreground()
    activate.assert_not_called()


def test_the_watch_console_is_recognised_by_its_temp_python_title():
    dispatch = object.__new__(Dispatch)
    dispatch.user = Mock()
    dispatch.window = Mock()
    temp = os.path.join(os.environ.get("TEMP", os.environ.get("LOCALAPPDATA", "")),
                        "harness-notepad-venv-20261122", "Scripts", "python.exe")
    dispatch.window.api.title_of.return_value = temp
    assert dispatch.transient_holder(1)
    dispatch.window.api.title_of.return_value = "C:\\Windows\\explorer.exe"
    assert not dispatch.transient_holder(1)


def test_an_ended_turn_is_not_running_even_when_the_stop_glyph_flickers(tmp_path):
    dispatch = object.__new__(Dispatch)
    dispatch.stop_visible = Mock(return_value=True)
    dispatch.turn_ended_banner = Mock(return_value=True)
    assert not dispatch.turn_running(Mock())
    dispatch.turn_ended_banner.return_value = False
    assert dispatch.turn_running(Mock())


def test_a_marker_is_released_only_by_a_pre_input_foreground_refusal(tmp_path):
    dispatch = object.__new__(Dispatch)
    dispatch.output = tmp_path
    trace = tmp_path / "driver.jsonl"
    trace.write_text(json.dumps({
        "kind": "action", "step_id": "send-once", "ok": False,
        "detail": "executor failed: FreeBuff is not the foreground window; held by hwnd 1"}) + "\n",
        encoding="utf-8")
    assert dispatch.prior_send_refused_before_input()
    trace.write_text(json.dumps({
        "kind": "action", "step_id": "send-once", "ok": True, "detail": ""}) + "\n",
        encoding="utf-8")
    assert not dispatch.prior_send_refused_before_input()
