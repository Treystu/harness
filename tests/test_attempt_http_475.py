"""#475: per-attempt http_status and timestamps on panel and Jev result rows.

The Champion retry/breaker brief cannot replay anything without an attempt
timeline: the only time value it had was the row's booking ``ts``
(#475 filing `6995705970`). These tests pin the new record shape at both
existing writers -- ``model_result`` for panel seats and the judge,
``jev_eval`` for Jev -- and pin that a landed row without the field still
reads.

Each of the first tests asserts a key the pre-change writers never wrote, so
they fail against the old shape rather than merely passing against the new
one.
"""
import os
import tempfile
import unittest

from harness import attempt_trace
from harness.config import load_settings
from harness.jev_policy import policy_for
from harness.ledger import AutonomyLedger
from harness.panel import panel_judge
from harness.spend import SpendGovernor
from tests._fake import FakeTransport, _gov, comp, m, P1, P2, JUDGE


def _rows(ledger, event):
    return [e for e in ledger.entries() if e.get("event") == event]


class _JevTransport:
    """Hermetic Jev transport: canned (status, body) pairs, in order."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, key, payload, timeout=45):
        self.calls.append(payload)
        status, body = self.responses.pop(0)
        return status, body


class PanelAttemptTimelineTests(unittest.TestCase):
    def _ledger(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        ledger = AutonomyLedger(os.path.join(td.name, "ledger.jsonl"))
        ledger.ensure_offered_task_id("t1", model="(agent)", source="test_setup")
        return ledger

    def test_seat_row_carries_each_attempt_status_and_its_timestamps(self):
        fake = FakeTransport(
            models=[m(P1), m(P2), m(JUDGE)],
            posts=[(429, {"error": {"message": "slow down"}}),
                   comp("take one"), comp("take two"), comp("verdict: agree")])
        gov = _gov(fake)
        ledger = self._ledger()
        panel_judge(transport=fake, api_key="k", governor=gov, prompt="Q?",
                    panel=[P1, P2], judge=JUDGE, ledger=ledger, task_id="t1")

        rows = [r for r in _rows(ledger, "model_result")
                if r.get("event_note") == "panel" and r.get("status") == "ok"
                and r.get("retries") == 1]
        self.assertTrue(rows, "the retried seat's success row was not written")
        row = rows[0]
        # Keys the old writer never wrote: this is the assertion that fails
        # against the pre-change shape.
        self.assertIn(attempt_trace.ATTEMPTS_FIELD, row)
        self.assertIn(attempt_trace.HTTP_STATUS_FIELD, row)
        self.assertEqual(row["http_status"], 200)
        timeline = attempt_trace.timeline(row)
        self.assertEqual([a["http_status"] for a in timeline], [429, 200])
        self.assertEqual([a["attempt"] for a in timeline], [1, 2])
        for attempt in timeline:
            self.assertTrue(attempt["started_at"].endswith("Z"))
            self.assertTrue(attempt["ended_at"].endswith("Z"))
            self.assertLessEqual(attempt["started_at"], attempt["ended_at"])
        self.assertEqual(row["attempt_started_at"], timeline[0]["started_at"])
        self.assertEqual(row["attempt_ended_at"], timeline[-1]["ended_at"])
        # The brief's recovered-call rate, read off the recorded timeline.
        self.assertEqual(attempt_trace.recovered_calls(row), 1)

    def test_failed_seat_row_names_the_status_it_saw(self):
        fake = FakeTransport(
            models=[m(P1), m(P2), m(JUDGE)],
            posts=[(503, {"error": {"message": "unavailable"}}),
                   comp("take two"), comp("verdict")])
        gov = _gov(fake)
        ledger = self._ledger()
        panel_judge(transport=fake, api_key="k", governor=gov, prompt="Q?",
                    panel=[P1, P2], judge=JUDGE, ledger=ledger, task_id="t1")

        failed = [r for r in _rows(ledger, "model_result")
                  if r.get("event_note") == "panel" and r.get("status") == "error"]
        self.assertTrue(failed)
        row = failed[0]
        self.assertEqual(row["http_status"], 503)
        self.assertEqual([a["http_status"]
                          for a in attempt_trace.timeline(row)], [503])

    def test_judge_row_carries_its_own_attempt_timeline(self):
        fake = FakeTransport(models=[m(P1), m(P2), m(JUDGE)],
                             posts=[comp("one"), comp("two"), comp("judged")])
        gov = _gov(fake)
        ledger = self._ledger()
        panel_judge(transport=fake, api_key="k", governor=gov, prompt="Q?",
                    panel=[P1, P2], judge=JUDGE, ledger=ledger, task_id="t1")

        judge_rows = [r for r in _rows(ledger, "model_result")
                      if r.get("event_note") == "judge"]
        self.assertTrue(judge_rows)
        row = judge_rows[0]
        self.assertEqual(row["http_status"], 200)
        timeline = attempt_trace.timeline(row)
        self.assertEqual(len(timeline), 1)
        self.assertEqual(timeline[0]["http_status"], 200)
        self.assertIn("started_at", timeline[0])
        self.assertIn("ended_at", timeline[0])


class JevAttemptTimelineTests(unittest.TestCase):
    def _settings(self):
        return load_settings({"jev_api_key": "jev-key"})

    def _ledger(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        ledger = AutonomyLedger(os.path.join(td.name, "ledger.jsonl"))
        ledger.ensure_offered_task_id("t1", model="(agent)", source="test_setup")
        return ledger

    def test_jev_eval_row_carries_its_attempt_status_and_timestamps(self):
        transport = _JevTransport((200, {
            "model": "jev-test",
            "answers": {"instruction_matches": {"type": "noul", "noul": 0.95}},
            "usage": {"input_tokens": 100, "output_tokens": 3},
        }))
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        ledger = AutonomyLedger(os.path.join(td.name, "ledger.jsonl"))
        governor = SpendGovernor(
            FakeTransport(models=[m("jev-test", prompt="0", completion="0")]),
            "sk-test", max_cost=0.10)
        policy = policy_for(self._settings(), transport=transport,
                            governor=governor, ledger=ledger)
        result, _structural = policy.evaluate_site_reachability(
            {"probe_outcome": "http_response", "http_status": 200})
        self.assertFalse(result.is_fallback)

        rows = _rows(ledger, "jev_eval")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertIn(attempt_trace.ATTEMPTS_FIELD, row)
        self.assertEqual(row["http_status"], 200)
        timeline = attempt_trace.timeline(row)
        self.assertEqual([a["http_status"] for a in timeline], [200])
        self.assertTrue(timeline[0]["started_at"].endswith("Z"))
        self.assertTrue(timeline[0]["ended_at"].endswith("Z"))

    def test_jev_eval_row_on_a_failed_call_records_the_status_it_saw(self):
        transport = _JevTransport((500, {"error": {"message": "boom"}}))
        ledger = self._ledger()
        governor = SpendGovernor(
            FakeTransport(models=[m("jev-test", prompt="0", completion="0")]),
            "sk-test", max_cost=0.10)
        policy = policy_for(self._settings(), transport=transport,
                            governor=governor, ledger=ledger)
        policy.evaluate_site_reachability(
            {"probe_outcome": "http_response", "http_status": 200})

        rows = _rows(ledger, "jev_eval")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["http_status"], 500)
        self.assertEqual([a["http_status"]
                          for a in attempt_trace.timeline(rows[0])], [500])

    def test_a_local_judgment_borrows_no_neighbouring_timeline(self):
        """No call was made, so the row carries no attempt of its own."""
        transport = _JevTransport()  # would raise if called
        ledger = self._ledger()
        governor = SpendGovernor(
            FakeTransport(models=[m("jev-test", prompt="0", completion="0")]),
            "sk-test", max_cost=0.10)
        policy = policy_for(load_settings({"jev_api_key": ""}),
                            transport=transport, governor=governor,
                            ledger=ledger)
        result, structural = policy.evaluate_site_reachability(
            {"probe_outcome": "http_response", "http_status": 200})
        self.assertTrue(result.is_fallback)
        self.assertIn(structural["fallback_reason"],
                      ("missing_key", "explicit_disable"))
        self.assertEqual(transport.calls, [])
        self.assertFalse(attempt_trace.active())


class LandedRowToleranceTests(unittest.TestCase):
    def test_a_row_written_before_475_reads_as_an_empty_timeline(self):
        """Migration: landed JSONL has no timeline; the reader says so."""
        legacy = {"event": "model_result", "status": "ok", "retries": 2,
                  "ts": 1760000000.0}
        self.assertEqual(attempt_trace.timeline(legacy), [])
        self.assertFalse(attempt_trace.has_timeline(legacy))
        self.assertEqual(attempt_trace.recovered_calls(legacy), 0)

    def test_field_names_are_the_ones_the_brief_reads(self):
        self.assertEqual(attempt_trace.ATTEMPTS_FIELD, "attempts")
        self.assertEqual(attempt_trace.HTTP_STATUS_FIELD, "http_status")


if __name__ == "__main__":
    unittest.main()
