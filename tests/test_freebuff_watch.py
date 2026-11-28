"""Tests for the FreeBuff watch, runner, and SCM project census."""

from datetime import datetime, timezone
import hashlib
import json
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
from scripts import windows_freebuff_dispatch as dispatch
from scripts import windows_freebuff_runner as runner
from scripts import windows_freebuff_t4 as census
from scripts import windows_freebuff_watch as watch
from scripts.windows_freebuff_dispatch import Dispatch


def recent_stamp(minutes):
    """A dispatch timestamp inside the claim's own 24-hour bound.

    Fixed stamps date the fixture: the 2026-11-25 literals this file used
    passed the bound on 2026-11-26 and the drain test began failing for the
    clock rather than for the behaviour it pins.
    """
    from datetime import timedelta
    return ((datetime.now(timezone.utc) - timedelta(minutes=minutes))
            .strftime("%Y-%m-%dT%H:%M:%SZ"))


def runtime_present():
    """Stand in the desktop runtime that the claiming paths require.

    ``require_driver_runtime`` refuses when windows_capture/PIL are absent, and
    that refusal is correct in production - it is also true on every hermetic
    CI leg, which is why five tests failed there while passing under the
    interpreter the watch actually runs on. The tests below are about the claim
    path, so they present the runtime explicitly; the refusal keeps its own test
    against a controlled probe.
    """
    return patch.object(watch.importlib.util, "find_spec", lambda name: object())


def pinned_home(tmp_path, *lanes):
    """A pinned runtime home carrying one registered steer per lane (G13).

    The claim path reads a lane's continuation from the pinned home rather than
    improvising one, so a test that expects a claim to execute has to register
    its lane exactly as production does. The text is written as bytes: the
    verdict carries the prompt's sha256 over those bytes.
    """
    home = Path(tmp_path) / "runtime-home"
    prompts = home / "registry" / "standing-prompts"
    prompts.mkdir(parents=True, exist_ok=True)
    for lane in lanes:
        stem = watch.standing_prompts.lane_slug(lane)
        (prompts / f"{stem}.md").write_bytes(f"STEER {lane}\n".encode("utf-8"))
    return home


class _Surface:
    """Records the primitives a driver surface offers, so a sequence can be read."""

    def __init__(self, *, stops, labels, rows=(), missing=None, reading=None):
        self.stops = list(stops)
        self.labels = labels
        self.rows = list(rows)
        self.missing = missing
        self.reading = reading
        self.acts = []
        self.typed = []
        self.audit = Mock()
        self.size = (1800, 1131)

    class _Frame:
        def __init__(self, size):
            self.size = size

    def frame(self, step):
        return self._Frame(self.size)

    def settle_view(self, step):
        return self._Frame(self.size)

    def locate_exact_text(self, step, frame, label, region, **_kwargs):
        if self.missing and label == self.missing:
            raise RuntimeError(f"{step}: exact OCR label {label!r} was not verified")
        return list(self.labels[label])

    def yes(self, step, frame, question, *, region):
        return True

    def act(self, step, action, params):
        self.acts.append(params["control"])

    def stop_visible(self, frame):
        return self.stops.pop(0) if self.stops else False

    def type_literal(self, text):
        self.typed.append(text)

    def read_lines(self, step, frame, region):
        return [self.reading if self.reading is not None else "My Project"]

    def settled_roster(self, step, region, attempts=6):
        return self.frame(step), self.rows

    @staticmethod
    def _norm(text):
        return " ".join(text.casefold().split())


class ResumeStartCureTests(unittest.TestCase):
    """R7: an expired session holding a staged /mission is resumed, not refused."""

    def test_the_expired_staged_state_is_read_from_exact_ocr(self):
        self.assertTrue(dispatch.expired_with_staged_mission(
            ["Your free session has expired"], ["/mission", "Mission start"]))
        self.assertFalse(dispatch.expired_with_staged_mission(
            ["Your free session has expired"], ["continue in full"]))
        self.assertFalse(dispatch.expired_with_staged_mission(
            ["Ask Freebuff..."], ["/mission"]))

    def test_resume_then_start_leaves_the_lane_starting(self):
        surface = _Surface(stops=[False, False, True],
                           labels={"Resume mission": (900, 700), "Start mission": (900, 600)})
        with patch.object(dispatch.time, "sleep"):
            outcome = dispatch.resume_staged_session(surface, surface.frame("f"))
        self.assertEqual(outcome, "started")
        self.assertEqual(surface.acts, ["Resume mission", "Start mission"])

    def test_a_resume_that_already_runs_sends_nothing_more(self):
        surface = _Surface(stops=[True],
                           labels={"Resume mission": (900, 700), "Start mission": (900, 600)})
        with patch.object(dispatch.time, "sleep"):
            outcome = dispatch.resume_staged_session(surface, surface.frame("f"))
        self.assertEqual(outcome, "resumed")
        self.assertEqual(surface.acts, ["Resume mission"])

    def test_no_running_cue_is_refused_by_name(self):
        surface = _Surface(stops=[False],
                           labels={"Resume mission": (900, 700), "Start mission": (900, 600)})
        with patch.object(dispatch.time, "sleep"):
            with self.assertRaises(RuntimeError) as caught:
                dispatch.resume_staged_session(surface, surface.frame("f"))
        self.assertIn("no running Stop cue appeared", str(caught.exception))


