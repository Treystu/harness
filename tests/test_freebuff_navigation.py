"""The class cure for lane standup: settled rosters, unique rows, named refusals."""

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
