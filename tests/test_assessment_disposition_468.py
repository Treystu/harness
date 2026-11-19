"""Issue #468: the assessment gate persists its five distributions and its disposition.

The Champion brief could not be executed because no assessment's aspect
distributions or outcome label were ever written down, so no assessment could
be replayed. The write lives in the gate itself and goes through the one
trace writer that already exists (`harness/decision_trace.py` over the
hash-chained `AutonomyLedger`); these tests pin the record's content, the
exact distributions, the refused cases, and the CLI seam that produces it.
"""
import io
import json
import os
import tempfile
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock, TestCase

from harness import cli
from harness.decision_trace import (
    DecisionTrace, TraceSinkUnavailable, read_trace_events,
)
from harness.jev_assessment import (
    ASPECTS, BAND_BELOW, BAND_FLEX, BAND_GREEN, BLOCK, DISPOSITION_EVENT, PASS,
    AssessmentError, disposition_payload, record_disposition,
    verdict_for_payload,
)
from harness.ledger import AutonomyLedger


def _green():
    return {BAND_GREEN: 0.9, BAND_FLEX: 0.05, BAND_BELOW: 0.05}


def _payload(**overrides):
    """A complete five-aspect judgement; every aspect green unless overridden."""
    aspects = {name: {"probabilities": dict(overrides.get(name) or _green())}
               for name in ASPECTS}
    for name, value in overrides.items():
        if name in ASPECTS and value is None:
            aspects[name] = {"relevant": False,
                             "reason": "no claims in this aspect"}
    return {"aspects": aspects}


class DispositionPayloadTests(TestCase):
    def test_payload_carries_every_aspect_distribution_verbatim(self):
        payload = disposition_payload(verdict_for_payload(_payload()))
        self.assertEqual(payload["decision"], PASS)
        self.assertTrue(payload["ok"])
        self.assertEqual([row["aspect"] for row in payload["aspects"]],
                         list(ASPECTS))
        for row in payload["aspects"]:
            self.assertEqual(row["probabilities"], _green())
            self.assertEqual(row["band"], BAND_GREEN)

    def test_payload_is_not_renormalised_or_rounded(self):
        verdict = verdict_for_payload(_payload(
            correctness={BAND_GREEN: 0.7000001, BAND_FLEX: 0.1999999,
                         BAND_BELOW: 0.1}))
        row = [item for item in disposition_payload(verdict)["aspects"]
               if item["aspect"] == "correctness"][0]
        self.assertEqual(row["probabilities"][BAND_GREEN], 0.7000001)

    def test_irrelevant_aspect_keeps_its_reason_and_no_distribution(self):
        payload = disposition_payload(
            verdict_for_payload(_payload(no_regression=None)))
        row = [item for item in payload["aspects"]
               if item["aspect"] == "no_regression"][0]
        self.assertFalse(row["relevant"])
        self.assertEqual(row["probabilities"], {})
        self.assertEqual(row["reason"], "no claims in this aspect")
        self.assertIn("no_regression was declared irrelevant",
                      " ".join(payload["notes"]))

    def test_blocking_disposition_is_recorded_as_a_block(self):
        payload = disposition_payload(verdict_for_payload(_payload(
            confidence={BAND_GREEN: 0.2, BAND_FLEX: 0.2, BAND_BELOW: 0.6})))
        self.assertEqual(payload["decision"], BLOCK)
        self.assertFalse(payload["ok"])

    def test_composer_is_referenced_not_duplicated(self):
        verdict = verdict_for_payload(
            dict(_payload(), composer={"verdict": "proceed"}))
        payload = disposition_payload(verdict)
        self.assertTrue(payload["composer_present"])
        self.assertNotIn("composer", payload)

    def test_payload_refuses_something_that_is_not_a_verdict(self):
        with self.assertRaises(AssessmentError):
            disposition_payload({"decision": PASS})