class _SingleUseSurface(_Surface):
    """A surface whose controls can be located exactly once each.

    This is the composition proof's measuring stick: a Resume-then-Start built as
    two independent driver actions locates each control again in its own pass,
    and here the second locate raises. One bounded action locates each once.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.located = []

    def locate_exact_text(self, step, frame, label, region, **_kwargs):
        if label in self.located:
            raise RuntimeError(f"{step}: exact OCR label {label!r} was not verified")
        self.located.append(label)
        return super().locate_exact_text(step, frame, label, region, **_kwargs)


def _bystander_dir():
    """A real folder for observe_bystander, which makes its own phase subfolder."""
    return Path(tempfile.mkdtemp(prefix="t5-"))


class BystanderIdleTests(unittest.TestCase):
    """Dispatch 7125497229: an idle bystander lane was read as a failed one."""

    def _audit(self):
        audit = Mock()
        audit.append = Mock()
        return audit

    def test_an_idle_lane_is_idle_not_a_failure(self):
        audit = self._audit()
        error = RuntimeError("observe-running: the separate Lane 1 Stop square is absent")
        with patch.object(runner, "run_phases", side_effect=error), \
                patch.object(runner.Path, "mkdir"):
            outcome = runner.observe_bystander(_bystander_dir(), audit, "before")
        self.assertEqual(outcome, runner.BYSTANDER_IDLE)
        steps = [c.kwargs.get("step_id") for c in audit.append.call_args_list]
        self.assertIn("t5-before-idle", steps)

    def test_any_other_failure_still_parks(self):
        audit = self._audit()
        with patch.object(runner, "run_phases", side_effect=RuntimeError("capture failed")), \
                patch.object(runner.Path, "mkdir"):
            self.assertFalse(runner.observe_bystander(_bystander_dir(), audit, "before"))

    def test_only_a_live_observation_is_paired(self):
        self.assertTrue(runner.bystander_needs_pair(True))
        self.assertFalse(runner.bystander_needs_pair(runner.BYSTANDER_IDLE))
        self.assertFalse(runner.bystander_needs_pair(False))


class ResumeStartCompositionTests(unittest.TestCase):
    """R7: Resume staging then Start firing is ONE bounded driver action.

    The failure this pins is the one that matters on a live lane: splitting the
    composition into two actions gives the second one its own frame and its own
    consent, so Start can fire against a session that moved on between them.
    """

    def test_one_call_locates_each_control_once_and_fires_both(self):
        surface = _SingleUseSurface(stops=[False, False, True],
                                    labels={"Resume mission": (900, 700),
                                            "Start mission": (900, 600)})
        with patch.object(dispatch.time, "sleep"):
            outcome = dispatch.resume_staged_session(surface, surface.frame("f"))
        self.assertEqual(outcome, "started")
        self.assertEqual(surface.acts, ["Resume mission", "Start mission"])
        self.assertEqual(surface.located, ["Resume mission", "Start mission"])

    def test_a_second_pass_at_the_same_controls_is_refused(self):
        """Split into two actions, the second locate has nothing left to find."""
        surface = _SingleUseSurface(stops=[False, False, True],
                                    labels={"Resume mission": (900, 700),
                                            "Start mission": (900, 600)})
        with patch.object(dispatch.time, "sleep"):
            dispatch.resume_staged_session(surface, surface.frame("f"))
            with self.assertRaises(RuntimeError) as caught:
                dispatch.resume_staged_session(surface, surface.frame("f2"))
        self.assertIn("was not verified", str(caught.exception))

    def test_start_is_located_on_a_frame_taken_after_the_resume_click(self):
        surface = _Surface(stops=[False, False, True],
                           labels={"Resume mission": (900, 700), "Start mission": (900, 600)})
        seen = []
        original = surface.locate_exact_text

        def recording(step, frame, label, region, **kwargs):
            seen.append((label, id(frame)))
            return original(step, frame, label, region, **kwargs)

        surface.locate_exact_text = recording
        with patch.object(dispatch.time, "sleep"):
            dispatch.resume_staged_session(surface, surface.frame("before"))
        self.assertEqual([label for label, _ in seen], ["Resume mission", "Start mission"])
        self.assertNotEqual(seen[0][1], seen[1][1])


class ProjectCreationCureTests(unittest.TestCase):
    """R10: a dispatch can create a project and hand its row on."""

    def test_create_names_the_project_and_hands_back_its_row(self):
        surface = _Surface(stops=[], rows=[{"text": "My Project"}],
                           labels={"New project": (120, 130), "Project name": (700, 400),
                                   "Create project": (900, 900)})
        with patch.object(dispatch.time, "sleep"):
            row = dispatch.create_project(surface, "My Project")
        self.assertEqual(row["text"], "My Project")
        self.assertEqual(surface.typed, ["My Project"])
        self.assertEqual(surface.acts,
                         ["New project", "Project name field", "Create project"])

    def test_a_missing_control_refuses_by_name_and_creates_nothing(self):
        surface = _Surface(stops=[], rows=[{"text": "My Project"}],
                           labels={"New project": (120, 130), "Project name": (700, 400),
                                   "Create project": (900, 900)},
                           missing="Create project")
        with patch.object(dispatch.time, "sleep"):
            with self.assertRaises(RuntimeError) as caught:
                dispatch.create_project(surface, "My Project")
        self.assertIn("the create control 'Create project' was not visible", str(caught.exception))
        self.assertEqual(surface.acts, ["New project"])
        self.assertEqual(surface.typed, [])

    def test_a_name_that_does_not_read_back_is_refused(self):
        surface = _Surface(stops=[], rows=[{"text": "My Project"}], reading="My Proj",
                           labels={"New project": (120, 130), "Project name": (700, 400),
                                   "Create project": (900, 900)})
        with patch.object(dispatch.time, "sleep"):
            with self.assertRaises(RuntimeError) as caught:
                dispatch.create_project(surface, "My Project")
        self.assertIn("the name field reads", str(caught.exception))
        self.assertEqual(surface.acts, ["New project", "Project name field"])


class IsolatedCaptureTests(unittest.TestCase):
    """The capture backend faults natively (0xc0000005 in GraphicsCapture.dll),
    so a frame is taken in a child process and a dead worker is re-taken once."""

    def _screen(self):
        from scripts.windows_notepad_window import WindowsWindowScreen
        window = Mock()
        window.require_window.return_value = 4242
        return WindowsWindowScreen(window, source="windows-freebuff")

    def test_a_crashed_worker_is_replaced_by_one_more(self):
        from driver_core.observation import GUI, Target
        screen = self._screen()
        calls = []

        def run(command, **_kwargs):
            calls.append(command)
            if len(calls) == 1:
                return Mock(returncode=-1073741819, stdout=b"", stderr=b"")
            Path(command[command.index("--out") + 1]).write_bytes(b"frame-bytes")
            return Mock(returncode=0, stdout=b"ok", stderr=b"")

        with tempfile.TemporaryDirectory() as tmp, patch("subprocess.run", side_effect=run):
            capture = screen.capture_isolated(Target("existing FreeBuff desktop", GUI),
                                              Path(tmp) / "f.png")
        self.assertEqual(capture.payload, b"frame-bytes")
        self.assertEqual(len(calls), 2)
        self.assertIn("--capture-once", calls[0])
        self.assertEqual(calls[0][calls[0].index("--capture-once") + 1], "4242")

    def test_two_dead_workers_are_refused_by_name(self):
        from driver_core.observation import GUI, Target
        screen = self._screen()
        dead = Mock(returncode=-1073741819, stdout=b"", stderr=b"")
        with tempfile.TemporaryDirectory() as tmp, \
             patch("subprocess.run", return_value=dead):
            with self.assertRaises(RuntimeError) as caught:
                screen.capture_isolated(Target("existing FreeBuff desktop", GUI),
                                        Path(tmp) / "f.png")
        self.assertIn("the capture worker died 2 times", str(caught.exception))
        self.assertIn("exit -1073741819", str(caught.exception))


class CaptureBudgetTests(unittest.TestCase):
    def test_one_slow_frame_is_retaken_instead_of_escalated(self):
        """Dispatch 7122154514 escalated at `sidebar-top-3-after: capture exceeded
        2s` with the window healthy; a slow snapshot is re-taken once."""
        ticks = iter([0.0, 2.4, 10.0, 10.3])
        payloads = iter(["slow-frame", "fresh-frame"])
        payload, elapsed, attempts = dispatch.bounded_capture(
            lambda: next(payloads), clock=lambda: next(ticks))
        self.assertEqual(payload, "fresh-frame")
        self.assertEqual(attempts, 2)
        self.assertAlmostEqual(elapsed, 0.3)

    def test_a_fast_frame_is_never_retaken(self):
        calls = []

        def capture():
            calls.append(1)
            return "only"

        ticks = iter([0.0, 0.4])
        payload, elapsed, attempts = dispatch.bounded_capture(capture, clock=lambda: next(ticks))
        self.assertEqual((payload, attempts), ("only", 1))
        self.assertEqual(len(calls), 1)

    def test_every_budget_must_be_exceeded_before_the_capture_refuses(self):
        ticks = iter([0.0, 11.0, 11.0, 23.0, 23.0, 35.0])
        with self.assertRaises(RuntimeError) as caught:
            dispatch.bounded_capture(lambda: "slow", clock=lambda: next(ticks))
        self.assertIn("capture exceeded 10s on 3 attempts", str(caught.exception))


class FreebuffWatchTests(unittest.TestCase):
    def test_legacy_census_pause_does_not_block_queue(self):
        known = {"paused.json", "armed.json"}
        receipts = {}
        write = Mock()
        run = Mock()
        with patch.object(watch, "local_control_state", lambda: {"enabled": True, "paused": False}), \
             patch.object(watch, "worktree_head", lambda **_kw: "pushed-head"), \
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
        run.assert_called_once_with(receipts, known, ())

    def test_owner_pause_preempts_any_admission(self):
        write = Mock()
        run = Mock()
        with patch.object(watch, "local_control_state", lambda: {"enabled": True, "paused": False}), \
             patch.object(watch, "worktree_head", lambda **_kw: "pushed-head"), \
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
                 patch.object(watch, "foreground_blocker", return_value=None), \
                 patch.object(watch, "checkpoint", write), \
                 runtime_present(), \
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
                 runtime_present(), \
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
        """A paused tick does no work - and says what it is holding; a stopped
        tick does nothing at all."""
        import json
        with tempfile.TemporaryDirectory() as tmp:
            ctl = Path(tmp) / "control.json"
            ctl.write_text(json.dumps({"enabled": True, "paused": True}), encoding="utf-8")
            with patch.dict("os.environ", {"HARNESS_DRIVER_CONTROL_FILE": str(ctl)}), \
                 patch.object(watch, "worktree_head") as head_mock, \
                 patch.object(watch, "report_paused") as paused_mock:
                watch.main()
            head_mock.assert_not_called()
            paused_mock.assert_called_once()
            ctl.write_text(json.dumps({"enabled": False, "paused": False}), encoding="utf-8")
            with patch.dict("os.environ", {"HARNESS_DRIVER_CONTROL_FILE": str(ctl)}), \
                 patch.object(watch, "worktree_head") as head_mock, \
                 patch.object(watch, "report_paused") as paused_mock:
                watch.main()
            head_mock.assert_not_called()
            paused_mock.assert_not_called()

    def test_a_stale_upstream_ref_is_refreshed_before_the_watch_refuses(self):
        """Cure for the 2026-11-25 silence: a pushed head whose remote-tracking
        ref lagged read as unpushed and every tick returned before its first
        checkpoint. A mismatch now fetches once and re-reads instead."""
        with patch.object(watch, "_head_pair", side_effect=[
                ("ok", "a" * 40, "b" * 40), ("ok", "a" * 40, "a" * 40)]), \
             patch.object(watch, "refresh_upstream", return_value=True) as fetch_mock:
            self.assertEqual(watch.worktree_head(refresh=True), "a" * 40)
        fetch_mock.assert_called_once()
        with patch.object(watch, "_head_pair", return_value=("ok", "a" * 40, "b" * 40)), \
             patch.object(watch, "refresh_upstream", return_value=False):
            self.assertIsNone(watch.worktree_head(refresh=True))

    def test_a_refused_tick_files_the_reason_instead_of_going_silent(self):
        """13:11Z-15:06Z on 2026-11-25: ~55 ticks exited 0 writing no checkpoint
        and no comment, which reads exactly like a tick that did its work."""
        with patch.object(watch, "worktree_head", return_value=None), \
             patch.object(watch, "head_refusal_detail",
                          return_value="HEAD deadbeef is not published at upstream cafe0000"), \
             patch.object(watch, "report_refusal") as refusal:
            watch.main()
        refusal.assert_called_once()
        self.assertIn("not published", refusal.call_args.args[0])

    def test_a_refusal_is_filed_once_per_bucket_per_reason(self):
        with patch.object(watch, "checkpoints", return_value=set()), \
             patch.object(watch, "checkpoint") as checkpoint_mock, \
             patch.object(watch, "issue_comment") as comment_mock:
            self.assertTrue(watch.report_refusal("HEAD deadbeef is not published at upstream cafe0000"))
            self.assertFalse(watch.report_refusal("HEAD deadbeef is not published at upstream cafe0000"))
        checkpoint_mock.assert_called_once()
        comment_mock.assert_called_once()

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

    def test_parse_dynamic_dispatch_accepts_the_oversight_action_requested_wording(self):
        """The L1-STOP dispatch 7119751841 says "Action requested", not
        "Action for the runner:"; refusing it made the reserved test launch
        unclaimable while the watch kept heartbeating "no unclaimed dispatches"."""
        now = datetime(2026, 11, 24, 4, 20, tzinfo=timezone.utc)
        comment = {
            "id": 7119751841,
            "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-24T02:05:55Z",
            "body": (
                "RESTART DISPATCH — episode L1-STOP-939 (from harness oversight tick 939)\n"
                "\n"
                "Lane: Lane 1 (combined prepare+gate+land lane, DeepSeek V4.1 Flash Slow, "
                "thread 315608d2).\n"
                "\n"
                "Action requested (runner alone, per the 2026-11-22 cutover): in-place "
                'restart only — exactly "continue in full".'
            ),
        }
        parsed = watch.parse_dynamic_dispatch(comment, now=now)
        self.assertEqual(parsed["kind"], "restart")
        self.assertEqual(parsed["thread"], watch.THREAD)
        self.assertEqual(parsed["text"], watch.CONTINUATION)

        prose = dict(comment, body=(
            "RESTART DISPATCH — not an instruction\n"
            "Lane: Lane 1\n"
            'The owner already said action requested "continue in full" elsewhere.'))
        self.assertIsNone(watch.parse_dynamic_dispatch(prose, now=now))

    def test_parse_dynamic_dispatch_accepts_the_lane1_retry_banner(self):
        """Dispatch 7122154514 leads with "DISPATCH - LANE 1 RESTART, RETRY
        UNDER THE CURED BOUND". Requiring the literal RESTART DISPATCH prefix
        left the reserved retry unclaimable; it is a restart in every other
        respect, so it must claim, and a banner that never says restart must
        not."""
        now = datetime(2026, 11, 24, 4, 40, tzinfo=timezone.utc)
        comment = {
            "id": 7122154514,
            "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-24T04:35:12Z",
            "body": (
                "DISPATCH - LANE 1 RESTART, RETRY UNDER THE CURED BOUND (2026-11-23;\n"
                "gate receipt in this filing).\n"
                "\n"
                "Action requested: execute ONE in-place restart of Lane 1 (thread\n"
                "315608d2, LOCAL Harness, Flash Slow): send its staged \"continue in\n"
                "full\" - no duplicate session, no model/settings change, no other\n"
                "text.\n"
            ),
        }
        # Filed as wrapped: the quoted instruction spans a line break.
        self.assertIn('"continue in\nfull"', comment["body"])
        parsed = watch.parse_dynamic_dispatch(comment, now=now)
        self.assertEqual(parsed["kind"], "restart")
        self.assertEqual(parsed["thread"], watch.THREAD)
        self.assertEqual(parsed["text"], watch.CONTINUATION)

        fill = dict(comment, id=7122154599, body=(
            "DISPATCH - FILL STAGES 1-8\n"
            "Action requested: stand every lane up in stage order.\n"
            'Send "continue in full" to each idle lane (thread 2ae32937).\n'))
        self.assertIsNone(watch.parse_dynamic_dispatch(fill, now=now))

    def test_parse_dynamic_dispatch_accepts_the_banner_lane_and_runner_action_wording(self):
        """Episodes L1-STOP-1014 and SCM-STOP-1242 were unclaimed while the watch
        heartbeated "no unclaimed dispatches".

        7145072019 files the instruction as "Runner action requested:" and names
        the lane only in the banner; 7146588401 names only "SCMessenger" in the
        banner and writes no ``Lane:`` line at all. Both are the same bounded
        restart the earlier wording described, so both must claim.
        """
        now = datetime(2026, 11, 24, 23, 0, tzinfo=timezone.utc)
        lane1 = {
            "id": 7145072019,
            "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-24T21:32:47Z",
            "body": (
                "RESTART DISPATCH — Lane 1, episode L1-STOP-1014 (oversight tick 1014, "
                "harness-codex-lane-oversight)\n\n"
                "Lane 1 is PRESUMED STOPPED under Clause 6/7 GitHub-first detection.\n\n"
                'Runner action requested: in-place restart only — exactly "continue in full"; '
                "never a duplicate session, never model/settings changes.\n"
            ),
        }
        parsed = watch.parse_dynamic_dispatch(lane1, now=now)
        self.assertEqual(parsed["kind"], "restart")
        self.assertEqual(parsed["thread"], watch.THREAD)
        self.assertEqual(parsed["text"], watch.CONTINUATION)

        scm = {
            "id": 7146588401,
            "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-24T22:44:26Z",
            "body": (
                "RESTART DISPATCH — SCMessenger, episode SCM-STOP-1242 "
                "(lane-continuation-overnight watch run 123)\n\n"
                "Action for the runner: restart SCMessenger in place with exactly "
                '\"continue in full\"; never a duplicate session.\n'
            ),
        }
        parsed = watch.parse_dynamic_dispatch(scm, now=now)
        self.assertEqual(parsed["kind"], "restart")
        self.assertEqual(parsed["thread"], watch.SCM_THREAD)

    def test_a_lane_named_only_in_body_prose_is_not_an_addressee(self):
        now = datetime(2026, 11, 24, 23, 0, tzinfo=timezone.utc)
        comment = {
            "id": 990020,
            "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-24T22:00:00Z",
            "body": (
                "RESTART DISPATCH — fleet sweep\n\n"
                "Context: Lane 1 was restarted earlier and must not move again.\n"
                'Action for the runner: execute "continue in full" where addressed.\n'
            ),
        }
        self.assertIsNone(watch.parse_dynamic_dispatch(comment, now=now))

    def test_parse_dynamic_dispatch_accepts_a_bare_action_line(self):
        """Episodes L1-STOP-980/991/999/1003 file the instruction as "ACTION
        (runner only, ...)" or "Action: ..."; refusing that wording left four
        owner restarts unclaimable while the watch reported nothing to claim."""
        now = datetime(2026, 11, 24, 19, 0, tzinfo=timezone.utc)
        comment = {
            "id": 7140150416,
            "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-24T18:05:47Z",
            "body": (
                "RESTART DISPATCH — harness-codex-lane-oversight tick 1003, episode L1-STOP-1003\n"
                "Lane: Lane 1 (combined prepare+gate+land lane)\n"
                'Action: in-place restart only — exactly "continue in full"; never a duplicate session.\n'
            ),
        }
        parsed = watch.parse_dynamic_dispatch(comment, now=now)
        self.assertEqual(parsed["kind"], "restart")
        self.assertEqual(parsed["thread"], watch.THREAD)

    def test_parse_dynamic_dispatch_accepts_a_burn_window_inline_action(self):
        """All six 08:51Z burn rows wrote Action: mid-paragraph.

        Measured 2026-11-25: the banner matched and the lane resolved for each,
        and only the line-start rule refused the instruction; every scan listed
        them as not claimable until the 09:29Z restart set superseded them.
        """
        now = datetime(2026, 11, 25, 9, 40, tzinfo=timezone.utc)
        comment = {
            "id": 7157548700,
            "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-25T08:50:59Z",
            "body": (
                "BURN WINDOW DISPATCH - BigEnergyCo launch. Owner order (Lucas).\n"
                "Lane: BigEnergyCo (LOCAL project - session titled 'BigEnergyCo Full Burndown').\n"
                "State: staged since 12:03 HST with its /mission carrier. Action: re-read "
                "session state before acting; restart in place (Resume -> Start on "
                "the staged carrier).\n"
            ),
        }
        parsed = watch.parse_dynamic_dispatch(comment, now=now)
        self.assertEqual(parsed["kind"], "restart")
        self.assertEqual(parsed["mode"], "staged-resume")
        self.assertEqual(parsed["thread"], "0d7e2f37")

    def test_inline_action_is_refused_outside_a_burn_window_banner(self):
        now = datetime(2026, 11, 25, 9, 40, tzinfo=timezone.utc)
        comment = {
            "id": 7157548701,
            "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-25T08:50:59Z",
            "body": (
                "RESTART DISPATCH - BigEnergyCo.\n"
                "Lane: BigEnergyCo\n"
                "State: staged. Action: restart in place (Resume -> Start on the staged carrier).\n"
            ),
        }
        self.assertIsNone(watch.parse_dynamic_dispatch(comment, now=now))

    def test_a_lane_cancelled_at_the_control_surface_is_never_claimed(self):
        """Measured 2026-11-25 01:28Z: the control file carried
        cancelled_lanes=[\"315608d2\"] while Lane 1 restarts stayed claimable."""
        now = datetime(2026, 11, 25, 1, 30, tzinfo=timezone.utc)
        comment = {
            "id": 7145072019, "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-24T21:32:47Z",
            "body": ("RESTART DISPATCH — Lane 1, episode L1-STOP-1014\n"
                     'Runner action requested: restart with "continue in full".\n'),
        }
        with tempfile.TemporaryDirectory() as tmp:
            execute = Mock()
            with patch.dict("os.environ", {"LOCALAPPDATA": tmp}), \
                 patch.object(watch, "api", return_value=[comment]), \
                 patch.object(watch, "guard_approval", Mock()), \
                 patch.object(watch, "checkpoint", Mock()), \
                 patch.object(watch, "issue_comment", Mock()), \
                 patch.object(watch, "execute", execute):
                self.assertFalse(watch.poll_dynamic_dispatches(
                    set(), now=now, cancelled=(watch.THREAD,)))
            execute.assert_not_called()
        # The control surface is where the operator writes that list, and the
        # watch reads it once per tick rather than inside the claim scan.
        path = Path(tempfile.mkdtemp()) / "control.json"
        path.write_text(json.dumps({"paused": False,
                                    "cancelled_lanes": [watch.THREAD]}), encoding="utf-8")
        with patch.dict("os.environ", {"HARNESS_DRIVER_CONTROL_FILE": str(path)}):
            self.assertEqual(watch.local_control_state()["cancelled_lanes"], (watch.THREAD,))

    def test_a_cancelled_episode_is_closed_and_never_claimed(self):
        """The dispatch's own bound is "execute only while episode X is OPEN";
        a later owner CANCELLATION that names X closes it."""
        now = datetime(2026, 11, 24, 21, 50, tzinfo=timezone.utc)
        dispatch = {
            "id": 7143702385, "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-24T21:10:00Z",
            "body": ("RESTART DISPATCH — Lane 1, episode L1-STOP-1010\n"
                     'Action for the runner: restart with "continue in full".\n'),
        }
        cancellation = {
            "id": 7144433519, "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-24T21:04:10Z",
            "body": ("CANCELLATION — Lane 1 restart dispatch 7143702385, episode L1-STOP-1010\n"
                     "Do NOT execute the restart against the recovered lane.\n"),
        }
        self.assertTrue(watch.parse_dynamic_dispatch(dispatch, now=now))
        self.assertTrue(watch.episode_closed([dispatch, cancellation], dispatch,
                                             watch.parse_dynamic_dispatch(dispatch, now=now)))
        with tempfile.TemporaryDirectory() as tmp:
            execute = Mock()
            with patch.dict("os.environ", {"LOCALAPPDATA": tmp}), \
                 patch.object(watch, "api", return_value=[dispatch, cancellation]), \
                 patch.object(watch, "guard_approval", Mock()), \
                 patch.object(watch, "checkpoint", Mock()), \
                 patch.object(watch, "issue_comment", Mock()), \
                 patch.object(watch, "execute", execute):
                self.assertFalse(watch.poll_dynamic_dispatches(set(), now=now))
            execute.assert_not_called()

    def test_a_cancellation_of_another_episode_does_not_close_this_one(self):
        now = datetime(2026, 11, 24, 22, 0, tzinfo=timezone.utc)
        dispatch = {
            "id": 7145072019, "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-24T21:32:47Z",
            "body": ("RESTART DISPATCH — Lane 1, episode L1-STOP-1014\n"
                     'Runner action requested: restart with "continue in full".\n'),
        }
        other = {
            "id": 7143702385, "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-24T21:10:00Z",
            "body": ("RESTART DISPATCH — Lane 1, episode L1-STOP-1010\n"
                     'Action for the runner: restart with "continue in full".\n'),
        }
        cancellation = {
            "id": 7144433519, "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-24T21:04:10Z",
            "body": ("CANCELLATION — Lane 1 restart dispatch 7143702385, episode L1-STOP-1010\n"
                     "Do NOT execute the restart.\n"),
        }
        parsed = watch.parse_dynamic_dispatch(dispatch, now=now)
        self.assertFalse(watch.episode_closed([other, cancellation, dispatch], dispatch, parsed))

    def test_a_superseded_restart_is_never_claimed_after_a_newer_one(self):
        """Measured 2026-11-25 01:06Z: with the wording cure live, the oldest
        unclaimed id won and the watch executed 7129310215 (L1-STOP-974, filed
        10:50Z) although episode L1-STOP-1014 was the open one. Supersession is
        the episode check the dispatches themselves state."""
        now = datetime(2026, 11, 24, 23, 0, tzinfo=timezone.utc)
        older = {
            "id": 7129310215, "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-24T10:50:17Z",
            "body": ("RESTART DISPATCH — Lane 1, episode L1-STOP-974\n"
                     'Action for the runner: restart with "continue in full".\n'),
        }
        newer = dict(older, id=7145072019, created_at="2026-11-24T21:32:47Z",
                     body=("RESTART DISPATCH — Lane 1, episode L1-STOP-1014\n"
                           'Runner action requested: restart with "continue in full".\n'))
        with tempfile.TemporaryDirectory() as tmp:
            home = pinned_home(tmp, watch.SESSIONS[watch.THREAD][0])
            write = Mock()
            execute = Mock(return_value=0)
            with patch.dict("os.environ", {"LOCALAPPDATA": tmp,
                                           "HARNESS_DRIVER_RUNTIME_ROOT": str(home)}), \
                 patch.object(watch, "api", return_value=[older, newer]), \
                 patch.object(watch, "guard_approval", Mock()), \
                 patch.object(watch, "desktop_idle", lambda: True), \
                 patch.object(watch, "foreground_blocker", return_value=None), \
                 patch.object(watch, "checkpoint", write), \
                 patch.object(watch, "issue_comment", Mock()), \
                 patch.object(watch, "advance_cursor", Mock()), \
                 runtime_present(), \
                 patch.object(watch, "execute", execute):
                self.assertTrue(watch.poll_dynamic_dispatches(set(), now=now))
            # The superseded row now gets its own durable verdict instead of
            # being skipped in silence, so the claim is not the first write.
            self.assertEqual([call.args[0] for call in write.call_args_list],
                             ["skip-dyn-7129310215-315608d2.json",
                              "claim-dyn-7145072019-315608d2.json",
                              "ack-dyn-7145072019-315608d2.json",
                              "result-dyn-7145072019-315608d2.json"])
            self.assertEqual(write.call_args_list[0].args[1]["state"], "superseded")
            self.assertEqual(execute.call_args.args[2]["dispatch"], 7145072019)

    def test_poll_reports_a_dispatch_it_cannot_parse_instead_of_nothing_to_claim(self):
        now = datetime(2026, 11, 24, 23, 0, tzinfo=timezone.utc)
        comments = [{
            "id": 990021,
            "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-24T22:30:00Z",
            "body": "RESTART DISPATCH — fleet sweep\nNo instruction line here.\n",
        }]
        unclaimed = {}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"LOCALAPPDATA": tmp}), \
                 patch.object(watch, "api", return_value=comments), \
                 patch.object(watch, "execute", Mock()) as execute:
                self.assertFalse(watch.poll_dynamic_dispatches(set(), now=now, unclaimed=unclaimed))
        self.assertEqual(unclaimed, {990021: "no-instruction"})
        execute.assert_not_called()

    def test_filed_on_issue_skips_a_dispatch_another_channel_already_executed(self):
        comments = [
            {"id": 7117989632, "body": "RESTART DISPATCH — SCMessenger"},
            {"id": 7119856718,
             "body": "Vision restart ack #7117989632: `2ae32937`, receipt dyn-7117989632-2ae32937."},
        ]
        self.assertTrue(watch.filed_on_issue(comments, 7117989632))
        self.assertFalse(watch.filed_on_issue(comments, 7119751841))

    def test_poll_dynamic_dispatches_skips_an_already_acked_restart(self):
        now = datetime(2026, 11, 24, 4, 20, tzinfo=timezone.utc)
        comments = [
            {"id": 990010, "user": {"id": watch.OWNER_ID},
             "created_at": "2026-11-24T02:00:00Z",
             "body": "RESTART DISPATCH\nLane: SCMessenger\nAction requested: \"continue in full\""},
            {"id": 990011, "user": {"id": watch.OWNER_ID},
             "created_at": "2026-11-24T02:10:00Z",
             "body": "Vision restart ack #990010: `2ae32937`, receipt dyn-990010-2ae32937."},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            execute = Mock(return_value=0)
            with patch.dict("os.environ", {"LOCALAPPDATA": tmp}), \
                 patch.object(watch, "api", return_value=comments), \
                 patch.object(watch, "guard_approval", Mock()), \
                 patch.object(watch, "desktop_idle", lambda: True), \
                 patch.object(watch, "checkpoint", Mock()), \
                 patch.object(watch, "issue_comment", Mock()), \
                 patch.object(watch, "execute", execute):
                self.assertFalse(watch.poll_dynamic_dispatches(set(), now=now))
            execute.assert_not_called()

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
            home = pinned_home(tmp, watch.SESSIONS[watch.SCM_THREAD][0])
            write = Mock()
            posted = Mock()
            execute = Mock(return_value=0)
            with patch.dict("os.environ", {"LOCALAPPDATA": tmp,
                                           "HARNESS_DRIVER_RUNTIME_ROOT": str(home)}), \
                 patch.object(watch, "api", return_value=comments), \
                 patch.object(watch, "guard_approval", Mock()), \
                 patch.object(watch, "desktop_idle", lambda: True), \
                 patch.object(watch, "foreground_blocker", return_value=None), \
                 patch.object(watch, "checkpoint", write), \
                 patch.object(watch, "issue_comment", posted), \
                 patch.object(watch, "advance_cursor", Mock()), \
                 runtime_present(), \
                 patch.object(watch, "execute", execute):
                self.assertTrue(watch.poll_dynamic_dispatches({"claim-dyn-990002-antigravity.json"}, now=now))
            mission = execute.call_args.args[2]
            self.assertEqual(mission["thread"], watch.SCM_THREAD)
            self.assertEqual(mission["text"], "STEER SCMessenger\n")
            self.assertEqual(mission["prompt_file"], "scmessenger.md")
            self.assertEqual(write.call_args_list[0].args[0], "claim-dyn-990003-2ae32937.json")
            self.assertEqual(write.call_args_list[1].args[0], "ack-dyn-990003-2ae32937.json")
            self.assertEqual(write.call_args_list[2].args[0], "result-dyn-990003-2ae32937.json")
            self.assertEqual(write.call_args_list[2].args[1]["prompt_sha256"],
                             hashlib.sha256(b"STEER SCMessenger\n").hexdigest())

    def test_a_claimed_dispatch_is_never_re_run_by_the_watch(self):
        """At-most-once under the cutover: after the Lane 1 claim parked at the
        phase deadline, Product Jev escalated an auto-retry draft, so retry
        authority stays with oversight and the watch keeps the spent claim."""
        now = datetime(2026, 11, 24, 4, 30, tzinfo=timezone.utc)
        comments = [{
            "id": 7119751841, "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-24T02:05:55Z",
            "body": "RESTART DISPATCH\nLane: Lane 1\nAction requested: \"continue in full\"",
        }]
        with tempfile.TemporaryDirectory() as tmp:
            execute = Mock(return_value=0)
            with patch.dict("os.environ", {"LOCALAPPDATA": tmp}), \
                 patch.object(watch, "api", return_value=comments), \
                 patch.object(watch, "checkpoint", Mock()), \
                 patch.object(watch, "execute", execute):
                self.assertFalse(watch.poll_dynamic_dispatches(
                    {"claim-dyn-7119751841-315608d2.json"}, now=now))
            execute.assert_not_called()

    def test_missing_driver_runtime_is_refused_by_name_before_a_claim(self):
        """L17: the %TEMP% proof venv is not durable, so the runtime the watch
        actually runs under is checked before any claim and named when absent.

        Both halves are measured against a controlled probe rather than the
        ambient interpreter: the hermetic CI legs have no windows_capture, so
        asserting that this interpreter has it made the suite red exactly where
        it was supposed to be portable.
        """
        with patch.object(watch.importlib.util, "find_spec", lambda name: object()):
            self.assertIsNone(watch.require_driver_runtime())
        with patch.object(watch.importlib.util, "find_spec",
                          side_effect=lambda name: None if name == "windows_capture" else object()):
            with self.assertRaisesRegex(RuntimeError, "driver runtime missing: windows_capture"):
                watch.require_driver_runtime()

    def test_the_daily_hours_banner_is_named_as_a_quota_refusal(self):
        """Measured 2026-11-25 18:01 HST on the SCMessenger session: the app
        renders "Today's hours are used up ... Your daily hours refill at 12:00
        AM HST" and never says "usage limit". Without this marker the driver
        reported "Stop square and exact queue placeholder were not verified",
        which names a UI failure and hides the exhausted account behind it."""
        surface = dispatch.Dispatch.__new__(dispatch.Dispatch)
        surface.read_lines = lambda step, frame, region: [
            "Today's hours are used up: an hour of DeepSeek V4.1 Flash Slow uses 1 hour,",
            "and you have less than an hour left. Your daily hours refill at 12:00 AM HST.",
        ]
        self.assertIn("daily hours exhausted",
                      surface.platform_refusal_notice("probe", None))

    def test_oversight_and_lane_continuation_banners_parse_as_restarts(self):
        """Gap 3 of audit 7149949800: 7143702385 leads with "OVERSIGHT RESTART
        DISPATCH" and 7124370203 with "LANE CONTINUATION WATCH", and both were
        unreadable while the census claimed zero unclaimed dispatches."""
        now = datetime(2026, 11, 24, 23, 0, tzinfo=timezone.utc)
        bodies = [
            ("OVERSIGHT RESTART DISPATCH — Lane 1, episode L1-STOP-1010\n"
             'Action for the runner: restart with "continue in full".\n'),
            ("LANE CONTINUATION WATCH RESTART DISPATCH — Lane 1\n"
             'Runner action requested: "continue in full"\n'),
        ]
        for index, body in enumerate(bodies):
            comment = {"id": 991000 + index, "user": {"id": watch.OWNER_ID},
                       "created_at": "2026-11-24T22:30:00Z", "body": body}
            parsed = watch.parse_dynamic_dispatch(comment, now=now)
            self.assertIsNotNone(parsed, body.splitlines()[0])
            self.assertEqual(parsed["kind"], "restart")
            self.assertEqual(parsed["thread"], watch.THREAD)

    def test_the_runner_colon_instruction_line_parses(self):
        """Measured 2026-11-25T04:30Z: 7151203687 writes "Runner: in-place
        restart only - exactly \"continue in full\"", and the dispatch that was
        filed to bring Lane 1 back was unreadable by the watch meant to run it."""
        now = datetime(2026, 11, 25, 3, 0, tzinfo=timezone.utc)
        comment = {
            "id": 7151203687, "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-25T02:48:02Z",
            "body": ("RESTART DISPATCH - Lane 1, episode L1-STOP-1035\n\n"
                     "Lane 1 is PRESUMED STOPPED.\n\n"
                     'Runner: in-place restart only - exactly "continue in full"; never a duplicate session.\n'),
        }
        parsed = watch.parse_dynamic_dispatch(comment, now=now)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["thread"], watch.THREAD)

    def test_a_steer_dispatch_is_named_as_unclaimable_not_silently_ignored(self):
        """7149636711 is a STEER: it carries no instruction line, so the watch
        must report it by name rather than let the heartbeat call the queue empty."""
        now = datetime(2026, 11, 24, 23, 0, tzinfo=timezone.utc)
        comment = {"id": 990031, "user": {"id": watch.OWNER_ID},
                   "created_at": "2026-11-24T22:30:00Z",
                   "body": ("STEER DISPATCH - Lane 1\n"
                            "Text for the runner to send into Lane 1's session, verbatim: fix the driver.\n")}
        with patch.object(watch, "api", return_value=[comment]), \
             patch.object(watch, "advance_cursor", Mock()):
            _, evidence = watch.scan_dispatch_comments(now=now)
        self.assertIn(990031, evidence["unparsed"])
        unclaimed = {}
        with patch.dict("os.environ", {"LOCALAPPDATA": tempfile.gettempdir()}), \
             patch.object(watch, "api", return_value=[comment]), \
             patch.object(watch, "advance_cursor", Mock()), \
             patch.object(watch, "execute", Mock()) as execute:
            self.assertFalse(watch.poll_dynamic_dispatches(set(), now=now, unclaimed=unclaimed))
        execute.assert_not_called()
        self.assertEqual(unclaimed, {990031: "banner-names-no-restart"})

    def test_the_cursor_watermark_is_create_only_and_only_moves_forward(self):
        """The ledger refuses a rewrite of an existing path (HTTP 422 "sha
        wasn't supplied", measured 2026-11-25T04:27Z on the first live paused
        tick), so the watermark is a new file per position, written once."""
        written = Mock()
        evidence = {"scanned_through": 7152505813, "scanned": 120}
        with patch.object(watch, "checkpoint", written):
            watch.advance_cursor(evidence, known={"cursor-7152000000.json"})
        self.assertTrue(evidence["cursor_advanced"])
        self.assertEqual(written.call_args.args[0], "cursor-7152505813.json")
        written.reset_mock()
        again = {"scanned_through": 7152505813, "scanned": 120}
        with patch.object(watch, "checkpoint", written):
            watch.advance_cursor(again, known={"cursor-7152505813.json"})
        self.assertFalse(again["cursor_advanced"])
        written.assert_not_called()

    def test_the_canary_names_a_blind_scan_instead_of_reporting_an_empty_queue(self):
        self.assertEqual(watch.canary({"owner": 0, "scanned_through": 0}),
                         ["the scan returned no owner comments at all",
                          "the scan advanced no cursor"])
        self.assertEqual(watch.canary({"owner": 3, "scanned_through": 7152505813}), [])

    def test_a_paused_watch_escalates_what_is_waiting_without_touching_a_desktop(self):
        """Pause permanence: three dispatches sat unclaimed from 01:28Z with no
        filing. A paused tick must say what it is holding, and run no input."""
        body = ("RESTART DISPATCH — SCMessenger, episode SCM-STOP-1542\n"
                'Action for the runner: "continue in full"\n')
        comment = {"id": 7149910847, "user": {"id": watch.OWNER_ID},
                   "created_at": datetime.now(timezone.utc).isoformat(), "body": body}
        posted = Mock()
        with patch.object(watch, "api", return_value=[comment]), \
             patch.object(watch, "advance_cursor", Mock()), \
             patch.object(watch, "checkpoints", return_value=set()), \
             patch.object(watch, "checkpoint", Mock()) as written, \
             patch.object(watch, "issue_comment", posted), \
             patch.object(watch, "execute", Mock()) as execute:
            self.assertTrue(watch.report_paused({"enabled": True, "paused": True,
                                                 "cancelled_lanes": ()}))
        execute.assert_not_called()
        self.assertEqual(written.call_args.args[0][:19], "paused-escalation-2")
        self.assertIn("PAUSED at the control surface", posted.call_args.args[0])
        self.assertIn("#7149910847", posted.call_args.args[0])

    def test_a_second_paused_tick_in_the_same_hour_does_not_repeat_the_escalation(self):
        body = ("RESTART DISPATCH — SCMessenger, episode SCM-STOP-1542\n"
                'Action for the runner: "continue in full"\n')
        comment = {"id": 7149910847, "user": {"id": watch.OWNER_ID},
                   "created_at": datetime.now(timezone.utc).isoformat(), "body": body}
        bucket = watch.datetime.now(timezone.utc).strftime("%Y%m%d-%H")
        digest = watch.hashlib.sha256(b"7149910847").hexdigest()[:8]
        posted = Mock()
        with patch.object(watch, "api", return_value=[comment]), \
             patch.object(watch, "advance_cursor", Mock()), \
             patch.object(watch, "checkpoints",
                          return_value={f"paused-escalation-{bucket}-{digest}.json"}), \
             patch.object(watch, "checkpoint", Mock()), \
             patch.object(watch, "issue_comment", posted):
            self.assertFalse(watch.report_paused({"enabled": True, "paused": True,
                                                  "cancelled_lanes": ()}))
        posted.assert_not_called()

    def test_local_control_state_accepts_utf8_bom_control_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctl = Path(tmp) / "control.json"
            ctl.write_bytes(b'\xef\xbb\xbf{"enabled": true, "paused": false}\n')
            with patch.dict("os.environ", {"HARNESS_DRIVER_CONTROL_FILE": str(ctl)}):
                state = watch.local_control_state()
            self.assertTrue(state["enabled"])
            self.assertFalse(state["paused"])


