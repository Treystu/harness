"""#336: the timed daily sweep and the routed evidence consumers.

Both halves are exercised at their real seam: a real ledger on disk with a real
sealed segment, the real ``LedgerSweeper`` thread (start/stop, no mocked
scheduler), the real CLI-shaped entrypoint with its persisted state file, and
the real consumers that selection/calibration/export call -- seeded with canary
rows attractive enough that any leak would change their answers.
"""
import hashlib
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from harness import capability, ledger_canary, ledger_sweep, refine, saturation, site_export
from harness.errors import HarnessError
from harness.ledger import AutonomyLedger, _canon
from harness.ledger_sweep import LedgerSweeper, run_daily_sweep, sweep_due

OLD = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(timespec="seconds")


def _row(seq, event, prev, **fields):
    entry = {"seq": seq, "ts": OLD, "event": event, "task_id": None,
             "prev_hash": prev}
    entry.update(fields)
    entry["hash"] = hashlib.sha256(_canon(entry).encode("utf-8")).hexdigest()
    return entry


class SweepFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name
        self.path = os.path.join(self.dir, "ledger.jsonl")
        self.state = os.path.join(self.dir, "ledger.jsonl.sweep-state")
        self.key = os.path.join(self.dir, "signing.key")
        patcher = mock.patch.dict(os.environ,
                                  {"HARNESS_LEDGER_SIGNING_KEY": self.key})
        patcher.start()
        self.addCleanup(patcher.stop)

    def seal(self):
        """Four old sealed segments, so the newest three are kept in full.

        The oldest segment carries a compactable canary row in the middle of
        two protected rows: the sweep must drop exactly that one and cross the
        gap with a signed run.
        """
        rows, prev = [], None
        for index in range(12):
            event = "canary_probe" if index in (1, 5, 8) else "jev_eval"
            if event == "canary_probe":
                row = _row(index + 1, event, prev, canary=True, ok=True,
                           probe="routing_resolves")
            else:
                row = _row(index + 1, event, prev, verdict="pass")
            rows.append(row)
            prev = row["hash"]
        for index in range(4):
            chunk = rows[index * 3:(index + 1) * 3]
            name = self.path + ".2026090{}T000000.000001".format(index + 1)
            with open(name, "wb") as handle:
                for row in chunk:
                    handle.write((_canon(row) + "\n").encode())
        tail = _row(13, "offer", prev, caller="tests/tail")
        with open(self.path, "wb") as handle:
            handle.write((_canon(tail) + "\n").encode())

    def ledger(self):
        return AutonomyLedger(self.path)


class DailySweepTests(SweepFixture):
    def test_due_rule_is_one_sweep_per_utc_day(self):
        now = datetime.now(timezone.utc).timestamp()
        self.assertTrue(sweep_due(now))
        self.assertFalse(sweep_due(now, last_sweep_epoch=now))
        self.assertTrue(sweep_due(now + 86400, last_sweep_epoch=now))

    def test_the_entrypoint_sweeps_once_and_remembers_its_state(self):
        self.seal()
        first = run_daily_sweep(self.ledger(), state_file=self.state)
        self.assertTrue(first["ran"])
        self.assertEqual(first["compacted"], 1)
        second = run_daily_sweep(AutonomyLedger(self.path), state_file=self.state)
        self.assertFalse(second["ran"])
        self.assertIn("already swept", second["reason"])
        forced = run_daily_sweep(AutonomyLedger(self.path), state_file=self.state,
                                 force=True)
        self.assertTrue(forced["ran"])
        self.assertTrue(os.path.exists(self.state))

    def test_the_state_file_survives_a_missing_or_unwritable_path(self):
        self.assertIsNone(ledger_sweep.read_last_sweep(None))
        broken = os.path.join(self.dir, "missing", "state")
        ledger_sweep.write_last_sweep(broken, 1.0)
        self.assertTrue(os.path.exists(broken))
        self.assertEqual(ledger_sweep.read_last_sweep(broken), 1.0)
        with open(broken, "w", encoding="utf-8") as handle:
            handle.write("not a number")
        self.assertIsNone(ledger_sweep.read_last_sweep(broken))
        with mock.patch.object(ledger_sweep.os, "makedirs",
                               side_effect=OSError("read-only")):
            ledger_sweep.write_last_sweep(broken, 2.0)  # degrades, never raises

    def test_the_timer_thread_sweeps_a_quiet_ledger_without_rotation(self):
        self.seal()
        seen = []
        sweeper = LedgerSweeper(lambda: AutonomyLedger(self.path),
                                interval=0.01, on_sweep=seen.append)
        sweeper.start()
        deadline = time.time() + 10
        while time.time() < deadline and not (sweeper.last_result or {}).get("ran"):
            time.sleep(0.01)
        sweeper.stop()
        self.assertTrue(sweeper.last_result["ran"])
        self.assertEqual(sweeper.last_result["compacted"], 1)
        self.assertTrue(seen)
        fresh = AutonomyLedger(self.path)
        status = fresh.chain_status()
        self.assertTrue(status["ok"], status)
        self.assertTrue(status["checkpoint_covered"])
        self.assertEqual(len(status["checkpoint_covered"]), 1)

    def test_a_second_tick_the_same_day_does_not_sweep(self):
        self.seal()
        sweeper = LedgerSweeper(lambda: AutonomyLedger(self.path))
        self.assertTrue(sweeper.tick()["ran"])
        second = sweeper.tick()
        self.assertFalse(second["ran"])
        sweeper.stop()  # no thread started: stop is safe

    def test_the_ledger_command_carries_the_sweep_entrypoint(self):
        from harness.cli_parser import build_parser

        opts = build_parser().parse_args(["ledger", "sweep", "--force"])
        self.assertEqual(opts.ledger_cmd, "sweep")
        self.assertTrue(opts.force)


