from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from driver_core.audit import AuditLog
from scripts import windows_freebuff_t4 as census
from scripts import windows_freebuff_watch as watch


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


def test_census_match_requires_active_uuid_and_both_activity_markers():
    fields = {"toolbar": "Local DeepSeek V4.1 Flash Slow", "transcript-upper": "#745",
              "transcript-lower": "Codex #746", "rail_marks": 22,
              "document_sessions": ["2ae32937-c991-4c33-87d4-68b8c956ba98"]}
    assert census.census_signature(fields)
    assert not census.census_signature(fields | {"document_sessions": []})
    assert not census.census_signature(fields | {"transcript-lower": "Older work"})


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
