"""Changed-line coverage for the #683 burndown batch's refusal branches.

D12 requires the lines a change touches to be executed by the suite. These
tests drive the refusal and fallback paths that the happy-path suites leave
cold: a non-preprint registry subtype, a voucher with a missing component, a
deferred request's persisted resumability, an unknown backend, a passing
local-only MCP check, and a composed drop-run chain.
"""
import os
import tempfile
import unittest
from unittest import mock

from harness import citation_resolver as citations
from harness.ledger import AutonomyLedger
from harness import ledger_compaction as compaction
from harness import public_share as share
from harness import run_recovery
from harness import server as ui_server
from harness import state_report
from harness.errors import HarnessError

DOI = "10.1234/abc"
ISSUER_KEY = b"issuer-key"
MODEL = "deepseek/deepseek-v4.1-flash"
ROUND = "2026-10"


class CitationSubtypeTests(unittest.TestCase):
    def test_a_preprint_subtype_on_a_registry_record_is_a_preprint(self):
        payload = {"message": {"DOI": DOI, "type": "journal-article",
                               "subtype": "preprint"}}
        self.assertEqual(citations.crossref_metadata(payload)["version"],
                         "preprint")


class VoucherArgumentTests(unittest.TestCase):
    def test_a_voucher_refuses_an_empty_component(self):
        boss = share.EligibilityIssuer(ISSUER_KEY)
        credential = boss.credential("profile")
        with self.assertRaises(HarnessError) as caught:
            boss.voucher("", credential=credential, model=MODEL,
                         round_id=ROUND)
        self.assertIn("non-empty token", str(caught.exception))


class RecoveryResumabilityTests(unittest.TestCase):
    def test_a_deferred_request_honors_its_persisted_resumability(self):
        base = {"status": "deferred", "stage": "review"}
        self.assertTrue(run_recovery.classify(
            dict(base, data={"resumable": True}),
            age_seconds=5)["resumable"])
        self.assertFalse(run_recovery.classify(
            dict(base, data={"resumable": False}),
            age_seconds=5)["resumable"])


class BackendUnknownTests(unittest.TestCase):
    def test_an_unknown_probe_reports_the_backend_as_unknown(self):
        monitor = state_report.BackendMonitor(
            probe=lambda: {"name": "mcp_stdio", "status": "UNKNOWN",
                           "detail": "local startup only",
                           "next": "point the backend at the transport"},
            ttl_seconds=0)
        component = monitor.component()
        self.assertEqual(component["state"], state_report.BACKEND_UNKNOWN)
        self.assertIn("transport", component["next_action"])


class DefaultBackendProbeTests(unittest.TestCase):
    def test_a_passing_local_check_reports_unknown_not_ok(self):
        settings = type("S", (), {"mcp_auth_token": "token-value"})()
        with mock.patch("harness.doctor.check_mcp_stdio",
                        return_value={"status": "OK", "detail": "started"
                                      }) as check, \
                mock.patch("harness.server.load_settings",
                           return_value=settings):
            # Building the probe inside the patch matters: it binds the
            # doctor's check into the closure when it is created.
            check_result = ui_server._default_backend_probe()()
        check.assert_called_once_with("token-value")
        self.assertEqual(check_result["status"], "UNKNOWN")
        self.assertIn("not contacted", check_result["detail"])

    def test_unreadable_settings_still_probe_without_a_token(self):
        with mock.patch("harness.server.load_settings",
                        side_effect=HarnessError("broken")), \
                mock.patch("harness.doctor.check_mcp_stdio",
                           return_value={"status": "MISSING"}) as check:
            ui_server._default_backend_probe()()
        check.assert_called_once_with(None)