class SelfRelianceAndComposerCureTests(unittest.TestCase):
    """#684 7151843755 + 7153690483 + 7154645137 cures."""

    @staticmethod
    def _rgb_crop(rects, width=920, height=192):
        buf = bytearray(width * height * 3)
        for x0, y0, x1, y1, val in rects:
            for y in range(y0, y1):
                row = y * width * 3
                for x in range(x0, x1):
                    off = row + x * 3
                    buf[off] = val
                    buf[off + 1] = val
                    buf[off + 2] = val
        return bytes(buf)

    def test_composer_unchanged_tolerates_only_1x25_caret_not_glyphs_or_toolbar(self):
        base = self._rgb_crop([])
        caret_1x25 = self._rgb_crop([(157, 55, 158, 80, 240)])
        caret_2x25 = self._rgb_crop([(157, 55, 159, 80, 240)])
        glyph_16px = self._rgb_crop([(157, 59, 159, 75, 240)])  # 'l'/'i' 16px height
        dot_3x3 = self._rgb_crop([(157, 70, 160, 73, 240)])
        suggestion_wide = self._rgb_crop([(157, 55, 240, 80, 140)])
        toolbar_delta = self._rgb_crop([(157, 150, 158, 175, 240)])
        self.assertTrue(dispatch.composer_unchanged(base, base))
        self.assertTrue(dispatch.composer_unchanged(base, caret_1x25))
        self.assertTrue(dispatch.composer_unchanged(caret_1x25, base))
        self.assertTrue(dispatch.composer_unchanged(base, caret_2x25))
        self.assertFalse(dispatch.composer_unchanged(base, glyph_16px))
        self.assertFalse(dispatch.composer_unchanged(base, dot_3x3))
        self.assertFalse(dispatch.composer_unchanged(base, suggestion_wide))
        self.assertFalse(dispatch.composer_unchanged(base, toolbar_delta))

    def test_prior_send_refused_before_input_releases_pre_click_refusals_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = object.__new__(Dispatch)
            d.output = Path(tmp)
            trace = d.output / "driver.jsonl"
            trace.write_text(
                json.dumps({"kind": "action", "step_id": "send-once", "ok": False,
                            "detail": "send-once: executor failed: the standing composer changed after approval"})
                + "\n",
                encoding="utf-8",
            )
            self.assertTrue(d.prior_send_refused_before_input())
            trace.write_text(
                json.dumps({"kind": "action", "step_id": "send-once", "ok": True, "detail": "ok"}) + "\n",
                encoding="utf-8",
            )
            self.assertFalse(d.prior_send_refused_before_input())

    def test_parse_dynamic_dispatch_handles_7154645137_markdown_reroute(self):
        now = datetime(2026, 11, 25, 6, 30, tzinfo=timezone.utc)
        body = (
            "## RESTART DISPATCH — Lane 1 — Episode L1-STOP-1045 — Clause 7(c) FIRST RE-ROUTE\n\n"
            "**From:** harness-codex-lane-oversight tick 1049\n"
            "**Lane:** Lane 1 (combined prepare+gate+land lane).\n"
            "**Episode:** L1-STOP-1045 (OPEN).\n"
            '**Action requested:** in-place restart only — exactly "continue in full".\n'
        )
        comment = {"id": 7154645137, "user": {"id": watch.OWNER_ID},
                   "created_at": "2026-11-25T06:17:50Z", "body": body}
        parsed = watch.parse_dynamic_dispatch(comment, now=now)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["kind"], "restart")
        self.assertEqual(parsed["thread"], watch.THREAD)
        self.assertTrue(watch.episode_closed(
            [comment, {"id": 7154699999, "user": {"id": watch.OWNER_ID},
                        "body": "CANCELLATION — episode L1-STOP-1045"}],
            comment, parsed,
        ))
        self.assertTrue(watch.episode_closed(
            [comment, {
                "id": 7154907371,
                "user": {"id": watch.OWNER_ID},
                "body": (
                    "OVERSIGHT CANCELLATION — episode L1-STOP-1045, "
                    "Lane 1 restart dispatch 7154645137 (re-route 1, routed tick 1049) "
                    "is CANCELLED before any runner verdict."
                ),
            }],
            comment, parsed,
        ))

    def test_mode_e_reopens_scm_session_in_prepare_but_never_in_send(self):
        d = object.__new__(Dispatch)
        d.standing = True
        d.thread = dispatch.SCM_THREAD
        d.project = "SCMessenger"
        d.label = "SCMessenger"
        d.allow_navigation = True
        d.routes = Mock(return_value=[])
        d.selected_exact_session = Mock(side_effect=[False, True])
        d.navigate_by_session_list = Mock(return_value=True)
        d.identity_by_continuation = Mock(return_value=False)
        d.audit = Mock()
        d.phase = "prepare"
        d.verify_session_identity()
        d.navigate_by_session_list.assert_called_once()

        d2 = object.__new__(Dispatch)
        d2.standing = True
        d2.thread = dispatch.SCM_THREAD
        d2.project = "SCMessenger"
        d2.label = "SCMessenger"
        d2.allow_navigation = True
        d2.routes = Mock(return_value=[])
        d2.selected_exact_session = Mock(return_value=False)
        d2.navigate_by_session_list = Mock(return_value=True)
        d2.identity_by_continuation = Mock(return_value=False)
        d2.audit = Mock()
        d2.phase = "send"
        with self.assertRaisesRegex(RuntimeError, "exact pinned session route"):
            d2.verify_session_identity()
        d2.navigate_by_session_list.assert_not_called()

        d3 = object.__new__(Dispatch)
        d3.text = "continue in full"
        d3.phase = "prepare"
        d3.recovering = False
        d3.saw_text = Mock(return_value=False)
        d3.frame = Mock(side_effect=["retry_frame", "recovered_frame"])
        d3.verify_lane = Mock()
        d3.verify_tier = Mock(return_value="paid")
        d3.reloaded = Mock(return_value=True)
        d3.reestablish_if_reloaded = Mock(return_value=True)
        self.assertEqual(d3.verify_draft("initial_frame"), "recovered_frame")
        d3.reestablish_if_reloaded.assert_called_once_with("draft-verify")

    def test_mode_c_and_r20_claim_fault_leaves_cursor_unadvanced_and_alerts_once(self):
        receipts = {watch.BURN_QUEUE: {"created_at": "2026-11-24T00:00:00+00:00", "body": "b"}}
        posted = Mock()
        write = Mock()
        known = {"cursor-100.json"}

        def flaky_api(url, **_kwargs):
            if "page=2" in url:
                raise RuntimeError("HTTP 403 rate limit exceeded")
            return [{"id": 200 + i, "user": {"id": watch.OWNER_ID}, "body": "ok"} for i in range(100)]

        with patch.object(watch, "api", side_effect=flaky_api), \
             patch.object(watch, "checkpoint", write), \
             patch.object(watch, "issue_comment", posted):
            watch.run_burn(receipts, known)
        written_names = [call.args[0] for call in write.call_args_list]
        self.assertFalse(any(name.startswith("cursor-") for name in written_names))
        self.assertEqual(len(written_names), 1)
        self.assertTrue(written_names[0].startswith("canary-fault-"))
        self.assertIn("canary FAILED: claim-loop fault", posted.call_args.args[0])
        # Rate-limited: a second failure with the same signature in the same hour does not repost.
        with patch.object(watch, "api", side_effect=flaky_api), \
             patch.object(watch, "checkpoint", Mock()), \
             patch.object(watch, "issue_comment", posted):
            watch.run_burn(receipts, known)
        self.assertEqual(posted.call_count, 1)

    def test_mode_d_foreground_blocker_keeps_claim_unspent_and_retries_when_clear(self):
        now = datetime(2026, 11, 25, 6, 30, tzinfo=timezone.utc)
        comment = {
            "id": 995501,
            "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-25T06:20:00Z",
            "body": "RESTART DISPATCH\nLane: Lane 1\nAction for the runner: \"continue in full\"",
        }
        known = set()
        write = Mock(side_effect=lambda name, _data: known.add(name))
        posted = Mock()
        execute = Mock(return_value=0)
        with tempfile.TemporaryDirectory() as tmp:
            home = pinned_home(tmp, watch.SESSIONS[watch.THREAD][0])
            runtime_env = {"LOCALAPPDATA": tmp, "HARNESS_DRIVER_RUNTIME_ROOT": str(home)}
            with patch.dict("os.environ", runtime_env), \
                 patch.object(watch, "api", return_value=[comment]), \
                 patch.object(watch, "guard_approval", Mock()), \
                 patch.object(watch, "desktop_idle", lambda: True), \
                 patch.object(watch, "foreground_blocker", return_value=(1049510, 12304, "Windows Security")), \
                 patch.object(watch, "checkpoint", write), \
                 patch.object(watch, "issue_comment", posted), \
                 patch.object(watch, "advance_cursor", Mock()), \
                 runtime_present(), \
                 patch.object(watch, "execute", execute):
                self.assertTrue(watch.poll_dynamic_dispatches(known, now=now))
            execute.assert_not_called()
            self.assertFalse(any(n.startswith("claim-dyn-") for n in known))
            self.assertTrue(any(n.startswith("foreground-blocked-") for n in known))
            self.assertIn("Windows Security", posted.call_args.args[0])
            with patch.dict("os.environ", runtime_env), \
                 patch.object(watch, "api", return_value=[comment]), \
                 patch.object(watch, "guard_approval", Mock()), \
                 patch.object(watch, "desktop_idle", lambda: True), \
                 patch.object(watch, "foreground_blocker", return_value=None), \
                 patch.object(watch, "checkpoint", write), \
                 patch.object(watch, "issue_comment", posted), \
                 patch.object(watch, "advance_cursor", Mock()), \
                 runtime_present(), \
                 patch.object(watch, "execute", execute):
                self.assertTrue(watch.poll_dynamic_dispatches(known, now=now))
            execute.assert_called_once()
            self.assertIn("claim-dyn-995501-315608d2.json", known)

    def test_foreground_blocker_and_edge_paths_hermetic(self):
        self.assertTrue(dispatch.composer_unchanged(None, None))
        self.assertFalse(dispatch.composer_unchanged(b"short", b"other"))
        with patch.object(watch.os, "name", "posix"):
            self.assertIsNone(watch.foreground_blocker())
        known = set()
        with patch.object(watch, "checkpoint", Mock()) as cp, patch.object(watch, "issue_comment", Mock()) as ic:
            self.assertTrue(watch.report_foreground_blocked(known, 1, "t", (10, 20, "Windows Security")))
            self.assertFalse(watch.report_foreground_blocked(known, 1, "t", (10, 20, "Windows Security")))
            self.assertEqual(cp.call_count, 1)
            self.assertEqual(ic.call_count, 1)

        # Also prove real SendExecutor.send() + send_draft()-style caret-only frame change succeeds on object.__new__(Dispatch)
        base_img = Image.new("RGB", (920, 192))
        if hasattr(base_img, "paste") and hasattr(base_img, "resize"):
            # PIL present (Py3.14): verify Image objects directly as well
            caret_img = base_img.copy()
            for y in range(55, 80):
                caret_img.putpixel((157, y), (240, 240, 240))
            self.assertTrue(dispatch.composer_unchanged(base_img, caret_img))

        d = object.__new__(dispatch.Dispatch)
        d.standing = True
        d.thread = dispatch.SCM_THREAD
        d.text = dispatch.CONTINUATION
        d.send_deadline = float("inf")
        d.send_composer = self._rgb_crop([])
        d.verify_active_session = Mock()
        d.turn_running = Mock(return_value=False)
        d.click = Mock()
        caret_frame = Mock()
        caret_frame.crop = Mock(return_value=self._rgb_crop([(157, 55, 158, 80, 240)]))
        d.frame = Mock(return_value=caret_frame)
        d.send(dispatch.SEND, {"thread": dispatch.SCM_THREAD, "text": dispatch.CONTINUATION})
        d.click.assert_called_once()

    def test_utf8_bom_prefixed_dispatch_cancellation_and_pause_are_parsed(self):
        now = datetime(2026, 11, 25, 7, 0, tzinfo=timezone.utc)
        comment = {
            "id": 7155240387,
            "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-25T06:52:00Z",
            "body": (
                "\ufeff## RESTART DISPATCH — SCMessenger — Episode SCM-STOP-1912 — Clause 7(c) FIRST RE-ROUTE\n\n"
                "**Lane:** SCMessenger (`2ae32937`).\n"
                "**Episode:** SCM-STOP-1912 (RE-ROUTE 1).\n"
                '**Action requested:** in-place restart only — exactly "continue in full".\n'
            ),
        }
        parsed = watch.parse_dynamic_dispatch(comment, now=now)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["kind"], "restart")
        self.assertEqual(parsed["thread"], dispatch.SCM_THREAD)
        self.assertEqual(parsed["text"], dispatch.CONTINUATION)

        cancel_bom = {
            "id": 7155240999,
            "user": {"id": watch.OWNER_ID},
            "body": "\ufeffOVERSIGHT CANCELLATION — episode SCM-STOP-1912 cancelled.",
        }
        self.assertTrue(watch.episode_closed([comment, cancel_bom], comment, parsed))

        with patch.object(watch, "api", return_value=[{"id": 7155999000, "user": {"id": watch.OWNER_ID}, "body": "\ufeffPAUSE"}]):
            self.assertEqual(watch.pause_requested(), 7155999000)

        with patch.object(runner, "api", side_effect=RuntimeError("unexpected blob read")):
            self.assertIsNone(runner.approved({"id": 1, "user": {"id": watch.OWNER_ID}, "body": "\ufeffother"}, now))
            with self.assertRaisesRegex(RuntimeError, "unexpected blob read"):
                runner.approved({
                    "id": 2,
                    "user": {"id": watch.OWNER_ID},
                    "body": "\ufeffVISION-DISPATCH dispatch/laptop-driver/inbox/a.json " + ("a" * 40),
                }, now)


