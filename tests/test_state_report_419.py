"""#419: local health, backend reachability and request state are separate.

The defect: the desktop API answered ``status=ok`` while the configured MCP
backend could not be reached, and the run list was empty, so a reader could not
tell "the request stopped" from "its status is unavailable".

These tests use the real seam the issue names:

* the **local** side is a real ``make_server`` socket answering over loopback,
* the **backend** side is the callable the server uses for its MCP reachability
  check (``doctor.check_mcp_stdio`` in production), here a probe that fails the
  way the finding reports -- an SSH connection timeout,
* the **request** side is a real lifecycle checkpoint written by
  ``LifecycleCoordinator``, which is the durable state a restarted process sees.

Nothing here asserts that a function exists; every assertion is about what a
client of ``/api/status`` and ``/api/diagnostics`` actually receives.
"""
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from harness.lifecycle import LifecycleCoordinator
from harness.server import make_server
from harness.state_report import (
    BACKEND_OK,
    BACKEND_UNREACHABLE,
    BackendMonitor,
    diagnostics_text,
    report_requests,
)

PROMPT = "Rebuild the release index from the last three tags."
TIMEOUT_ERROR = ("ssh: connect to host mcp.internal port 22: "
                 "Connection timed out")


def _request(port, path, token=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        headers = {"Host": "127.0.0.1"}
        if token:
            headers["X-Harness-Auth"] = token
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            payload = {"raw": body.decode("utf-8", "replace")}
        return resp.status, payload
    finally:
        conn.close()


class _Probe:
    """Stands in for ``doctor.check_mcp_stdio`` at the server's probe seam."""

    def __init__(self, failing=True, message=TIMEOUT_ERROR):
        self.failing = failing
        self.message = message
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.failing:
            raise OSError(self.message)
        return {"name": "mcp_stdio", "status": "OK",
                "detail": "ledger_status passed", "next": ""}


class _ServerOverCheckpoints(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.history = self.root / "chat_history"
        self.history.mkdir(parents=True)
        self.token = "state-report-token-419"

    def _checkpoint(self, session_id="sess-419", prompt=PROMPT):
        coordinator = LifecycleCoordinator(history_dir=self.history)
        coordinator.begin("chat", session_id, prompt,
                          stage="answer_generation")

    def _server(self, probe, ttl=30.0):
        httpd = make_server("127.0.0.1", 0, auth_token=self.token,
                            history_dir=self.history, backend_probe=probe,
                            backend_probe_ttl=ttl)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        def stop():
            httpd.shutdown()
            httpd.server_close()
            thread.join(2)
            httpd.ui.uninstall_event_sink()

        self.addCleanup(stop)
        return httpd, httpd.server_address[1]


class SeparateStatesTests(_ServerOverCheckpoints):
    def test_local_health_and_backend_reachability_are_reported_separately(self):
        probe = _Probe()
        _httpd, port = self._server(probe)
        self._checkpoint()
        status, payload = _request(port, "/api/status", self.token)
        self.assertEqual(status, 200)
        # The local process is answering: that is the one healthy fact.
        self.assertEqual(payload["local"]["state"], "ok")
        self.assertGreaterEqual(payload["local"]["uptime_seconds"], 0)
        self.assertTrue(payload["local"]["version"])
        # The backend is not reachable, and it says so with the reason.
        self.assertEqual(payload["backend"]["state"], BACKEND_UNREACHABLE)
        self.assertIn("timed out", payload["backend"]["error"])
        self.assertIsNone(payload["backend"]["last_ok_at"])
        self.assertTrue(payload["backend"]["next_action"])
        self.assertIn("harness.mcp", payload["backend"]["endpoint"])

    def test_an_unconfirmed_request_is_unknown_rather_than_finished(self):
        _httpd, port = self._server(_Probe())
        self._checkpoint()
        _status, payload = _request(port, "/api/status", self.token)
        run = payload["requests"][0]
        # The durable checkpoint says interrupted; the backend cannot confirm
        # anything, so the reported state must be unknown -- never completed,
        # failed or cancelled.
        self.assertEqual(run["durable_state"], "interrupted")
        self.assertEqual(run["state"], "unknown")
        self.assertNotIn(run["state"], ("completed", "failed", "cancelled"))
        self.assertFalse(run["confirmed"])
        self.assertTrue(run["reason"])
        self.assertGreater(run["last_confirmed_at"], 0)
        self.assertEqual(run["prompt"], PROMPT)

    def test_reconciliation_after_the_backend_returns_dispatches_nothing(self):
        probe = _Probe(failing=True)
        # A zero interval asks the backend on every status read, which is what
        # "reconcile when connectivity returns" means for a poller.
        httpd, port = self._server(probe, ttl=0)
        self._checkpoint()
        _status, before = _request(port, "/api/status", self.token)
        self.assertEqual(before["requests"][0]["state"], "unknown")
        probe.failing = False
        _status, after = _request(port, "/api/status", self.token)
        self.assertEqual(after["backend"]["state"], BACKEND_OK)
        self.assertEqual(after["requests"][0]["state"], "interrupted")
        self.assertTrue(after["backend"]["last_ok_at"].endswith("Z"))
        # One probe per status call, and no request was replayed or queued.
        self.assertEqual(probe.calls, 2)
        self.assertEqual(httpd.ui.runs, {})

    def test_the_probe_is_cached_within_its_interval(self):
        probe = _Probe()
        _httpd, port = self._server(probe)
        _request(port, "/api/status", self.token)
        _request(port, "/api/status", self.token)
        self.assertEqual(probe.calls, 1)

    def test_diagnostics_are_copyable_and_never_carry_the_token(self):
        probe = _Probe(message=TIMEOUT_ERROR + " [token=" + self.token + "]")
        _httpd, port = self._server(probe)
        self._checkpoint()
        _status, payload = _request(port, "/api/diagnostics", self.token)
        text = payload["text"]
        self.assertNotIn(self.token, text)
        self.assertIn("[redacted]", text)
        self.assertIn("backend: unreachable", text)
        self.assertIn("harness.mcp", text)
        self.assertIn("requests: 1", text)
        self.assertIn("last confirmed", text)
        # A copyable summary carries the numbers a reader needs to compare
        # against another machine's, not just prose.
        self.assertIn(payload["local"]["started_at"], text)


class ReportRequestsTests(unittest.TestCase):
    """The reporting rule itself, without a server in the way."""

    def _record(self, state, updated_at=1000.0):
        return {"id": "rec1", "state": state, "durable_state": state,
                "prompt": PROMPT, "updated_at": updated_at,
                "reason": "from the checkpoint"}

    def _backend(self, state):
        return {"state": state, "last_ok_at": None, "error": "timed out"}

    def test_a_down_backend_cannot_turn_a_live_request_into_a_failure(self):
        out = report_requests([self._record("interrupted")],
                              self._backend(BACKEND_UNREACHABLE))
        self.assertEqual(out[0]["state"], "unknown")
        self.assertFalse(out[0]["confirmed"])

    def test_a_terminal_checkpoint_stays_terminal_but_is_not_backend_confirmed(self):
        out = report_requests([self._record("completed")],
                              self._backend(BACKEND_UNREACHABLE))
        self.assertEqual(out[0]["state"], "completed")
        self.assertFalse(out[0]["confirmed"])
        self.assertIn("checkpoint", out[0]["reason"])

    def test_a_reachable_backend_does_not_confirm_without_request_evidence(self):
        out = report_requests([self._record("interrupted")],
                              self._backend(BACKEND_OK))
        self.assertEqual(out[0]["state"], "interrupted")
        self.assertFalse(out[0]["confirmed"])

    def test_request_specific_evidence_confirms_the_durable_state(self):
        out = report_requests([self._record("interrupted")],
                              self._backend(BACKEND_OK),
                              confirmed_ids={"rec1"})
        self.assertEqual(out[0]["state"], "interrupted")
        self.assertTrue(out[0]["confirmed"])

    def test_no_report_path_invents_a_state_that_was_never_recorded(self):
        for state in ("interrupted", "unknown", "stale", "completed", "failed"):
            out = report_requests([self._record(state)],
                                  self._backend(BACKEND_UNREACHABLE))
            self.assertEqual(out[0]["durable_state"], state)
            self.assertIn(out[0]["state"],
                          ("unknown", state))

    def test_a_doctor_failure_result_is_reported_with_its_next_step(self):
        monitor = BackendMonitor(
            probe=lambda: {"name": "mcp_stdio", "status": "MISSING",
                           "detail": "MCP initialize failed",
                           "next": "Check MCP configuration"},
            ttl_seconds=0)
        component = monitor.component()
        self.assertEqual(component["state"], BACKEND_UNREACHABLE)
        self.assertIn("MCP initialize failed", component["error"])
        self.assertIn("Check MCP configuration", component["next_action"])

    def test_a_monitor_never_reports_ok_after_a_failed_probe(self):
        monitor = BackendMonitor(probe=_Probe(failing=True), ttl_seconds=0)
        self.assertEqual(monitor.component()["state"], BACKEND_UNREACHABLE)
        self.assertEqual(monitor.component()["state"], BACKEND_UNREACHABLE)


class DiagnosticsTextTests(unittest.TestCase):
    def test_diagnostics_redacts_a_secret_and_keeps_the_timestamps(self):
        report = {
            "local": {"state": "ok", "started_at": "2026-11-18T09:00:00Z",
                      "uptime_seconds": 12.5,
                      "version": "0.1", "commit": "abcdef0"},
            "backend": {"state": BACKEND_UNREACHABLE,
                        "endpoint": "stdio: python -m harness.mcp",
                        "checked_at": "2026-11-18T09:00:12Z",
                        "last_ok_at": None,
                        "error": "ssh timed out (token=hunter2)",
                        "next_action": "check the MCP host"},
            "requests": [{"id": "rec1", "state": "unknown",
                          "durable_state": "interrupted",
                          "last_confirmed_at": "2026-11-18T08:59:00Z",
                          "prompt": "use sk-abcdef1234567890 please"}],
        }
        text = diagnostics_text(report)
        self.assertIn("local: ok", text)
        self.assertIn("backend: unreachable", text)
        self.assertIn("2026-11-18T09:00:12Z", text)
        self.assertNotIn("hunter2", text)
        self.assertNotIn("sk-abcdef1234567890", text)


if __name__ == "__main__":
    unittest.main()
