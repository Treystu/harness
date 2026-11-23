"""#413: the loopback driver round-trip reports what actually happened.

#413's verification probe has twice been misled by this seam rather than by
the driver:

* `POST /api/driver/step` accepted an ``action`` field and never read it, so a
  probe body carrying one looked like a vocabulary read while it ran the
  model-backed decision pipeline. That misreading filed
  `driver-vocabulary-keyless-claim-false`, which had to be withdrawn.
* A service that answered 401 was reported as "driver service returned HTTP
  401: unauthorized" through the same exception an outage uses, and the server
  route then returned 503 -- so a token mismatch (routine when two harness
  processes are up, because an undeclared token is generated per start) was
  indistinguishable from a dead service.

These tests pin the two corrections. Nothing here touches the network: the
client takes a fake opener and the route takes a fake adapter.
"""
import http.client
import io
import json
import threading
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from harness.perception_client import (
    PerceptionAdapter, PerceptionUnauthorized, PerceptionUnavailable,
)
from harness.server import make_server
from tests.test_server import _request


def _http_error(code, detail):
    return urllib.error.HTTPError(
        "http://127.0.0.1:8791/step", code, "error", {},
        io.BytesIO(json.dumps({"error": detail}).encode("utf-8")))


class PerceptionCredentialRefusalTest(unittest.TestCase):
    """The client keeps `unavailable` for outages and names a refusal."""

    def _adapter(self, outcome):
        def opener(req, timeout=None):
            raise outcome
        return PerceptionAdapter(base_url="http://127.0.0.1:8791",
                                 token="stale-token", opener=opener)

    def test_a_rejected_token_is_its_own_failure(self):
        adapter = self._adapter(_http_error(401, "unauthorized"))
        with self.assertRaises(PerceptionUnauthorized) as caught:
            adapter.health()
        error = caught.exception
        self.assertEqual(error.status, 401)
        # Existing callers catch the base class and must keep working.
        self.assertIsInstance(error, PerceptionUnavailable)
        message = str(error)
        self.assertIn("HTTP 401", message)
        self.assertIn("DRIVER_TOKEN", message)
        self.assertIn("generated per start", message)

    def test_a_forbidden_caller_is_the_same_class(self):
        adapter = self._adapter(_http_error(403, "forbidden"))
        with self.assertRaises(PerceptionUnauthorized) as caught:
            adapter.vocabulary()
        self.assertEqual(caught.exception.status, 403)

    def test_an_unreachable_service_is_not_a_credential_refusal(self):
        adapter = self._adapter(urllib.error.URLError(ConnectionRefusedError(
            111, "Connection refused")))
        with self.assertRaises(PerceptionUnavailable) as caught:
            adapter.health()
        self.assertNotIsInstance(caught.exception, PerceptionUnauthorized)
        self.assertIn("unreachable", str(caught.exception))

    def test_a_server_side_failure_is_not_a_credential_refusal(self):
        adapter = self._adapter(_http_error(500, "boom"))
        with self.assertRaises(PerceptionUnavailable) as caught:
            adapter.schemas()
        self.assertNotIsInstance(caught.exception, PerceptionUnauthorized)
        self.assertIn("HTTP 500", str(caught.exception))


class DriverStepRouteTruthTest(unittest.TestCase):
    """`/api/driver/step` refuses the inert field and maps 401 honestly."""

    def setUp(self):
        self.httpd = make_server("127.0.0.1", 0, auth_token=None)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=60)

    def _post(self, path, body):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        try:
            return _request(conn, "POST", path, body=body)
        finally:
            conn.close()

    @patch("harness.server.UiRequestHandler._get_driver_adapter")
    def test_the_inert_action_field_is_refused_by_name(self, mock_get_adapter):
        adapter = MagicMock()
        mock_get_adapter.return_value = adapter

        status, data = self._post("/api/driver/step", {
            "target": "http://127.0.0.1:8797/",
            "schema": "dom",
            "action": "vocabulary",
        })

        self.assertEqual(status, 400)
        self.assertIn("not a step field", data["error"])
        self.assertIn("/api/driver/vocabulary", data["error"])
        # The refusal happens before any step runs, which is the whole point:
        # the old route ran the model-backed decision for this body.
        adapter.step.assert_not_called()

    @patch("harness.server.UiRequestHandler._get_driver_adapter")
    def test_a_credential_refusal_is_401_with_its_own_kind(self, mock_get_adapter):
        adapter = MagicMock()
        adapter.step.side_effect = PerceptionUnauthorized(
            "driver service rejected the request with HTTP 401: unauthorized",
            status=401)
        mock_get_adapter.return_value = adapter

        status, data = self._post("/api/driver/step", {
            "target": "http://127.0.0.1:8797/", "schema": "dom"})

        self.assertEqual(status, 401)
        self.assertEqual(data["error_kind"], "driver_token_mismatch")
        self.assertIn("HTTP 401", data["error"])

    @patch("harness.server.UiRequestHandler._get_driver_adapter")
    def test_an_outage_is_still_503(self, mock_get_adapter):
        adapter = MagicMock()
        adapter.step.side_effect = PerceptionUnavailable(
            "driver service unreachable at http://127.0.0.1:8791 "
            "(Connection refused). Start it with: driver-core serve")
        mock_get_adapter.return_value = adapter

        status, data = self._post("/api/driver/step", {
            "target": "file-manager", "schema": "screen"})

        self.assertEqual(status, 503)
        self.assertNotIn("error_kind", data)

    @patch("harness.server.UiRequestHandler._get_driver_adapter")
    def test_a_missing_schema_is_still_400(self, mock_get_adapter):
        adapter = MagicMock()
        adapter.step.side_effect = PerceptionUnavailable(
            "schema is required; declare one of ['cli', 'dom', 'gui', 'mcp', "
            "'screen']")
        mock_get_adapter.return_value = adapter

        status, data = self._post("/api/driver/step", {"target": "file-manager"})

        self.assertEqual(status, 400)
        self.assertIn("schema is required", data["error"])


if __name__ == "__main__":
    unittest.main()
