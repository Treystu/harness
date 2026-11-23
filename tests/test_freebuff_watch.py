from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from PIL import Image

from driver_core.audit import AuditLog
from scripts import windows_freebuff_t4 as census
from scripts import windows_freebuff_watch as watch
from scripts import windows_freebuff_runner as runner
from scripts.windows_freebuff_dispatch import Dispatch


def test_legacy_census_pause_does_not_block_queue(monkeypatch):
    known = {"paused.json", "armed.json"}
    receipts = {}
    monkeypatch.setattr(watch, "worktree_head", lambda: "pushed-head")
    monkeypatch.setenv("HARNESS_VISION_HEAD", "pushed-head")
    monkeypatch.setattr(watch, "checkpoints", lambda: known)
    monkeypatch.setattr(watch, "read_checkpoint", lambda name: {"state": "adapter-unavailable"})
    monkeypatch.setattr(watch, "pause_requested", lambda: None)
    monkeypatch.setattr(watch, "validate_receipts", lambda: receipts)
    monkeypatch.setattr(watch, "checkpoint", write := Mock())
    monkeypatch.setattr(watch, "issue_comment", Mock())
    monkeypatch.setattr(watch, "run_restoration", lambda receipts, known: False)
    monkeypatch.setattr(watch, "run_burn", run := Mock())

    watch.main()

    assert write.call_args.args[0] == f"parked-{watch.CENSUS}.json"
    run.assert_called_once_with(receipts, known)


def test_owner_pause_preempts_any_admission(monkeypatch):
    monkeypatch.setattr(watch, "worktree_head", lambda: "pushed-head")
    monkeypatch.setattr(watch, "checkpoints", lambda: {"armed.json"})
    monkeypatch.setattr(watch, "pause_requested", lambda: 123)
    monkeypatch.setattr(watch, "issue_comment", Mock())
    monkeypatch.setattr(watch, "checkpoint", write := Mock())
    monkeypatch.setattr(watch, "run_burn", run := Mock())

    watch.main()

    write.assert_called_once_with("owner-paused.json", {"dispatch": 123, "state": "owner-paused"})
    run.assert_not_called()


def test_github_response_uses_utf8(monkeypatch):
    result = Mock(returncode=0, stdout='{"body":"RESTART — ready"}')
    run = Mock(return_value=result)
    monkeypatch.setattr(runner.subprocess, "run", run)

    assert runner.api("example") == {"body": "RESTART — ready"}
    assert run.call_args.kwargs["encoding"] == "utf-8"