class GapChainTests(unittest.TestCase):
    def test_consecutive_signed_runs_cross_a_gap(self):
        runs = [
            {"first_seq": 9, "last_seq": 10, "predecessor_hash": "x",
             "terminal_hash": "y"},
            {"first_seq": 2, "last_seq": 3, "predecessor_hash": "wrong",
             "terminal_hash": "y"},
            {"first_seq": 2, "last_seq": 3, "predecessor_hash": "h1",
             "terminal_hash": "h2"},
            {"first_seq": 4, "last_seq": 5, "predecessor_hash": "h2",
             "terminal_hash": "h3"},
        ]
        self.assertTrue(compaction.crosses_gap(
            1, "h1", {"seq": 6, "prev_hash": "h3"}, runs))

    def test_a_broken_chain_does_not_cross_a_gap(self):
        runs = [
            {"first_seq": 2, "last_seq": 3, "predecessor_hash": "h1",
             "terminal_hash": "h2"},
            {"first_seq": 4, "last_seq": 5, "predecessor_hash": "hX",
             "terminal_hash": "h3"},
        ]
        self.assertFalse(compaction.crosses_gap(
            1, "h1", {"seq": 6, "prev_hash": "h3"}, runs))


class TerminalFailureDenominatorTests(unittest.TestCase):
    """Row 44: a failed apply run is a task, not a missing observation."""

    def _rows(self, *extra):
        base = [{"event": "model_result", "model": MODEL, "cost": 0.002},
                {"event": "complete", "model": MODEL, "status": "ok"}]
        return base + [dict(row, model=MODEL) for row in extra]

    def test_an_abort_row_counts_in_the_task_denominator(self):
        stats = share.derive_stats(self._rows(
            {"event": "abort", "reason": "verify rounds exhausted"}), MODEL)
        self.assertEqual(stats["tasks"], 2)
        self.assertEqual(stats["successes"], 1)

    def test_an_abort_without_a_reason_is_not_evidence(self):
        stats = share.derive_stats(self._rows({"event": "abort"}), MODEL)
        self.assertEqual(stats["tasks"], 1)


class QueuedReportPeriodTests(unittest.TestCase):
    """Row 45: a retry may not send a report from an older consent period."""

    def test_a_retry_discards_a_report_from_an_older_consent_period(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = share.ShareProfile(tmp)
            old = share._hex16(profile.enable()["period"])
            profile.disable()
            profile.enable()
            sent = []
            profile.transport = sent.append
            profile.queue({"protocol": "x", "proof": {
                "consent_period": old}})
            result = profile.upload_pending()
            self.assertEqual(result, {"sent": 0, "dropped": 1,
                                      "retained": 0,
                                      "reason": "the consent period changed"})
            self.assertEqual(sent, [])
            self.assertEqual(profile.pending(), [])

    def test_a_retry_sends_a_report_from_the_current_consent_period(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = share.ShareProfile(tmp)
            current = share._hex16(profile.enable()["period"])
            sent = []
            profile.transport = sent.append
            profile.queue({"protocol": "x", "proof": {
                "consent_period": current}})
            result = profile.upload_pending()
            self.assertEqual((result["sent"], result["dropped"]), (1, 0))
            self.assertEqual(len(sent), 1)


class CitationPinRefreshTests(unittest.TestCase):
    """Row 38: another instance's citation must pin this one before a sweep."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "ledger.jsonl")

    def test_a_sweep_sees_a_citation_the_instance_did_not_append(self):
        writer = AutonomyLedger(self.path)
        older = AutonomyLedger(self.path)
        row = writer.append("verdict", note="cited evidence")
        writer.pin_citation(row["seq"], row["hash"], source="gate:test")
        self.assertNotIn((row["seq"], row["hash"]), older.citation_pins)
        older.sweep_compaction(segments=[])
        self.assertIn((row["seq"], row["hash"]), older.citation_pins)

    def test_an_append_rebases_citation_pins_from_another_instance(self):
        writer = AutonomyLedger(self.path)
        older = AutonomyLedger(self.path)
        row = writer.append("verdict", note="cited evidence")
        writer.pin_citation(row["seq"], row["hash"], source="gate:test")
        older.append("verdict", note="later work")
        self.assertIn((row["seq"], row["hash"]), older.citation_pins)


if __name__ == "__main__":
    unittest.main()