class _ArrowCrop:
    def __init__(self, size, pixels_bytes=b"same"):
        self.size = size
        self._bytes = pixels_bytes

    def convert(self, _mode):
        return self

    def point(self, _fn):
        return self

    def getbbox(self):
        return (10, 10, 42, 42)

    def tobytes(self):
        return self._bytes


class _ArrowFrame:
    def __init__(self, size=(1800, 1131)):
        self.size = size

    def crop(self, _region):
        return _ArrowCrop(self.size)


class MonitorDrainAndStagedCarrierTests(unittest.TestCase):
    """Ask 2 incremental ETag 304 polling, back-to-back drain, 3-timestamp SLA, and staged carriers."""

    def test_sync_issue_comments_uses_since_watermark_and_etag_304_zero_quota(self):
        comments_payload = [
            {
                "id": 7158410813,
                "user": {"id": watch.OWNER_ID},
                "created_at": "2026-11-25T09:29:53Z",
                "updated_at": "2026-11-25T09:29:53Z",
                "body": "later",
            },
            {
                "id": 7158410915,
                "user": {"id": watch.OWNER_ID},
                "created_at": "2026-11-25T09:29:53Z",
                "updated_at": "2026-11-25T09:29:53Z",
                "body": "PAUSE",
            },
        ]
        seen = []

        def fake_conditional(endpoint, etag=None):
            seen.append((endpoint, etag))
            if len(seen) == 1:
                return comments_payload, None
            if len(seen) == 2:
                return comments_payload, '"etag-1"'
            return watch._NOT_MODIFIED, etag

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "monitor.json"
            old_stats = dict(watch._POLL_STATS)
            watch._POLL_STATS["requests"] = 0
            watch._POLL_STATS["conditional_304s"] = 0
            try:
                with patch.dict("os.environ", {"HARNESS_DRIVER_MONITOR_STATE": str(state_path)}), \
                        patch.object(watch, "_http_get_conditional", side_effect=fake_conditional):
                    first = watch._sync_issue_comments(since_floor="2026-11-24T00:20:00Z")
                    self.assertEqual([item["id"] for item in first], [7158410813, 7158410915])
                    # Same-second watermark keeps 09:29:53Z and sets ETag on the next poll.
                    second = watch._sync_issue_comments(since_floor="2026-11-24T00:20:00Z")
                    self.assertEqual(len(second), 2)
                    self.assertIn("since=2026-11-25T09:29:53Z", seen[1][0])
                    # Third poll hits HTTP 304 Not Modified without changing cache.
                    third = watch._sync_issue_comments(since_floor="2026-11-24T00:20:00Z")
                    self.assertEqual(len(third), 2)
                    self.assertEqual(seen[2][1], '"etag-1"')
                    self.assertEqual(watch._POLL_STATS["requests"], 3)
                    self.assertEqual(watch._POLL_STATS["conditional_304s"], 1)
                    # pause_requested reuses the 304 cache without issuing non-conditional calls.
                    self.assertEqual(watch.pause_requested(), 7158410915)
                    self.assertEqual(watch._POLL_STATS["conditional_304s"], 2)
                    with patch.object(watch, "api", return_value={"id": 999}):
                        watch.issue_comment("test invalidates etag")
                    saved = json.loads(state_path.read_text(encoding="utf-8"))
                    self.assertIsNone(saved["comments_etag"])
                    self.assertEqual(saved["comments_watermark"], "2026-11-25T09:29:53Z")
            finally:
                watch._POLL_STATS.clear()
                watch._POLL_STATS.update(old_stats)

    def test_validate_receipts_uses_monitor_state_cache_after_cold_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "monitor.json"
            api_calls = []

            def fake_api(endpoint):
                api_calls.append(endpoint)
                num = int(endpoint.rsplit("/", 1)[1])
                return {
                    "id": num,
                    "user": {"id": watch.OWNER_ID},
                    "created_at": "2026-11-23T06:55:00Z",
                    "body": watch.RECEIPTS[num],
                    "issue_url": "https://api.github.com/repos/Treystu/harness/issues/684",
                }

            with patch.dict("os.environ", {"HARNESS_DRIVER_MONITOR_STATE": str(state_path)}), \
                    patch.object(watch, "api", side_effect=fake_api):
                first = watch.validate_receipts()
                self.assertEqual(len(first), len(watch.RECEIPTS))
                self.assertEqual(len(api_calls), len(watch.RECEIPTS))
                second = watch.validate_receipts()
                self.assertEqual(set(second), set(watch.RECEIPTS))
                self.assertEqual(len(api_calls), len(watch.RECEIPTS))

    def test_parse_live_dispatches_bigenergyco_agensi_lane1_and_burn_window(self):
        now = datetime(2026, 11, 25, 11, 30, tzinfo=timezone.utc)
        bec = {
            "id": 7158410813,
            "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-25T09:29:53Z",
            "body": (
                "## RESTART DISPATCH \u2014 BigEnergyCo, episode BURN-20261124-BEC\n\n"
                "Runner action requested: in-place restart of BigEnergyCo only. "
                "The lane sits staged with its /mission carrier + Start showing after turn 15. "
                "Resume -> Start on the staged carrier.\n"
            ),
        }
        agensi = {
            "id": 7158410915,
            "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-25T09:29:53Z",
            "body": (
                "## RESTART DISPATCH \u2014 Agensi, episode BURN-20261124-AGENSI\n\n"
                "Runner action requested: in-place restart of Agensi only "
                "(Agensi Skills Local, session 26646448, 'Agensi Lane Queue Executi'). "
                "Resume -> Start on the staged carrier.\n"
            ),
        }
        lane1 = {
            "id": 7159142905,
            "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-25T10:02:32Z",
            "body": (
                "OVERSIGHT RESTART DISPATCH \u2014 Lane 1 \u2014 Episode L1-STOP-1064\n\n"
                "Action for the runner alone: in-place restart only \u2014 "
                'exactly "continue in full"; never a duplicate session.\n'
            ),
        }
        burn = {
            "id": 7159999001,
            "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-25T10:15:00Z",
            "body": (
                "BURN WINDOW DISPATCH \u2014 SCMessenger Audit\n"
                'Action for the runner: "continue in full"\n'
            ),
        }
        p_bec = watch.parse_dynamic_dispatch(bec, now=now)
        p_ag = watch.parse_dynamic_dispatch(agensi, now=now)
        p_l1 = watch.parse_dynamic_dispatch(lane1, now=now)
        p_burn = watch.parse_dynamic_dispatch(burn, now=now)
        self.assertEqual((p_bec["thread"], p_bec["mode"]), ("0d7e2f37", "staged-resume"))
        self.assertEqual((p_ag["thread"], p_ag["mode"]), ("26646448", "staged-resume"))
        self.assertEqual((p_l1["thread"], p_l1["mode"]), (watch.THREAD, "continuation"))
        self.assertEqual((p_burn["thread"], p_burn["mode"]), ("0319b9f6", "continuation"))

    def test_run_burn_drains_multiple_dispatches_back_to_back_without_idle_gap(self):
        comments = [
            {
                "id": 7158410813,
                "user": {"id": watch.OWNER_ID},
                "created_at": recent_stamp(20),
                "body": "## RESTART DISPATCH \u2014 BigEnergyCo\nRunner action requested: Resume -> Start on the staged carrier.",
            },
            {
                "id": 7159142905,
                "user": {"id": watch.OWNER_ID},
                "created_at": recent_stamp(5),
                "body": 'OVERSIGHT RESTART DISPATCH \u2014 Lane 1\nAction for the runner alone: "continue in full"',
            },
        ]
        executed = []

        def fake_execute(out, item, mission, digest, bystanders):
            executed.append((item, mission["thread"], mission.get("phases"), mission["phase_timeout"], mission["filed_at"]))
            return 0

        receipts = {watch.BURN_QUEUE: {"created_at": "2026-11-24T00:00:00+00:00", "body": "queue"}}
        known = set()
        posted = []
        with tempfile.TemporaryDirectory() as tmp:
            home = pinned_home(tmp, *(watch.SESSIONS[t][0] for t in ("0d7e2f37", watch.THREAD)))
            with patch.dict("os.environ", {"LOCALAPPDATA": tmp,
                                           "HARNESS_DRIVER_RUNTIME_ROOT": str(home)}), \
                    patch.object(watch, "api", return_value=comments), \
                    patch.object(watch, "guard_approval", Mock()), \
                    patch.object(watch, "desktop_idle", lambda: True), \
                    patch.object(watch, "foreground_blocker", return_value=None), \
                    patch.object(watch, "checkpoint", Mock()), \
                    patch.object(watch, "issue_comment", side_effect=posted.append), \
                    patch.object(watch, "advance_cursor", Mock()), \
                    runtime_present(), \
                    patch.object(watch, "execute", side_effect=fake_execute):
                watch.run_burn(receipts, known)
        self.assertEqual(len(executed), 2)
        self.assertEqual(executed[0][1], "0d7e2f37")
        self.assertEqual(executed[0][2], ("search", "query", "select", "vision-resume"))
        self.assertEqual(executed[0][3], 480)
        self.assertEqual(executed[1][1], watch.THREAD)
        self.assertIsNone(executed[1][2])
        # Each claim acks before its input and files its result, and the two
        # dispatches drain with nothing between them (pickup discipline: ack on
        # claim, no idle gap, three stamps per verdict).
        self.assertEqual(len(posted), 4)
        self.assertIn("ack #7158410813", posted[0])
        self.assertIn("result #7158410813", posted[1])
        self.assertIn("ack #7159142905", posted[2])
        self.assertIn("result #7159142905", posted[3])
        for verdict in (posted[1], posted[3]):
            self.assertIn(", claimed ", verdict)
            self.assertIn(", completed ", verdict)

    def test_claimable_excludes_claimed_and_alerts_stale_pickup_over_300s(self):
        now = datetime(2026, 11, 25, 11, 30, tzinfo=timezone.utc)
        comments = [
            {
                "id": 7158000001,
                "user": {"id": watch.OWNER_ID},
                "created_at": "2026-11-25T09:00:00Z",
                "body": 'RESTART DISPATCH - SCMessenger\nAction for the runner: "continue in full"',
            },
            {
                "id": 7159142905,
                "user": {"id": watch.OWNER_ID},
                "created_at": "2026-11-25T10:02:32Z",
                "body": 'OVERSIGHT RESTART DISPATCH \u2014 Lane 1\nAction for the runner alone: "continue in full"',
            },
        ]
        known = {"claim-dyn-7158000001-2ae32937.json"}
        posted = []
        with tempfile.TemporaryDirectory() as tmp:
            home = pinned_home(tmp, *(watch.SESSIONS[t][0] for t in ("2ae32937", watch.THREAD)))
            with patch.dict("os.environ", {"LOCALAPPDATA": tmp,
                                           "HARNESS_DRIVER_RUNTIME_ROOT": str(home)}), \
                    patch.object(watch, "api", return_value=comments), \
                    patch.object(watch, "guard_approval", Mock()), \
                    patch.object(watch, "desktop_idle", lambda: False), \
                    patch.object(watch, "checkpoint", Mock()), \
                    patch.object(watch, "issue_comment", side_effect=posted.append), \
                    patch.object(watch, "advance_cursor", Mock()), \
                    runtime_present():
                result = watch.poll_dynamic_dispatches(known, now=now)
                self.assertEqual(result, "deferred")
                self.assertEqual(watch.LAST_SCAN["claimable"], 1)
                self.assertTrue(any("pickup SLA ALERT on #7159142905" in msg for msg in posted))
                before_count = sum(1 for msg in posted if "pickup SLA ALERT" in msg)
                watch.report_stale_pickup(known, 7159142905, watch.THREAD, 600, "waiting for owner desktop idle")
                after_count = sum(1 for msg in posted if "pickup SLA ALERT" in msg)
                self.assertEqual(before_count, after_count)

    def test_runner_execute_posts_three_timestamps_and_pickup_latency(self):
        comments_posted = []

        def fake_api(_endpoint, method="GET", body=None):
            if method == "POST":
                comments_posted.append(body["body"])
                return {"id": len(comments_posted), "html_url": "https://example.test/c"}
            return {"id": 7158410813, "user": {"id": runner.OWNER_ID}, "body": "## RESTART DISPATCH"}

        fake_win = Mock()
        fake_win.handle = 123
        fake_win.api.foreground.return_value = 999
        fake_win.api.title_of.return_value = "Editor"
        fake_win.pid.return_value = 456
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "dyn-7158410813-0d7e2f37"
            out.mkdir()
            with patch.object(runner, "api", side_effect=fake_api), \
                    patch.object(runner, "FreeBuffWindow", return_value=fake_win), \
                    patch.object(runner, "capture_set", return_value={}), \
                    patch.object(runner, "observe_bystander", return_value=runner.BYSTANDER_IDLE), \
                    patch.object(runner, "run_phases", return_value=True), \
                    patch.object(runner, "activate_exact", return_value=True), \
                    patch.object(runner, "publish", return_value=["https://example.test/e"]):
                rc = runner.execute(out, "dyn-7158410813-0d7e2f37", {
                    "thread": "0d7e2f37",
                    "dispatch": 7158410813,
                    "standing": True,
                    "filed_at": "2026-11-25T09:29:53Z",
                }, "abc", ())
        self.assertEqual(rc, 0)
        self.assertIn("filed 2026-11-25T09:29:53Z, claimed ", comments_posted[0])
        self.assertIn("Timestamps: filed 2026-11-25T09:29:53Z, claimed ", comments_posted[1])
        self.assertIn(", completed ", comments_posted[1])
        self.assertIn("pickup ", comments_posted[1])

    def test_resume_vision_mission_staged_arrow_and_post_send_reveal_cure(self):
        with tempfile.TemporaryDirectory() as tmp:
            phase_dir = Path(tmp) / "vision-resume"
            phase_dir.mkdir()
            surface = _Surface(
                stops=[False, False, True, True],
                labels={"Resume mission": (900, 700)},
                missing="Start mission",
                reading="/mission Burn Queue",
            )
            surface.output = phase_dir
            surface.thread = "0d7e2f37"
            surface.label = "BigEnergyCo"
            surface.allow_navigation = True
            surface.post_send = False
            surface.frame = lambda _step: _ArrowFrame()
            surface.settle_view = lambda _step: _ArrowFrame()
            surface.choose = lambda *_args, **_kwargs: "resume"
            def _locate(step, _frame, label, _region, **kwargs):
                if label == "Start mission":
                    raise RuntimeError(f"{step}: exact OCR label {label!r} was not verified")
                pt = [900, 700]
                return (pt, (840, 685, 960, 715)) if kwargs.get("with_bounds") else pt
            surface.locate_exact_text = _locate
            surface._submit_staged_carrier_arrow = lambda f, s: Dispatch._submit_staged_carrier_arrow(surface, f, s)
            identity_calls = []
            surface.verify_session_identity = lambda: identity_calls.append(surface.post_send)
            with patch.object(dispatch.time, "sleep"), \
                    patch.object(dispatch, "composer_unchanged", return_value=True):
                Dispatch.resume_vision_mission(surface)
            self.assertEqual(surface.acts, ["BigEnergyCo Resume mission", "BigEnergyCo staged mission start arrow"])
            self.assertEqual(identity_calls, [False, False, False, True])
            self.assertTrue((phase_dir.parent / "harness-freebuff-0d7e2f37-staged-start-20261122.json").is_file())

            # Post-send SCM_THREAD identity check runs scroll-only reveal_lane_row(step="post-send-reveal-lane").
            scm = object.__new__(Dispatch)
            scm.thread = dispatch.SCM_THREAD
            scm.project = "SCMessenger"
            scm.label = "SCMessenger"
            scm.standing = True
            scm.phase = "send"
            scm.post_send = True
            scm.routes = lambda: []
            scm.audit = Mock()
            scm.reveal_lane_row = Mock()
            scm.selected_exact_session = Mock(side_effect=[False, True])
            with patch.dict(dispatch.PINNED_UUIDS, {dispatch.SCM_THREAD: "2ae32937-uuid"}):
                scm.verify_session_identity()
            scm.reveal_lane_row.assert_called_once_with(step="post-send-reveal-lane")
            self.assertEqual(scm.selected_exact_session.call_count, 2)

            # Non-SCM reveal_lane_row accepts session_candidates under project heading (BigEnergyCo).
            bec = object.__new__(Dispatch)
            bec.thread = "0d7e2f37"
            bec.label = "BigEnergyCo"
            bec.project = "BigEnergyCo"
            bec.audit = Mock()
            bec.scroll_sidebar_to_top = lambda: _ArrowFrame()
            bec.settled_roster = Mock(return_value=(
                _ArrowFrame(),
                [{"text": "B BigEnergyCo", "y": 200}, {"text": "BigEnergyCo Full Burne", "y": 230}],
            ))
            _, rows = bec.reveal_lane_row()
            self.assertEqual(rows[1]["text"], "BigEnergyCo Full Burne")