class EvidenceReaderRoutingTests(unittest.TestCase):
    """A canary row attractive enough that any leak changes the answer."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "ledger.jsonl")
        self.ledger = AutonomyLedger(self.path)

    def seed_canaries(self):
        """Twenty-five labelled canary rows, attractive to every consumer."""
        for index in range(5):
            task = "canary-{}".format(index)
            self.ledger.append("offer", task_id=task, model="m2", canary=True)
            self.ledger.append("task_outcome", task_id=task, task_family="fam",
                               outcome=1.0, model="m2", canary=True)
            self.ledger.append("model_result", task_id=task, model="m2",
                               json_expected=True, json_ok=True, canary=True)
            self.ledger.append("apply_attempt", task_id=task, model="m2",
                               canary=True)
            self.ledger.append("model_result", task_id=task, model="m1",
                               status="429", canary=True)

    def seed(self):
        # Real task evidence: one honest outcome, one honest miss.
        self.ledger.append("offer", task_id="real-1", model="m1")
        self.ledger.append("task_outcome", task_id="real-1", task_family="fam",
                           outcome=0.9, model="m1")
        self.ledger.append("model_result", task_id="real-1", model="m1",
                           json_expected=True, json_ok=True)
        self.ledger.append("apply_attempt", task_id="real-1", model="m1")
        self.seed_canaries()

    def test_participation_report_counts_task_evidence_only(self):
        self.ledger.append("offer", task_id="real-1", model="m1")
        self.ledger.append("apply_attempt", task_id="real-1", model="m1")
        self.ledger.append("complete", task_id="real-1", ok=True)
        before = self.ledger.participation_report()
        self.seed_canaries()
        after = self.ledger.participation_report()
        # Twenty canary rows land between the two reads; the per-model tally
        # and its calibration block may not budge.
        self.assertEqual(after["per_model"], before["per_model"])
        self.assertEqual(after["calibration"], before["calibration"])
        self.assertNotIn("m2", after["per_model"])

    def test_capability_observed_reliability_ignores_canary_rows(self):
        self.seed()
        self.assertEqual(capability.observed_samples(self.ledger, "m2"), 0)
        self.assertIsNone(capability.observed_json_reliability(self.ledger, "m2"))
        self.assertEqual(capability.observed_samples(self.ledger, "m1"), 1)
        self.assertEqual(
            capability.observed_json_reliability(self.ledger, "m1"), 1.0)

    def test_seat_share_is_a_task_selection_view(self):
        self.seed()
        report = capability.seat_share_report(self.ledger)
        self.assertNotIn("m2", json.dumps(report))

    def test_refinement_outcomes_ignore_canary_rows(self):
        self.seed()
        self.assertIsNone(refine.get_task_outcome(self.ledger, "canary-0"))
        self.assertIsNotNone(refine.get_task_outcome(self.ledger, "real-1"))
        rows = refine.recent_outcomes(self.ledger, "fam")
        self.assertEqual([row.get("task_id") for row in rows], ["real-1"])

    def test_the_pre_run_gate_does_not_fire_on_canary_429s(self):
        self.seed()
        with mock.patch.object(saturation, "_warned_this_process", False):
            self.assertFalse(saturation.pre_run_warning(ledger=self.ledger,
                                                        use_free=True))

    def test_export_refuses_a_canary_only_ledger(self):
        self.ledger.append("model_result", model="m1", canary=True, ok=True)
        with self.assertRaises(HarnessError):
            site_export.verify_chain(self.path)

    def test_the_calibration_join_ignores_canary_evals(self):
        self.ledger.append("offer", task_id="real-1", model="m1")
        self.ledger.append("offer", task_id="canary-1", model="m1", canary=True)
        self.ledger.append("jev_eval", task_id="real-1", site="s",
                           verdict="pass", confidence=0.9, supported=True,
                           is_fallback=False)
        self.ledger.append("jev_eval", task_id="canary-1", site="s",
                           verdict="pass", confidence=1.0, supported=True,
                           is_fallback=False, canary=True)
        report = self.ledger.jev_calibration_report()
        self.assertEqual(report.get("jev_evals"), 1)
        self.assertEqual(report.get("tasks_with_jev"), 1)

    def test_the_shared_reader_is_the_single_exclusion_point(self):
        self.seed()
        rows = ledger_canary.evidence_rows(self.ledger)
        self.assertTrue(all(row.get("canary") is not True for row in rows))
        self.assertEqual(len(rows), len(self.ledger.entries()) - 25)


if __name__ == "__main__":
    unittest.main()
