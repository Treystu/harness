"""#476: ceiling refusals recorded with the refused call's outcome.

The Champion brief for spend ceilings, terminal reserve and sizing could not run:
"harness ceiling refusals are not recorded as events and refused runs carry no
outcome" (#466 brief, unblocker: *record each refusal with the refused run's
outcome*). Nothing said which check refused, against what envelope, or for how
much, so neither the protective-vs-starving classification nor the denominator of
ceiling hits had a numerator.

Each refusal now writes one ``spend.refusal`` row through the trace family the
run already holds: the check that refused, the phase, the dual-budget envelope it
refused against, the amount requested, and the refused call's own outcome. These
tests pin the row, its absence rule for unknown values, and legacy tolerance.
"""
import os
import tempfile
import unittest

from harness.decision_trace import DecisionTrace, read_trace_events
from harness.errors import HarnessError
from harness.ledger import AutonomyLedger
from harness.spend import REFUSAL_EVENT, SpendGovernor


def _ledger():
    directory = tempfile.TemporaryDirectory()
    ledger = AutonomyLedger(os.path.join(directory.name, "ledger.jsonl"))
    return directory, ledger


def _governor(ledger=None, *, max_cost=0.000001, trace=True, **kwargs):
    return SpendGovernor(
        transport=None, api_key="k", max_cost=max_cost,
        trace=DecisionTrace(ledger) if (trace and ledger is not None) else None,
        **kwargs)


def _rows(ledger):
    return read_trace_events(ledger, kinds=[REFUSAL_EVENT])


class RefusalRowTests(unittest.TestCase):
    def test_a_ceiling_refusal_is_recorded_on_the_existing_row(self):
        directory, ledger = _ledger()
        self.addCleanup(directory.cleanup)
        governor = _governor(ledger)

        with self.assertRaises(HarnessError) as caught:
            governor.preflight_jev(100_000, label="jev")

        rows = _rows(ledger)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["site"], "jev_preflight")
        self.assertEqual(row["phase"], "attempt")
        # The refused call's own outcome: it did not run.
        self.assertEqual(row["outcome"], "refused")
        self.assertGreater(row["requested"], 0.0)
        self.assertEqual(row["label"], "jev")
        self.assertEqual(row["envelope"]["max_cost"], 0.000001)
        self.assertEqual(row["envelope"]["terminal_reserve"], 0.0)
        self.assertEqual(row["envelope"]["phase_ceiling"], 0.000001)
        self.assertEqual(row["spec_ref"], "spend.ceiling")
        # The row is the family's, and its kind is the refusal's own.
        self.assertEqual(row["kind"], REFUSAL_EVENT)
        self.assertIn("exceeds remaining budget", row["reason"])
        self.assertIn("exceeds remaining budget", str(caught.exception))

    def test_the_terminal_reserve_unlock_is_visible_in_the_envelope(self):
        directory, ledger = _ledger()
        self.addCleanup(directory.cleanup)
        governor = _governor(ledger, max_cost=0.01, terminal_reserve=0.004)

        with self.assertRaises(HarnessError):
            governor.preflight_jev(10_000_000)

        row = _rows(ledger)[-1]
        self.assertEqual(row["envelope"]["max_cost"], 0.01)
        self.assertEqual(row["envelope"]["terminal_reserve"], 0.004)
        self.assertEqual(row["envelope"]["phase_ceiling"], 0.01 - 0.004)
        self.assertEqual(row["envelope"]["phase_remaining"], 0.01 - 0.004)

    def test_a_reservation_refusal_records_its_site_and_label(self):
        directory, ledger = _ledger()
        self.addCleanup(directory.cleanup)
        governor = _governor(ledger, max_cost=0.01)

        with self.assertRaises(HarnessError):
            governor.reserve(0.02, "apply_candidate")

        row = _rows(ledger)[-1]
        self.assertEqual(row["site"], "reserve")
        self.assertEqual(row["label"], "apply_candidate")
        self.assertEqual(row["requested"], 0.02)
        self.assertEqual(row["envelope"]["outstanding"], 0.0)

    def test_a_task_scope_refusal_carries_the_scope_it_refused(self):
        directory, ledger = _ledger()
        self.addCleanup(directory.cleanup)
        governor = _governor(ledger, max_cost=1.0)

        with self.assertRaises(HarnessError):
            with governor.task_scope(0.000001, label="task-476"):
                governor.reserve(0.001, "candidate")

        row = _rows(ledger)[-1]
        self.assertEqual(row["site"], "task_scope")
        self.assertEqual(row["scope"], "task-476")
        # The family's own envelope carries the join key, so a later terminal
        # row for the same run can be joined without a second reader.
        self.assertEqual(row["subject_id"], "task-476")

    def test_the_phase_is_recorded_not_assumed(self):
        directory, ledger = _ledger()
        self.addCleanup(directory.cleanup)
        governor = _governor(ledger, max_cost=0.01, terminal_reserve=0.004)
        governor.set_phase("terminal")

        with self.assertRaises(HarnessError):
            governor.reserve(0.02, "terminal_finding")

        row = _rows(ledger)[-1]
        self.assertEqual(row["phase"], "terminal")
        self.assertEqual(row["envelope"]["phase_ceiling"], 0.01)


