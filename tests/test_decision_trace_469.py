"""D5-1 decision trace: one writer/reader, identity, archive pinning, campaign events (#469).

The adopted design (#466 record 7002802650) requires the campaign emitter's
histories to stop being discarded and a single trace family to span the active
ledger file and its retained segments. These tests pin the writer/reader
contract, the identity fields an audit joins on, the window manifest, and the
narrow fail-closed clause (audit-enabled entry points only).
"""
import json
import os
import tempfile
import unittest

from harness.decision_trace import (
    CAMPAIGN_EVENT,
    ENVELOPE_KEYS,
    TRACE_VERSION,
    DecisionTrace,
    TraceError,
    TraceSinkUnavailable,
    envelope,
    pin_window,
    read_trace_events,
    terminal,
)
from harness.flush_loop import EventLedger, record_pass, record_refusal
from harness.ledger import AutonomyLedger


class _Identity:
    digest = "sha256:fixture"
    records = ("record-1", "record-2", "record-3")
    angles = ("analysis", "gaps")
    instruments = ("jev",)


def _ledger(directory, name="ledger.jsonl"):
    return AutonomyLedger(os.path.join(directory, name))


class EnvelopeTests(unittest.TestCase):
    def test_envelope_carries_the_versioned_identity_fields(self):
        event = envelope("campaign.event", subject_id="campaign-a",
                         call_id="call-1", attempt_id="attempt-1",
                         causal_id="cause-1", spec_ref="campaign.event:stop")
        self.assertEqual(event["trace_version"], TRACE_VERSION)
        self.assertEqual(event["kind"], "campaign.event")
        self.assertEqual(event["subject_id"], "campaign-a")
        self.assertEqual(event["call_id"], "call-1")
        self.assertEqual(event["attempt_id"], "attempt-1")
        self.assertEqual(event["causal_id"], "cause-1")
        self.assertEqual(event["spec_ref"], "campaign.event:stop")
        self.assertTrue(event["event_id"])
        self.assertTrue(event["happened_at"])
        # ``appended_at`` is the writer's stamp: the envelope names the fact.
        self.assertEqual(set(ENVELOPE_KEYS) - {"appended_at"}, set(event))

    def test_envelope_refuses_an_empty_kind(self):
        with self.assertRaises(TraceError):
            envelope("  ")

    def test_terminal_payload_names_refusals_and_fallbacks(self):
        self.assertEqual(terminal(state="refused", path="fallback",
                                  reason="no rung"),
                         {"state": "refused", "path": "fallback",
                          "reason": "no rung"})
        with self.assertRaises(TraceError):
            terminal(state="approved")
        with self.assertRaises(TraceError):
            terminal(state="failed", path="telepathy")