class RecordDispositionTests(TestCase):
    def test_record_persists_one_replayable_event(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = AutonomyLedger(os.path.join(directory, "ledger.jsonl"))
            entry = record_disposition(
                DecisionTrace(ledger), verdict_for_payload(_payload()),
                subject_id="spec-42", call_id="call-7")
            self.assertEqual(entry["kind"], DISPOSITION_EVENT)
            self.assertEqual(entry["trace_version"], "trace_v1")
            self.assertEqual(entry["subject_id"], "spec-42")
            self.assertEqual(entry["call_id"], "call-7")
            self.assertEqual(entry["spec_ref"], "jev_assessment.assess")

            rows = read_trace_events(ledger, kinds=[DISPOSITION_EVENT])
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["event_id"], entry["event_id"])
            self.assertEqual(len(rows[0]["aspects"]), len(ASPECTS))
            self.assertEqual(rows[0]["decision"], PASS)

    def test_subject_id_is_required(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = AutonomyLedger(os.path.join(directory, "ledger.jsonl"))
            trace = DecisionTrace(ledger)
            verdict = verdict_for_payload(_payload())
            for bad in ("", "   ", None):
                with self.subTest(bad=bad):
                    with self.assertRaises(AssessmentError):
                        record_disposition(trace, verdict, subject_id=bad)
            self.assertEqual(read_trace_events(ledger), [])

    def test_subject_id_is_stripped_and_spec_ref_can_be_named(self):
        with tempfile.TemporaryDirectory() as directory:
            entry = record_disposition(
                DecisionTrace(AutonomyLedger(
                    os.path.join(directory, "ledger.jsonl"))),
                verdict_for_payload(_payload()), subject_id="  spec-9  ",
                spec_ref="cli.assess")
            self.assertEqual(entry["subject_id"], "spec-9")
            self.assertEqual(entry["spec_ref"], "cli.assess")

    def test_audit_enabled_write_fails_closed_on_a_dead_sink(self):
        class _Broken:
            path = "broken.jsonl"

            def append(self, entry):
                raise OSError("sink gone")

            def segment_paths(self):
                return []

            def tail(self, limit=100):
                return []

        with self.assertRaises(TraceSinkUnavailable):
            record_disposition(
                DecisionTrace(_Broken()), verdict_for_payload(_payload()),
                subject_id="spec-1", audit_enabled=True)


class AssessCliTraceTests(TestCase):
    def _invoke(self, argv):
        out = io.StringIO()
        with mock.patch("harness.cli.load_settings",
                        return_value=SimpleNamespace()):
            with redirect_stdout(out):
                with self.assertRaises(SystemExit) as raised:
                    cli.main(argv)
        return raised.exception.code, out.getvalue()

    def _payload_file(self, directory):
        path = os.path.join(directory, "judgement.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(_payload(), handle)
        return path

    def test_cli_writes_the_row_it_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            payload_path = self._payload_file(directory)
            ledger_path = os.path.join(directory, "ledger.jsonl")

            code, stdout = self._invoke(
                ["assess", "--input", payload_path, "--trace-ledger",
                 ledger_path, "--subject", "spec-cli"])
            self.assertEqual(code, 0)
            report = json.loads(stdout)
            self.assertEqual(report["trace"]["ledger"], ledger_path)
            self.assertEqual(report["trace"]["kind"], DISPOSITION_EVENT)

            rows = read_trace_events(ledger_path, kinds=[DISPOSITION_EVENT])
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["event_id"], report["trace"]["event_id"])
            self.assertEqual(rows[0]["subject_id"], "spec-cli")
            self.assertEqual(rows[0]["spec_ref"], "cli.assess")

    def test_cli_without_a_subject_refuses_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            payload_path = self._payload_file(directory)
            ledger_path = os.path.join(directory, "ledger.jsonl")

            code, stdout = self._invoke(
                ["assess", "--input", payload_path, "--trace-ledger",
                 ledger_path])
            self.assertEqual(code, 2)
            self.assertFalse(json.loads(stdout)["ok"])
            self.assertEqual(read_trace_events(ledger_path), [])

    def test_cli_does_not_write_when_no_ledger_was_named(self):
        with tempfile.TemporaryDirectory() as directory:
            code, stdout = self._invoke(
                ["assess", "--input", self._payload_file(directory)])
            self.assertEqual(code, 0)
            self.assertNotIn("trace", json.loads(stdout))


class ReaderPathTests(TestCase):
    def test_the_reader_reads_a_bare_path_as_its_docstring_promises(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger_path = os.path.join(directory, "ledger.jsonl")
            record_disposition(
                DecisionTrace(AutonomyLedger(ledger_path)),
                verdict_for_payload(_payload()), subject_id="spec-path")
            rows = read_trace_events(ledger_path, kinds=[DISPOSITION_EVENT])
            self.assertEqual([row["subject_id"] for row in rows], ["spec-path"])


class GateOwnershipTests(TestCase):
    def test_the_gate_has_one_trace_kind_and_no_second_sink(self):
        import harness.jev_assessment as module

        self.assertEqual(DISPOSITION_EVENT, "assessment.disposition")
        with open(module.__file__, encoding="utf-8") as handle:
            source = handle.read()
        # The write goes through the shared writer: the gate never mints an
        # event id, never opens a ledger and never defines a segment.
        self.assertIn("trace.record(", source)
        self.assertNotIn("uuid", source)
        self.assertNotIn("AutonomyLedger(", source)
        self.assertNotIn("def segment", source)
