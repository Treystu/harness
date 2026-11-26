"""Changed-line coverage for the #683 burndown batch's refusal branches.

D12 requires the lines a change touches to be executed by the suite. These
tests drive the refusal and fallback paths that the happy-path suites leave
cold: a non-preprint registry subtype, a voucher with a missing component, a
deferred request's persisted resumability, an unknown backend, a passing
local-only MCP check, and a composed drop-run chain.
"""
import unittest
from unittest import mock

from harness import citation_resolver as citations
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


if __name__ == "__main__":
    unittest.main()