class AbsenceTests(unittest.TestCase):
    def test_an_unattributable_refusal_records_no_scope_and_no_label(self):
        """Unknown is absent, never defaulted to a made-up scope or label."""
        directory, ledger = _ledger()
        self.addCleanup(directory.cleanup)
        governor = _governor(ledger)

        with self.assertRaises(HarnessError):
            governor.preflight_jev(100_000)

        row = _rows(ledger)[-1]
        self.assertNotIn("scope", row)

        # ...and a scope refusal, which has no single call label, records the
        # scope it names without inventing one.
        governor = _governor(ledger, max_cost=1.0)
        with self.assertRaises(HarnessError):
            with governor.task_scope(0.000001, label="task-476"):
                governor.reserve(0.001, "candidate")
        row = _rows(ledger)[-1]
        self.assertEqual(row["scope"], "task-476")
        self.assertNotIn("label", row)

    def test_without_a_trace_the_refusal_is_unchanged(self):
        directory, ledger = _ledger()
        self.addCleanup(directory.cleanup)
        governor = _governor(ledger, trace=False)

        with self.assertRaises(HarnessError):
            governor.preflight_jev(100_000)

        self.assertEqual(ledger.entries(), [])

    def test_attach_trace_records_on_the_run_s_own_ledger(self):
        directory, ledger = _ledger()
        self.addCleanup(directory.cleanup)
        governor = _governor(ledger, trace=False)
        self.assertIs(governor.attach_trace(DecisionTrace(ledger)), governor)

        with self.assertRaises(HarnessError):
            governor.reserve(1.0, "candidate")

        self.assertEqual(_rows(ledger)[-1]["site"], "reserve")


class LegacyToleranceTests(unittest.TestCase):
    def test_a_ledger_written_before_476_reads_as_no_refusals(self):
        directory, ledger = _ledger()
        self.addCleanup(directory.cleanup)
        ledger.append("offer", task_id="t1")
        ledger.append("model_result", task_id="t1", event_note="apply",
                      model="m", task_type="code", json_expected=False,
                      json_ok=None, status="ok", cost=0.0, reported_cost=0.0)

        self.assertEqual(_rows(ledger), [])
        legacy = [e for e in ledger.tail(10) if e.get("event") == "model_result"]
        self.assertNotIn("outcome", legacy[0])
        self.assertNotIn("envelope", legacy[0])
        ok, detail = ledger.verify()
        self.assertTrue(ok, detail)

    def test_a_refusal_row_without_an_amount_still_reads(self):
        directory, ledger = _ledger()
        self.addCleanup(directory.cleanup)
        DecisionTrace(ledger).record(REFUSAL_EVENT, payload={
            "site": "preflight", "phase": "attempt", "outcome": "refused",
            "reason": "recorded by hand"})

        row = _rows(ledger)[0]
        self.assertEqual(row["site"], "preflight")
        self.assertNotIn("requested", row)
        self.assertNotIn("envelope", row)


if __name__ == "__main__":
    unittest.main()