def test_interrupted_items_skip_to_next_unclaimed_row(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(watch, "guard_approval", Mock())
    monkeypatch.setattr(watch, "desktop_idle", lambda: True)
    monkeypatch.setattr(watch, "checkpoint", write := Mock())
    monkeypatch.setattr(watch, "execute", execute := Mock(return_value=1))
    known = {f"claim-{watch.CENSUS}-2ae32937.json", f"claim-{watch.BURNDOWN}-0d7e2f37.json"}
    receipts = {watch.BURN_QUEUE: {"created_at": datetime.now(timezone.utc).isoformat(), "body": "pinned"}}

    watch.run_burn(receipts, known)

    assert execute.call_args.args[2]["thread"] == "7d4a9b14"
    assert [args.args[0] for args in write.call_args_list] == [
        f"claim-{watch.BURNDOWN}-7d4a9b14.json",
        f"result-{watch.BURNDOWN}-7d4a9b14.json",
    ]


def test_project_roster_rejects_unbounded_accessibility_list():
    group = {"name": "SCMessenger", "kind": "ControlType.List", "partial": True,
             "children": [{"name": "SCMessenger", "kind": "ControlType.ListItem"}]}
    with pytest.raises(RuntimeError, match="partial"):
        census.project_roster({"groups": [group]})


def test_census_reidentifies_row_on_fresh_stable_frame():
    old = Image.new("RGB", (400, 200), "black")
    fresh = Image.new("RGB", (400, 200), "white")
    driver = Mock()
    driver.frame.side_effect = [fresh, fresh]
    driver.read_roster.return_value = [{"text": "SCMessenger"}]
    driver.locate_exact_text.return_value = [150, 100]
    census.visual_select_row(driver, old, "SCMessenger", 100, "candidate")
    assert driver.locate_exact_text.call_args.args[1] is fresh
    assert driver.locate_exact_text.call_args.kwargs["scale"] == 2
    driver.yes.assert_called_once()
    driver.act.assert_called_once()


def test_census_refuses_row_changed_after_verification():
    driver = Mock()
    old = Image.new("RGB", (400, 200), "white")
    driver.frame.side_effect = [old, Image.new("RGB", (400, 200), "black")]
    driver.read_roster.return_value = [{"text": "SCMessenger"}]
    with pytest.raises(RuntimeError, match="changed before selection"):
        census.visual_select_row(driver, old, "SCMessenger", 100, "candidate")
    driver.act.assert_not_called()


def test_census_tolerates_only_small_ocr_differences_for_navigation():
    assert census.similar_census_label("SCMessenger Audit Lar", "SCMessenger Audit Lan")
    assert not census.similar_census_label("SCMessenger Audit Lar", "SCMessenger Cloud Cure")


def test_census_jev_verifies_visible_prefix_without_guessing_clipped_suffix():
    frame = Image.new("RGB", (400, 200), "white")
    driver = Mock()
    driver.frame.side_effect = [frame, frame]
    driver.read_roster.return_value = [{"text": "SCMessenger Audit Lar"}]
    census.visual_select_row(driver, frame, "SCMessenger Audit Lar", 100, "candidate")
    assert "SCMessenger Audit'" in driver.yes.call_args.args[2]
    assert "Lar" not in driver.yes.call_args.args[2]


def test_census_scrolls_past_sticky_footer_after_project_heading(monkeypatch):
    def line(text, x, y):
        return {"text": text, "words": [{"text": text, "x": 2 * (x - 95), "y": 2 * (y - 294)}]}

    pages = iter([{"lines": [line("SCMessenger", 120, 960), line("Invite friends", 115, 1040)]},
                  {"lines": [line("SCMessenger", 132, 800), line("Next project", 120, 900)]}])
    monkeypatch.setattr(census, "inspect_crop", lambda *args: next(pages))
    monkeypatch.setattr(census.time, "sleep", lambda _: None)
    driver = Mock()
    first = Image.new("RGB", (1800, 1131), "white")
    second = Image.new("RGB", (1800, 1131), "black")
    driver.frame.return_value = second
    pages = list(census.visual_project_pages(driver, first))
    assert [label for _, _, rows in pages for label, _ in rows] == ["SCMessenger"]
    driver.act.assert_called_once()


def test_census_waits_for_capture_geometry_before_navigation(monkeypatch):
    monkeypatch.setattr(census.time, "sleep", lambda _: None)
    driver = Mock()
    driver.frame.side_effect = [Image.new("RGB", (400, 194)), Image.new("RGB", (400, 200))]
    driver.compositor_bounds.return_value = Mock(left=0, top=0, right=400, bottom=200)
    assert census.settled_census_frame(driver).size == (400, 200)
    assert driver.frame.call_count == 2
    driver.act.assert_not_called()


def test_census_match_requires_active_uuid_and_both_activity_markers():
    fields = {"toolbar": "Local DeepSeek V4.1 Flash Slow", "transcript-upper": "#745",
              "transcript-lower": "Codex #746", "rail_marks": 22,
              "document_sessions": ["2ae32937-c991-4c33-87d4-68b8c956ba98"]}
    assert census.census_signature(fields)
    assert not census.census_signature(fields | {"document_sessions": []})
    assert not census.census_signature(fields | {"transcript-lower": "Older work"})


def test_selected_row_ignores_the_leading_status_glyph():
    assert Dispatch.row_matches("Ra Vision Driver Standup al V", "Vision Driver Standup and Audit")


def test_cure_never_replays_an_uncertain_send(tmp_path):
    evidence = tmp_path / "send"
    evidence.mkdir()
    receipt = AuditLog(tmp_path / "runner.jsonl")
    receipt.append("verification", step_id="result", state="parked: identify-foreground refused")
    trace = AuditLog(evidence / "driver.jsonl")
    trace.append("action", step_id="observation-foreground", action="focus_freebuff", ok=False)
    assert watch.cure_eligible(tmp_path, ("identify-",))
    trace.append("action", step_id="send-once", action="send_freebuff", ok=False)
    assert not watch.cure_eligible(tmp_path, ("identify-",))


def test_scm_timeout_cure_is_admitted_after_vision_seat(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
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
    monkeypatch.setattr(watch, "desktop_idle", lambda: True)
    monkeypatch.setattr(watch, "guard_approval", Mock())
    monkeypatch.setattr(watch, "checkpoint", Mock())
    monkeypatch.setattr(watch, "execute", execute := Mock(return_value=1))

    assert watch.run_restoration({watch.SCM_RESTART: {"body": "authorized"}}, known)
    assert execute.call_args.args[1] == f"{item}-project-roster-cure"
    assert execute.call_args.args[2]["phases"] == ("project-census",)