class WriterReaderTests(unittest.TestCase):
    def test_record_lands_one_trace_row_with_appended_at(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = _ledger(directory)
            entry = DecisionTrace(ledger).record(
                "assessment.end", subject_id="run-1",
                payload=terminal(state="completed"))
            self.assertEqual(entry["event"], "decision_trace")
            self.assertEqual(entry["kind"], "assessment.end")
            self.assertEqual(entry["state"], "completed")
            self.assertEqual(entry["path"], "primary")
            self.assertGreaterEqual(entry["appended_at"], entry["happened_at"])
            self.assertEqual(set(ENVELOPE_KEYS) <= set(entry), True)
            ok, _detail = ledger.verify()
            self.assertEqual(ok, True)

    def test_payload_cannot_redefine_an_envelope_key(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = _ledger(directory)
            with self.assertRaises(TraceError):
                DecisionTrace(ledger).record("assessment.end",
                                             payload={"kind": "other"})

    def test_reader_selects_kinds_and_ignores_other_ledger_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = _ledger(directory)
            ledger.append("offer", task_id="t1", model="m")
            trace = DecisionTrace(ledger)
            trace.record("assessment.end", subject_id="run-1")
            trace.record("campaign.event", subject_id="campaign-a",
                         payload={"campaign_event": "stop"})
            only_campaign = read_trace_events(ledger, kinds=[CAMPAIGN_EVENT])
            self.assertEqual([row["kind"] for row in only_campaign],
                             [CAMPAIGN_EVENT])
            everything = read_trace_events(ledger)
            self.assertEqual(len(everything), 2)

    def test_reader_spans_the_active_file_and_retained_segments(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "ledger.jsonl")
            ledger = AutonomyLedger(path)
            DecisionTrace(ledger).record("assessment.end", subject_id="before")
            rotated = path + ".20260101T000000.000000"
            os.replace(path, rotated)
            DecisionTrace(ledger).record("assessment.end", subject_id="after")
            events = read_trace_events(ledger, kinds=["assessment.end"])
            self.assertEqual([row["subject_id"] for row in events],
                             ["before", "after"])
            self.assertEqual(len(ledger.segment_paths()), 2)

    def test_reader_accepts_an_explicit_segment_list(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = _ledger(directory)
            DecisionTrace(ledger).record("assessment.end", subject_id="run-1")
            from_list = read_trace_events([ledger.path])
            self.assertEqual([row["subject_id"] for row in from_list], ["run-1"])

    def test_reader_tolerates_an_absent_active_file(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = _ledger(directory)
            self.assertEqual(read_trace_events(ledger), [])
            self.assertEqual(ledger.segment_paths(), [])

    def test_reader_fails_closed_on_a_corrupt_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "ledger.jsonl")
            with open(path, "w", encoding="utf-8", newline=chr(10)) as handle:
                handle.write("{not json}" + chr(10))
            with self.assertRaises(TraceError):
                read_trace_events(path)

    def test_a_campaign_event_needs_a_name(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = _ledger(directory)
            with self.assertRaises(TraceError):
                DecisionTrace(ledger).campaign_event("")

    def test_audit_enabled_entry_point_fails_closed_on_an_unavailable_sink(self):
        class _Broken:
            path = os.path.join(tempfile.gettempdir(), "unused.jsonl")

            def append(self, *_args, **_kwargs):
                raise OSError("disk gone")

        with self.assertRaises(TraceSinkUnavailable):
            DecisionTrace(_Broken()).record("assessment.end", audit_enabled=True)
        # Ordinary traffic never defers: the gap is left for the reader to show.
        survived = DecisionTrace(_Broken()).record("assessment.end")
        self.assertTrue(survived["unrecorded"])


class CampaignRetentionTests(unittest.TestCase):
    def test_campaign_events_are_retained_in_the_trace_family(self):
        with tempfile.TemporaryDirectory() as directory:
            durable = _ledger(directory)
            sidecar = EventLedger(os.path.join(directory, "campaign.events.jsonl"),
                                  trace=DecisionTrace(durable))
            record_pass(sidecar, identity=_Identity(), delta=("a",),
                        campaign="campaign-a")
            record_refusal(sidecar, reason="no delta", campaign="campaign-a")
            rows = read_trace_events(durable, kinds=[CAMPAIGN_EVENT])
            self.assertEqual([row["campaign_event"] for row in rows],
                             ["pass_admitted", "pass_refused"])
            self.assertEqual([row["campaign"] for row in rows],
                             ["campaign-a", "campaign-a"])
            self.assertEqual(rows[0]["records"], 3)
            self.assertEqual(rows[1]["reason"], "no delta")
            ok, _detail = durable.verify()
            self.assertEqual(ok, True)

    def test_campaign_records_carry_a_spec_ref_and_subject(self):
        with tempfile.TemporaryDirectory() as directory:
            durable = _ledger(directory)
            trace = DecisionTrace(durable)
            trace.campaign_event("stop", campaign="campaign-b",
                                 payload={"streak": 2})
            row = read_trace_events(durable, kinds=[CAMPAIGN_EVENT])[0]
            self.assertEqual(row["spec_ref"], "campaign.event:stop")
            self.assertEqual(row["subject_id"], "campaign-b")
            self.assertEqual(row["streak"], 2)

    def test_sidecar_without_a_trace_still_records(self):
        with tempfile.TemporaryDirectory() as directory:
            sidecar = EventLedger(os.path.join(directory, "campaign.events.jsonl"))
            record_refusal(sidecar, reason="no delta", campaign="c")
            self.assertEqual(len(sidecar.read()), 1)


class WindowPinningTests(unittest.TestCase):
    def test_manifest_retains_segments_hashes_positions_and_gaps(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = _ledger(directory)
            trace = DecisionTrace(ledger)
            trace.record("campaign.event", subject_id="campaign-a",
                         payload={"campaign_event": "pass_admitted"})
            trace.record("campaign.event", subject_id="campaign-b",
                         payload={"campaign_event": "pass_admitted"})
            out = os.path.join(directory, "windows", "469.json")
            manifest = pin_window(
                ledger, brief="469", revision="frozen-2026-11-18",
                selector="campaigns named in the brief's population",
                unit_ids=["campaign-a"], out_path=out,
                coverage={"campaign.event": "enabled 2026-11-19"},
                gaps=["pass outcomes before the producer landed"])
            with open(out, encoding="utf-8") as handle:
                written = json.load(handle)
            self.assertEqual(written["brief"], "469")
            self.assertEqual(written["revision"], "frozen-2026-11-18")
            self.assertEqual(written["unit_ids"], ["campaign-a"])
            self.assertTrue(written["segments"][0]["sha256"])
            self.assertTrue(written["segments"][0]["bytes"] > 0)
            self.assertEqual([row["subject_id"]
                              for row in written["ledger_positions"]],
                             ["campaign-a"])
            self.assertTrue(written["ledger_positions"][0]["hash"])
            self.assertEqual(written["known_gaps"],
                             ["pass outcomes before the producer landed"])
            self.assertEqual(manifest["coverage"],
                             {"campaign.event": "enabled 2026-11-19"})

    def test_manifest_requires_the_window_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = _ledger(directory)
            with self.assertRaises(TraceError):
                pin_window(ledger, brief="", revision="r", selector="s",
                           unit_ids=[], out_path=os.path.join(directory, "w.json"))


if __name__ == "__main__":
    unittest.main()
