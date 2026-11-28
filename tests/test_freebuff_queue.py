"""The dispatch queue is one id, and a comment-capped queue rolls over.

Measured 2026-11-28: #684 hit GitHub's hard 2,500-comment ceiling, every POST
answered 403, the watch ticked in ``state: error`` and nothing could be claimed
or filed. These tests pin the cure: one source for the id, a roll-over instead
of an unrecoverable error, and reads that keep resolving work filed on the
previous queue.
"""
import contextlib
import io
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from scripts import freebuff_queue as queue
from scripts import windows_freebuff_runner as runner
from scripts import windows_freebuff_watch as watch
from harness import laptop_driver_ctl as ctl

CAP_ERROR = ("GitHub POST failed for repos/Treystu/harness/issues/684/comments: gh: "
             "Commenting is disabled on issues with more than 2500 comments (HTTP 403)")
LEGACY_DISPATCH = {"id": 7232458803, "issue_url": "https://api.github.com/repos/Treystu/harness/issues/684",
                   "body": "## RESTART DISPATCH\nLane: Lane 2 (`9ecc3453`)"}


class _StateDir:
    """A queue state file in a temp directory, selected through the env var."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "queue.json"
        patcher = mock.patch.dict(os.environ, {queue.STATE_ENV: str(self.path)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def record(self, current, history=()):
        queue.save({"current": current, "history": list(history)})


class OneQueueIdTests(_StateDir, unittest.TestCase):
    """Runner, watch and ctl must name the same queue, whatever the state says."""

    def test_all_three_read_the_recorded_queue(self):
        self.record(910, history=[684])
        self.assertEqual(queue.queue_id(), 910)
        self.assertEqual(runner.queue_endpoints()[0], queue.comments_endpoint(910))
        self.assertEqual(watch.queue_endpoints()[0], queue.comments_endpoint(910))
        self.assertEqual(ctl.dispatch_issue({}), "910")

    def test_the_default_is_the_queue_the_history_is_on(self):
        self.assertEqual(queue.queue_id(), queue.DEFAULT_QUEUE)
        self.assertEqual(ctl.dispatch_issue({}), str(queue.DEFAULT_QUEUE))

    def test_a_plain_get_call_site_reads_the_same_id(self):
        self.record(911)
        self.assertEqual(runner.ISSUE, queue.comments_endpoint(int(runner.ISSUE.split("/")[-2])))
        self.assertTrue(callable(runner.post_queue_comment))
        self.assertTrue(callable(watch.issue_comment))


class CapDetectionTests(unittest.TestCase):
    def test_the_measured_gh_text_is_recognised(self):
        self.assertTrue(queue.is_comment_cap_error(CAP_ERROR))

    def test_an_unrelated_github_failure_is_not_a_cap(self):
        for text in ("GitHub POST failed: gh: Bad credentials (HTTP 401)",
                     "GitHub POST failed: gh: rate limit exceeded (HTTP 403)",
                     "GitHub POST failed: gh: Not Found (HTTP 404)"):
            self.assertFalse(queue.is_comment_cap_error(text), text)


class RollOverTests(_StateDir, unittest.TestCase):
    def test_a_capped_queue_rolls_over_instead_of_erroring(self):
        self.record(684)
        posted, created = [], []

        def post_to(issue, body):
            if issue == 684:
                raise RuntimeError(CAP_ERROR)
            posted.append((issue, body))
            return {"html_url": f"https://x/{issue}", "queue_issue": issue}

        def create(current, reason):
            created.append((current, reason))
            return 906

        # Injected both ways: a unit test must never discover or create a real
        # queue issue (one earlier run did, and its roll-over was real).
        result = queue.post("Vision restart ack #1", post_to=post_to, create=create,
                            locate=lambda current: None)
        self.assertEqual(result["queue_issue"], 906)
        self.assertEqual(posted, [(906, "Vision restart ack #1")])
        self.assertEqual(created, [(684, CAP_ERROR)])
        state = queue.load()
        self.assertEqual(state["current"], 906)
        self.assertIn(684, state["history"])

    def test_an_existing_rollover_queue_is_reused_not_duplicated(self):
        self.record(684)
        posted = []

        def post_to(issue, body):
            if issue == 684:
                raise RuntimeError(CAP_ERROR)
            posted.append(issue)
            return {"queue_issue": issue}

        result = queue.post("x", post_to=post_to, locate=lambda current: 905,
                            create=lambda current, reason: self.fail("must not create a second queue"))
        self.assertEqual(result["queue_issue"], 905)
        self.assertEqual(posted, [905])

    def test_a_non_cap_failure_is_not_masked_by_a_rotation(self):
        self.record(684)

        def post_to(issue, body):
            raise RuntimeError("GitHub POST failed: gh: Bad credentials (HTTP 401)")

        with self.assertRaises(RuntimeError):
            queue.post("x", post_to=post_to, create=lambda c, r: self.fail("no rotation on 401"))

    def test_the_recorded_mapping_survives_a_reload(self):
        queue.record_rotation(907, 684, CAP_ERROR)
        reloaded = queue.load()
        self.assertEqual(reloaded["current"], 907)
        self.assertEqual(reloaded["history"], [684])
        self.assertTrue(reloaded["rolled_at"])
        self.assertIn("2500 comments", reloaded["reason"])


class OutstandingWorkTests(_StateDir, unittest.TestCase):
    """Work already filed must keep resolving after the queue moves."""

    def test_a_dispatch_filed_on_the_old_queue_still_reads(self):
        queue.record_rotation(908, 684, CAP_ERROR)
        self.assertIn(684, queue.queue_ids())
        self.assertEqual(queue.queue_ids()[0], 908)
        self.assertTrue(queue.comment_belongs_to_queue(LEGACY_DISPATCH))

    def test_a_legacy_receipt_resolves_after_two_rollovers(self):
        queue.record_rotation(908, 684, CAP_ERROR)
        queue.record_rotation(909, 908, CAP_ERROR)
        receipt = {"id": 1, "issue_url": "https://api.github.com/repos/Treystu/harness/issues/684"}
        self.assertTrue(queue.comment_belongs_to_queue(receipt))
        self.assertEqual(queue.queue_ids(), [909, 908, 684])

    def test_the_original_queue_is_read_even_with_a_forgotten_state_file(self):
        queue.save({"current": 910, "history": [910]})
        self.assertIn(684, queue.queue_ids())
        self.assertTrue(queue.comment_belongs_to_queue(LEGACY_DISPATCH))

    def test_reads_cover_the_live_queue_then_its_history(self):
        queue.record_rotation(908, 684, CAP_ERROR)
        self.assertEqual(watch.queue_endpoints(),
                         [queue.comments_endpoint(908), queue.comments_endpoint(684)])
        self.assertEqual(runner.queue_endpoints(), watch.queue_endpoints())

    def test_a_comment_on_a_queue_this_driver_never_used_is_refused(self):
        queue.record_rotation(908, 684, CAP_ERROR)
        foreign = {"id": 2, "issue_url": "https://api.github.com/repos/Treystu/harness/issues/1"}
        self.assertFalse(queue.comment_belongs_to_queue(foreign))


class RetargetTests(_StateDir, unittest.TestCase):
    """An oversight-designated queue is authoritative and does not orphan work."""

    def test_a_designated_queue_becomes_live_and_the_previous_one_stays_readable(self):
        self.record(843, history=[684])
        queue.retarget(844, "oversight successor to #684")
        self.assertEqual(queue.queue_id(), 844)
        self.assertEqual(queue.queue_ids(), [844, 843, 684])
        on_843 = {"id": 3, "issue_url": "https://api.github.com/repos/Treystu/harness/issues/843"}
        self.assertTrue(queue.comment_belongs_to_queue(on_843))
        self.assertIn("retargeted", json.loads(self.path.read_text(encoding="utf-8"))["reason"])

    def test_a_retarget_refuses_a_non_issue_number_and_leaves_the_file_alone(self):
        self.record(843, history=[684])
        for bad in ("abc", 0, -4, None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                queue.retarget(bad, "bad")
            self.assertEqual(queue.queue_id(), 843)

    def test_the_cli_prints_the_mapping_it_recorded(self):
        self.record(843, history=[684])
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.assertEqual(queue.main(["--state", str(self.path), "--retarget", "844",
                                         "--reason", "oversight chose #844"]), 0)
        printed = json.loads(buffer.getvalue())
        self.assertEqual(printed["current"], 844)
        self.assertEqual(printed["history"], [843, 684])
        self.assertEqual(queue.queue_id(), 844)

    def test_the_watch_wrapper_alerts_the_queue_it_posts_to(self):
        """control.json keeps the install-time id; an alert must not go there."""
        import importlib.util
        import tempfile
        self.record(844, history=[843, 684])
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "run-watch.py"
            source.write_text(ctl._RUN_WATCH_PY, encoding="utf-8")
            spec = importlib.util.spec_from_file_location("generated_run_watch", source)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            completed = mock.Mock(returncode=0)
            with mock.patch.object(module.subprocess, "run", return_value=completed) as run:
                with mock.patch.dict(os.environ, {"HARNESS_DRIVER_WATCH_NO_ALERT": ""}):
                    self.assertTrue(module._emit_failure_alert({"dispatch_issue": 684}, 1, "boom", 2))
        self.assertEqual(run.call_args.args[0][3], "844")


class StateFileTests(_StateDir, unittest.TestCase):
    def test_an_unreadable_state_file_falls_back_to_the_original_queue(self):
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(queue.queue_id(), queue.DEFAULT_QUEUE)

    def test_the_saved_file_is_the_mapping_callers_read(self):
        queue.save({"current": 912, "history": [684], "reason": "test"})
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(raw["current"], 912)
        self.assertEqual(raw["history"], [684])


if __name__ == "__main__":
    unittest.main()