class LiveNavigationCureTests(unittest.TestCase):
    """Step 2.5 cures for BigEnergyCo/Agensi sidebar navigation, glyph dedup, modal order, and clipped query readback."""

    def test_bigenergyco_full_title_disambiguates_six_sidebar_rows(self):
        self.assertEqual(dispatch.SESSIONS["0d7e2f37"][0], "BigEnergyCo Full Burndown")
        rows = [
            {"text": "B BigEnergyCo", "y": 100},
            {"text": "BigEnergyCo Full BU", "y": 130},
            {"text": "BigEnergyCo Audit Lant V", "y": 160},
            {"text": "BigEnergyCo Overnight BU", "y": 190},
            {"text": "BigEnergyCo Laptop Workt", "y": 220},
            {"text": "BigEnergyCo Github Bloat", "y": 250},
            {"text": "BigEnergyCo Burndown Str", "y": 280},
        ]
        scoped, heading = Dispatch.session_candidates(rows, dispatch.SESSIONS["0d7e2f37"][0], "BigEnergyCo")
        self.assertEqual([r["text"] for r in scoped], ["BigEnergyCo Full BU"])
        self.assertEqual(heading["text"], "B BigEnergyCo")

    def test_walk_session_list_deduplicates_icon_glyph_rivals_and_click_row_matches(self):
        d = object.__new__(Dispatch)
        d.thread = "26646448"
        d.label = "Agensi Lane Queue Executi"
        d.project = "Agensi Skills Local"
        d.audit = Mock()
        d.scroll_sidebar_to_top = Mock(return_value=_ArrowFrame())
        page9 = [{"text": "B Agensi Skills Local", "y": 100}, {"text": "Ra Agensi Lane Queue E", "y": 130}]
        page10 = [{"text": "B Agensi Skills Local", "y": 100}, {"text": "Agensi Lane Queue E", "y": 130}]
        d.settled_roster = Mock(side_effect=[
            (_ArrowFrame(), page9),
            (_ArrowFrame(), page10),
            (_ArrowFrame(), page9),
        ])
        d.expand_sections = Mock(side_effect=lambda _p, frame, rows, _prefix: (frame, rows, False))
        d.advance_sidebar = Mock(side_effect=[(_ArrowFrame(), True), (_ArrowFrame(), False)])
        d.click_exact_row = Mock()
        with patch.object(dispatch.time, "sleep"):
            ok = d.walk_session_list(pages=5)
        self.assertTrue(ok)
        d.click_exact_row.assert_called_once()
        self.assertEqual(d.click_exact_row.call_args.args[2]["text"], "Ra Agensi Lane Queue E")

    def test_identify_by_route_closes_search_before_scrolling_to_top(self):
        order = []
        d = object.__new__(Dispatch)
        d.thread = "26646448"
        d.label = "Agensi Lane Queue Executi"
        d.project = "Agensi Skills Local"
        d.audit = Mock()
        d.frame = lambda step: _ArrowFrame()
        d.ensure_search_closed = lambda frame: order.append("close") or frame
        d.scroll_sidebar_to_top = lambda steps=25: order.append(("top", steps)) or _ArrowFrame()
        d.settled_roster = Mock(return_value=(_ArrowFrame(), []))
        d.scroll_by = Mock(return_value=False)
        self.assertFalse(d.identify_by_route())
        self.assertEqual(order[0], "close")
        self.assertEqual(order[1], ("top", 25))

    def test_query_search_field_accepts_clipped_agensi_readback_but_rejects_foreign(self):
        d = object.__new__(Dispatch)
        d.thread = "26646448"
        d.label = "Agensi Lane Queue Executi"
        d.audit = Mock()
        d.locate_exact_text = Mock(return_value=[700, 200])
        d.act = Mock()
        d.frame = lambda _step: _ArrowFrame()
        d.read_lines = Mock(return_value=["Agensi Lane Queue E)"])
        with patch.object(dispatch.time, "sleep"):
            res = d.query_search_field(_ArrowFrame())
        self.assertIsNotNone(res)

        d.read_lines = Mock(return_value=["Continue the SCMessenger queue please"])
        with patch.object(dispatch.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "not typing over it"):
                d.query_search_field(_ArrowFrame(), attempts=1)


class Step3OvernightAndStandingTests(unittest.TestCase):
    """Step 3 fixes: 7176494509 L1-STOP routing, ghost Tab vs foreign Send-only, HTTP backoff, standing rule, #703."""

    def test_7176494509_l1_stop_header_and_subject_routes_to_lane1(self):
        comment = {
            "id": 7176494509,
            "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-25T22:32:40Z",
            "body": (
                "RESTART DISPATCH — episode L1-STOP-1112 (oversight tick 1112, 2026-11-25T22:31:22Z)\n\n"
                "Lane 1 is PRESUMED STOPPED (Clause 6 GitHub-first detection).\n"
                'Runner action requested: in-place restart only — exactly "continue in full".\n'
            ),
        }
        now = datetime(2026, 11, 26, 6, 0, tzinfo=timezone.utc)
        parsed = watch.parse_dynamic_dispatch(comment, now=now)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["kind"], "restart")
        self.assertEqual(parsed["thread"], dispatch.THREAD)

        # Even without an episode tag in the banner, the opening "<Lane> is PRESUMED STOPPED" line resolves.
        no_ep = {
            "id": 7176494599,
            "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-26T05:00:00Z",
            "body": (
                "RESTART DISPATCH — oversight check\n\n"
                "SCMessenger is PRESUMED STOPPED.\n"
                'Runner action requested: "continue in full".\n'
            ),
        }
        self.assertEqual(watch.parse_dynamic_dispatch(no_ep, now=now)["thread"], dispatch.SCM_THREAD)

    def test_runner_api_and_watch_http_retry_transient_github_outage(self):
        fail_eof = Mock(returncode=1, stdout="", stderr="unexpected end of JSON input\n")
        ok_resp = Mock(returncode=0, stdout='{"ok": true}', stderr="")
        with patch.object(runner.subprocess, "run", side_effect=[fail_eof, ok_resp]) as run_mock, \
             patch.object(runner.time, "sleep"):
            self.assertEqual(runner.api("repos/Treystu/harness/issues/295/comments"), {"ok": True})
        self.assertEqual(run_mock.call_count, 2)

        # Non-transient error (e.g. HTTP 422) does not spin retries.
        fail_422 = Mock(returncode=1, stdout="", stderr="gh: Invalid request (HTTP 422)")
        with patch.object(runner.subprocess, "run", return_value=fail_422) as run_mock, \
             patch.object(runner.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "HTTP 422"):
                runner.api("repos/Treystu/slow-lane-ledger/contents/x", method="PUT", body={"a": 1})
        self.assertEqual(run_mock.call_count, 1)

        # report_claim_fault tolerates secondary write failure during outage and frees fault name.
        known = set()
        with patch.object(watch, "checkpoint", side_effect=RuntimeError("unexpected end of JSON input")):
            self.assertFalse(watch.report_claim_fault(known, RuntimeError("boom")))
        self.assertEqual(known, set())

    def test_empty_autocomplete_tab_ghost_vs_real_foreign_staged_send_only(self):
        dim_img = Image.new("RGB", (1800, 1131), (40, 40, 40)) if hasattr(Image.new("RGB", (10, 10)), "paste") else None
        if dim_img is not None:
            self.assertFalse(dispatch.has_send_arrow_outline(dim_img))
            # Draw bright white 34x34 Send button in SEND_CONTROL (1480, 1043, 1535, 1100).
            bright_img = dim_img.copy()
            for x in range(1490, 1524):
                for y in range(1055, 1089):
                    bright_img.putpixel((x, y), (245, 245, 245))
            self.assertTrue(dispatch.has_send_arrow_outline(bright_img))

        # 1. Empty autocomplete ghost (no bright Send circle + '...tab' OCR) routes as 'empty' -> types continuation.
        d = object.__new__(Dispatch)
        d.recovering = False
        d.scoped_input = True
        d.standing = True
        d.thread = dispatch.SCM_THREAD
        d.label = "SCMessenger"
        d.text = dispatch.CONTINUATION
        d.audit = Mock()
        d.reestablish_if_reloaded = Mock(return_value=False)
        d.verify_lane = Mock()
        d.verify_tier = Mock(return_value="paid")
        d.turn_running = Mock(return_value=False)
        d.locate_exact_text = Mock(side_effect=[RuntimeError("no placeholder"), [670, 1020]])
        d.read_lines = Mock(side_effect=[
            [],  # composer-expired-banner
            [],  # composer-staged-mission
            ["packetsfortheheldandgateditems...tab"],  # composer-written
            ["Tab"],  # composer-tab-hint
        ])
        d.yes = Mock()
        d.act = Mock()
        d.verify_draft = Mock()
        no_arrow_frame = Mock(size=(1800, 1131))
        no_arrow_frame.crop = Mock(return_value=_ArrowCrop((55, 57)))
        # Ensure getbbox() returns None when simulating no white circle:
        no_arrow_crop = Mock()
        no_arrow_crop.convert.return_value = no_arrow_crop
        no_arrow_crop.point.return_value = no_arrow_crop
        no_arrow_crop.getbbox.return_value = None
        no_arrow_frame.crop = Mock(return_value=no_arrow_crop)
        d.settle_view = Mock(return_value=no_arrow_frame)
        d.frame = Mock(return_value=no_arrow_frame)
        with patch.object(dispatch.time, "sleep"):
            d.prepare_draft()
        self.assertEqual([c.args[0] for c in d.act.call_args_list], ["focus-verified-composer", "type-continuation"])

        # 2. Genuine foreign staged draft (bright white Send circle present + standing=True) -> Send-only, no typing.
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "prepare"
            out_dir.mkdir()
            d2 = object.__new__(Dispatch)
            d2.recovering = False
            d2.scoped_input = True
            d2.standing = True
            d2.thread = dispatch.THREAD
            d2.label = "Lane 1"
            d2.project = "Harness"
            d2.text = dispatch.CONTINUATION
            d2.output = out_dir
            d2.audit = Mock()
            d2.reestablish_if_reloaded = Mock(return_value=False)
            d2.verify_lane = Mock()
            d2.verify_tier = Mock(return_value="paid")
            d2.turn_running = Mock(return_value=False)
            d2.locate_exact_text = Mock(side_effect=RuntimeError("no placeholder"))
            d2.read_lines = Mock(side_effect=[[], [], ["Investigate P1 calibration draft in detail"]])
            d2.act = Mock()
            arrow_frame = _ArrowFrame()
            d2.settle_view = Mock(return_value=arrow_frame)
            d2.prepare_draft()
            d2.act.assert_not_called()
            marker = Path(tmp) / "foreign-staged-send-only.json"
            self.assertTrue(marker.is_file())

            # send_draft honors foreign-staged-send-only.json without demanding 'continue in full'.
            d2.output = Path(tmp) / "send"
            d2.output.mkdir()
            d2.phase = "send"
            d2.allow_navigation = True
            d2.post_send = False
            d2.routes = Mock(return_value=[f"freebuff://chat/{dispatch.THREAD}-full"])
            d2.require_foreground = Mock(return_value=1)
            d2.stop_visible = Mock(side_effect=[False, True])
            d2.locate_exact_text = Mock(return_value=[700, 980])
            d2.working_banner = Mock(return_value="3s")
            d2.reestablish_if_reloaded = Mock(return_value=False)
            d2.frame = Mock(return_value=arrow_frame)
            d2.read_lines = Mock(return_value=["Investigate P1 calibration draft in detail"])
            d2.yes = Mock()
            d2.act = Mock()
            with patch.object(dispatch.time, "sleep"):
                d2.send_draft()
            send_call = d2.act.call_args_list[-1]
            self.assertEqual(send_call.args[0], "send-once")
            self.assertIn("foreign staged draft preserved", send_call.args[2]["control"])

    def test_poll_dynamic_dispatches_routes_antigravity_when_calibrated(self):
        now = datetime(2026, 11, 26, 8, 0, tzinfo=timezone.utc)
        comment = {
            "id": 996001,
            "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-26T07:55:00Z",
            "body": 'RESTART DISPATCH\nTarget: antigravity\nAction for the runner: "continue in full"\n',
        }
        with tempfile.TemporaryDirectory() as tmp:
            write = Mock()
            posted = Mock()
            with patch.dict("os.environ", {"LOCALAPPDATA": tmp}), \
                 patch.object(watch, "api", return_value=[comment]), \
                 patch.object(watch, "guard_approval", Mock()), \
                 patch.object(watch, "antigravity_adapter_ready", return_value=True), \
                 patch.object(watch, "desktop_idle", lambda: True), \
                 patch.object(watch, "checkpoint", write), \
                 patch.object(watch, "issue_comment", posted), \
                 patch.object(watch, "advance_cursor", Mock()), \
                 runtime_present(), \
                 patch.object(watch, "_execute_antigravity", return_value="verified running (typed continuation)") as exec_ag:
                self.assertTrue(watch.poll_dynamic_dispatches(set(), now=now))
            exec_ag.assert_called_once()
            self.assertIn("antigravity", posted.call_args.args[0])
            self.assertEqual([c.args[0] for c in write.call_args_list],
                             ["claim-dyn-996001-antigravity.json", "result-dyn-996001-antigravity.json"])

    def test_poll_standing_burndown_restarts_respects_stillness_stop_and_logs_after(self):
        now = datetime(2026, 11, 26, 8, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "monitor.json"
            execute = Mock(return_value=0)
            cp = Mock()
            with patch.dict("os.environ", {"LOCALAPPDATA": tmp, "HARNESS_DRIVER_MONITOR_STATE": str(state_path)}), \
                 patch.object(watch, "pause_requested", return_value=None), \
                 patch.object(watch, "_sync_issue_comments", return_value=[]), \
                 patch.object(watch, "_standing_lane_still", return_value=True), \
                 patch.object(watch, "guard_approval", Mock()), \
                 patch.object(watch, "desktop_idle", lambda: True), \
                 patch.object(watch, "foreground_blocker", return_value=None), \
                 patch.object(watch, "checkpoint", cp), \
                 runtime_present(), \
                 patch.object(watch, "execute", execute):
                res = watch.poll_standing_burndown_restarts(
                    set(), control={"continuous_burndown": True, "watched_lanes": (dispatch.THREAD,), "from_file": True}, now=now,
                )
            self.assertTrue(res)
            self.assertTrue(execute.call_args.args[2]["skip_pre_ack"])
            # Cooldown recorded so an immediate follow-up tick does not re-fire.
            with patch.dict("os.environ", {"LOCALAPPDATA": tmp, "HARNESS_DRIVER_MONITOR_STATE": str(state_path)}), \
                 patch.object(watch, "pause_requested", return_value=None), \
                 patch.object(watch, "_sync_issue_comments", return_value=[]), \
                 patch.object(watch, "execute", execute):
                res2 = watch.poll_standing_burndown_restarts(
                    set(), control={"continuous_burndown": True, "watched_lanes": (dispatch.THREAD,), "from_file": True},
                    now=now + watch.timedelta(minutes=5),
                )
            self.assertFalse(res2)
            self.assertEqual(execute.call_count, 1)


NL = chr(10)
Q = chr(34)
S = chr(39)


class DispatchRefusalTests(unittest.TestCase):
    """A2: "present but not claimable" names its cause and stops repeating itself.

    Measured 2026-11-27: 85 ids filled every heartbeat's refusal list for three
    days - nearly all past the 24-hour claim bound - so the list could no longer
    be read as a queue. Among the four dispatches filed on 2026-11-26,
    7174526907 carries its instruction as "Requested runner action:", a shape the
    parser did not read at all.
    """

    def _comment(self, body, *, cid=7174526907, created="2026-11-25T21:02:24Z"):
        return {"id": cid, "user": {"id": watch.OWNER_ID}, "body": body,
                "created_at": created}

    def test_the_requested_runner_action_wording_is_read(self):
        comment = self._comment(
            "OVERSIGHT RESTART DISPATCH - Episode L1-STOP-1106" + NL + NL +
            "Lane 1 is PRESUMED STOPPED." + NL + NL +
            'Requested runner action: in-place restart only - exactly ' + Q +
            'continue in full' + Q + '; never a duplicate session, never ' +
            'model/settings changes.' + NL)
        parsed = watch.parse_dynamic_dispatch(
            comment, now=datetime(2026, 11, 25, 21, 30, tzinfo=timezone.utc))
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["thread"], watch.THREAD)
        self.assertEqual(parsed["mode"], "continuation")

    def test_a_dispatch_with_no_instruction_line_is_named_no_instruction(self):
        comment = self._comment(
            "DISPATCH - scale to two tandem working lanes" + NL + NL +
            'Lane 1' + S + 's continuation rides the L1-STOP-1112 restart '
            "already routed." + NL,
            cid=7183653129, created="2026-11-26T05:37:18Z")
        self.assertEqual(
            watch.refusal_reason(comment,
                                 now=datetime(2026, 11, 26, 6, 0, tzinfo=timezone.utc)),
            "no-instruction")

    def test_a_dispatch_past_the_claim_bound_is_named_stale(self):
        comment = self._comment(
            "RESTART DISPATCH - Lane 1, episode L1-STOP-1106" + NL + NL +
            'Requested runner action: in-place restart only - exactly ' + Q +
            'continue in full' + Q + '.' + NL)
        self.assertEqual(
            watch.refusal_reason(comment,
                                 now=datetime(2026, 11, 27, 10, 0, tzinfo=timezone.utc)),
            "stale-beyond-24h")

    def test_a_final_refusal_is_recorded_once_and_not_reported_twice(self):
        now = datetime(2026, 11, 27, 10, 0, tzinfo=timezone.utc)
        comment = self._comment(
            "RESTART DISPATCH - Lane 1, episode L1-STOP-1106" + NL + NL +
            'Requested runner action: in-place restart only - exactly ' + Q +
            'continue in full' + Q + '.' + NL)
        known = set()
        with patch.dict("os.environ", {"LOCALAPPDATA": tempfile.gettempdir()}):
            with patch.object(watch, "api", return_value=[comment]):
                with patch.object(watch, "advance_cursor", Mock()):
                    with patch.object(watch, "execute", Mock()):
                        with patch.object(watch, "checkpoint", Mock()) as checkpoint:
                            unclaimed = {}
                            watch.poll_dynamic_dispatches(known, now=now, unclaimed=unclaimed)
                            self.assertEqual(unclaimed, {})
                            self.assertIn("refuse-dyn-7174526907.json",
                                          [c.args[0] for c in checkpoint.call_args_list])
                            checkpoint.reset_mock()
                            unclaimed = {}
                            watch.poll_dynamic_dispatches(known, now=now, unclaimed=unclaimed)
                            self.assertEqual(unclaimed, {})
                            self.assertNotIn("refuse-dyn-7174526907.json",
                                             [c.args[0] for c in checkpoint.call_args_list])

    def test_a_fresh_shape_refusal_is_still_named_by_reason(self):
        now = datetime(2026, 11, 27, 10, 0, tzinfo=timezone.utc)
        comment = self._comment(
            "STEER DISPATCH - Lane 1" + NL +
            'Text for the runner to send into Lane 1' + S + 's session, '
            "verbatim: fix the driver." + NL,
            cid=7224000000, created="2026-11-27T09:50:00Z")
        with patch.dict("os.environ", {"LOCALAPPDATA": tempfile.gettempdir()}):
            with patch.object(watch, "api", return_value=[comment]):
                with patch.object(watch, "advance_cursor", Mock()):
                    with patch.object(watch, "checkpoint", Mock()):
                        unclaimed = {}
                        watch.poll_dynamic_dispatches(set(), now=now, unclaimed=unclaimed)
        self.assertEqual(unclaimed, {7224000000: "banner-names-no-restart"})


if __name__ == "__main__":
    unittest.main()

class CheckpointIdempotenceTests(unittest.TestCase):
    """Measured 2026-11-27: an existing marker 422d every tick and stopped claims."""

    def test_an_existing_checkpoint_is_updated_with_its_own_sha(self):
        calls = []

        def fake_api(path, method=None, body=None):
            calls.append((path, method, body))
            if method == "PUT" and "sha" not in (body or {}):
                raise RuntimeError("GitHub PUT failed for " + path
                                   + ': gh: Invalid request.' + chr(10) + chr(10)
                                   + '"sha" wasn' + "'t supplied. (HTTP 422)'")
            if method is None:
                return {"sha": "abc123"}
            return {"content": {"sha": "abc123"}}

        with patch.object(watch, "api", Mock(side_effect=fake_api)), \
                patch.object(watch, "_monitor_enabled", Mock(return_value=False)):
            watch.checkpoint("skip-dyn-1-lane.json", {"dispatch": 1})
        puts = [call for call in calls if call[1] == "PUT"]
        self.assertEqual(len(puts), 2)
        self.assertEqual(puts[-1][2]["sha"], "abc123")

    def test_an_unrelated_failure_is_still_raised(self):
        def fake_api(path, method=None, body=None):
            raise RuntimeError("GitHub PUT failed: gh: Bad credentials (HTTP 401)")

        with patch.object(watch, "api", Mock(side_effect=fake_api)), \
                patch.object(watch, "_monitor_enabled", Mock(return_value=False)):
            with self.assertRaises(RuntimeError):
                watch.checkpoint("skip-dyn-2-lane.json", {"dispatch": 2})


class PinnedRuntimeHomeTests(unittest.TestCase):
    """G4: the watch executes a pinned home, so dev-tree dirtiness is not input.

    Twelve ticks refused on 2026-11-27 with "uncommitted changes under scripts/
    in the driver worktree" - each one a lane editing the cure it was about to
    test in the tree the watch runs from. The gate now reads the executing
    tree's own pin instead of the dev checkout's git state.
    """

    def _home(self, tmp_path, *, sha="a" * 40):
        from scripts import driver_runtime_home as home_mod
        root = Path(tmp_path) / "runtime"
        (root / "scripts").mkdir(parents=True)
        (root / "driver_core").mkdir(parents=True)
        (root / "scripts" / "windows_freebuff_watch.py").write_text("# watch\n", encoding="utf-8")
        (root / "driver_core" / "__init__.py").write_text("# core\n", encoding="utf-8")
        home_mod.write_pin(root, sha, source="test")
        return root

    def test_a_pinned_home_runs_without_reading_the_dev_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._home(tmp)
            with patch.dict("os.environ", {"HARNESS_DRIVER_RUNTIME_ROOT": str(root)}), \
                 patch.object(watch, "_head_pair") as head_pair:
                self.assertEqual(watch.worktree_head(refresh=True), "a" * 40)
            head_pair.assert_not_called()

    def test_a_byte_drifting_from_the_pin_refuses_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._home(tmp)
            (root / "scripts" / "windows_freebuff_watch.py").write_text("# edited\n", encoding="utf-8")
            with patch.dict("os.environ", {"HARNESS_DRIVER_RUNTIME_ROOT": str(root)}):
                self.assertIsNone(watch.worktree_head(refresh=True))
                detail = watch.head_refusal_detail()
            self.assertIn("does not match its pin", detail)
            self.assertIn("scripts/windows_freebuff_watch.py", detail)

    def test_install_pins_committed_bytes_and_ignores_a_dirty_source(self):
        import shutil
        import subprocess

        if shutil.which("git") is None:
            self.skipTest("deps: git is required to materialize a runtime home")
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "dev"
            (source / "scripts").mkdir(parents=True)
            (source / "driver_core").mkdir(parents=True)
            (source / "scripts" / "windows_freebuff_watch.py").write_text("# committed\n", encoding="utf-8")
            (source / "driver_core" / "__init__.py").write_text("# committed\n", encoding="utf-8")
            for args in (("init", "-q"), ("add", "-A"), ("-c", "user.email=ci@example.invalid",
                                                          "-c", "user.name=ci", "commit", "-qm", "base")):
                subprocess.run(["git", "-C", str(source), *args], check=True,
                               capture_output=True, text=True)
            sha = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], check=True,
                                 capture_output=True, text=True).stdout.strip()
            # The dev tree is dirty in exactly the way that used to refuse every tick.
            (source / "scripts" / "windows_freebuff_watch.py").write_text("# uncommitted\n", encoding="utf-8")

            from scripts import driver_runtime_home as home_mod
            pinned = home_mod.install(source, Path(tmp) / "home")

            self.assertEqual(pinned["sha"], sha)
            installed = (Path(tmp) / "home" / "scripts" / "windows_freebuff_watch.py").read_text(encoding="utf-8")
            self.assertEqual(installed, "# committed\n")
            self.assertEqual(home_mod.verify(Path(tmp) / "home"), (True, "matches the pin"))
            with patch.dict("os.environ", {"HARNESS_DRIVER_RUNTIME_ROOT": str(Path(tmp) / "home")}):
                self.assertEqual(watch.worktree_head(), sha)


class StandingPromptRegistryClaimTests(unittest.TestCase):
    """G13's two claim-path obligations, at the seam that decides them."""

    def test_an_unregistered_lane_parks_named_and_no_input_is_sent(self):
        now = datetime(2026, 11, 28, 5, 0, tzinfo=timezone.utc)
        comment = {
            "id": 995801,
            "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-28T04:55:00Z",
            "body": "RESTART DISPATCH\nLane: Lane 1\nAction for the runner: \"continue in full\"",
        }
        with tempfile.TemporaryDirectory() as tmp:
            home = pinned_home(tmp)  # a pinned home with no prompt registered
            write = Mock()
            posted = Mock()
            execute = Mock()
            with patch.dict("os.environ", {"LOCALAPPDATA": tmp,
                                           "HARNESS_DRIVER_RUNTIME_ROOT": str(home)}), \
                 patch.object(watch, "api", return_value=[comment]), \
                 patch.object(watch, "guard_approval", Mock()), \
                 patch.object(watch, "desktop_idle", lambda: True), \
                 patch.object(watch, "foreground_blocker", return_value=None), \
                 patch.object(watch, "checkpoint", write), \
                 patch.object(watch, "issue_comment", posted), \
                 patch.object(watch, "advance_cursor", Mock()), \
                 runtime_present(), \
                 patch.object(watch, "execute", execute):
                self.assertTrue(watch.poll_dynamic_dispatches(set(), now=now))
        execute.assert_not_called()
        names = [call.args[0] for call in write.call_args_list]
        self.assertEqual(names, ["parked-dyn-995801-315608d2-no-prompt-registered.json"])
        self.assertEqual(write.call_args.args[1]["state"], "parked: no-prompt-registered")
        self.assertIn("no-prompt-registered", posted.call_args.args[0])
        self.assertIn("No input was sent", posted.call_args.args[0])

    def test_the_prompt_file_reaches_the_child_and_the_verdict_carries_its_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            audit = AuditLog(output / "runner.jsonl")
            prompt = output / "prompt.txt"
            prompt.write_bytes(b"registered steer\n")
            fake = Mock(returncode=0)
            fake.communicate.return_value = ("", "")
            with patch.object(runner.subprocess, "Popen", return_value=fake) as popen:
                self.assertTrue(runner.run_phases(output, watch.THREAD, audit, ("send",),
                                                  standing=True, text_file=prompt))
            command = popen.call_args.args[0]
            self.assertIn("-TextFile", command)
            self.assertEqual(command[command.index("-TextFile") + 1], str(prompt))

    def test_claim_is_acked_immediately_and_the_verdict_carries_three_stamps(self):
        """Pickup discipline (7157864331): ack on claim, then filed/claimed/completed."""
        now = datetime(2026, 11, 28, 6, 0, tzinfo=timezone.utc)
        comment = {
            "id": 996001,
            "user": {"id": watch.OWNER_ID},
            "created_at": "2026-11-28T05:58:00Z",
            "body": "RESTART DISPATCH\nLane: Lane 1\nAction for the runner: \"continue in full\"",
        }
        order = []
        with tempfile.TemporaryDirectory() as tmp:
            home = pinned_home(tmp, "Lane 1")
            write = Mock()
            posted = Mock(side_effect=lambda text: order.append(("comment", text)))
            execute = Mock(side_effect=lambda *a, **k: order.append(("execute", "")) or 0)
            with patch.dict("os.environ", {"LOCALAPPDATA": tmp,
                                           "HARNESS_DRIVER_RUNTIME_ROOT": str(home)}), \
                 patch.object(watch, "api", return_value=[comment]), \
                 patch.object(watch, "guard_approval", Mock()), \
                 patch.object(watch, "desktop_idle", lambda: True), \
                 patch.object(watch, "foreground_blocker", return_value=None), \
                 patch.object(watch, "checkpoint", write), \
                 patch.object(watch, "issue_comment", posted), \
                 patch.object(watch, "advance_cursor", Mock()), \
                 runtime_present(), \
                 patch.object(watch, "execute", execute):
                self.assertTrue(watch.poll_dynamic_dispatches(set(), now=now))
        # The ack is the first word on the issue and it precedes any input.
        self.assertEqual(order[0][0], "comment")
        self.assertIn("ack #996001", order[0][1])
        self.assertIn("claimed 2026-11-28T", order[0][1])
        self.assertIn("filed 2026-11-28T05:58:00Z", order[0][1])
        self.assertEqual(order[1][0], "execute")
        verdict = [text for kind, text in order if kind == "comment" and "result #996001" in text]
        self.assertEqual(len(verdict), 1)
        for stamp in ("filed 2026-11-28T05:58:00Z", ", claimed 2026-11-28T",
                      ", completed 2026-11-28T", "pickup ", "execution "):
            self.assertIn(stamp, verdict[0])
        saved = {call.args[0]: call.args[1] for call in write.call_args_list}
        self.assertIn("ack-dyn-996001-315608d2.json", saved)
        result = saved["result-dyn-996001-315608d2.json"]
        self.assertEqual(result["filed_at"], "2026-11-28T05:58:00Z")
        self.assertTrue(result["claimed_at"].startswith("2026-11-28T"))
        self.assertTrue(result["completed_at"].startswith("2026-11-28T"))
        # The stamps are wall-clock at claim; only the shape is asserted here.
        self.assertIsInstance(result["pickup_seconds"], int)
        self.assertGreaterEqual(result["pickup_seconds"], 0)
        self.assertEqual(result["execution_seconds"], 0)


class DispatchIssueLockTests(unittest.TestCase):
    """#684 hit the 2500-comment cap; a verdict must still be filed somewhere."""

    def test_a_locked_dispatch_issue_files_the_same_verdict_on_the_tracker(self):
        locked = RuntimeError("GitHub POST failed for repos/Treystu/harness/issues/684/comments: "
                              "Commenting is disabled on issues with more than 2500 comments")
        calls = []

        def fake_api(endpoint, *, method="GET", body=None, attempts=3):
            calls.append((endpoint, body["body"]))
            if len(calls) == 1:
                raise locked
            return {"id": 1}

        with patch.object(runner, "api", side_effect=fake_api):
            runner.post_comment("Vision watch ack #1 / `lane`: claimed now; executing now.")
        self.assertEqual(calls[0][0], runner.ISSUE)
        self.assertEqual(calls[1][0], runner.FALLBACK_ISSUE)
        self.assertIn("Vision watch ack #1", calls[1][1])
        self.assertIn("Filed on #295", calls[1][1])
        self.assertIn("more than 2500 comments", calls[1][1])

    def test_an_unrelated_post_failure_is_not_swallowed(self):
        with patch.object(runner, "api", side_effect=RuntimeError("GitHub POST failed for x: HTTP 500")):
            with self.assertRaises(RuntimeError):
                runner.post_comment("Vision watch result #2: verified running.")
