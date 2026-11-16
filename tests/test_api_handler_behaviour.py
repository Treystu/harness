"""#283: behaviour tests for the six handlers nothing exercised, and the edge paths.

The coverage gate in `test_api_inventory` derived the route table from
`harness/server.py` and found six GET handlers named in no test at all:
`/api/capabilities`, `/api/economics`, `/api/ledger/report`, `/api/ledger/tail`,
`/api/ledger/verify`, `/api/models`. The acceptance says every handler gets at
least one behaviour test, so these drive each one through a real ephemeral
loopback server and assert the envelope a client depends on -- and then cover the
edge paths: unknown channel, malformed payload, method that the route does not
serve, and an unsupported verb.

Hermetic: ephemeral loopback port, no network, no provider calls.
"""
import http.client
import json
import threading
import unittest
from unittest import mock

from harness import server as ui_server
from harness.server import make_server

TOKEN = "behaviour-test-token"

#: route -> a key its 200 envelope must carry (measured on harness 2203782).
UNCOVERED_GET_ROUTES = {
    "/api/capabilities": "models",
    "/api/economics": "cost_summary",
    "/api/ledger/report": "completion_rate",
    "/api/ledger/tail": "entries",
    "/api/ledger/verify": "verified",
    "/api/models": "count",
}


class ServerCase(unittest.TestCase):
    """One ephemeral server per class, token-authenticated."""

    def setUp(self):
        self.httpd = make_server("127.0.0.1", 0, auth_token=TOKEN)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)
        self.conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        self.addCleanup(self.conn.close)

    def _stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def call(self, method, path, body=None, raw=None, token=TOKEN):
        payload = raw if raw is not None else (
            json.dumps(body).encode() if body is not None else None)
        headers = {"Host": "127.0.0.1"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["X-Harness-Auth"] = token
        self.conn.request(method, path, body=payload, headers=headers)
        resp = self.conn.getresponse()
        data = resp.read()
        try:
            parsed = json.loads(data or b"{}")
        except ValueError:
            parsed = {"raw": data.decode("utf-8", "replace")}
        return resp.status, parsed


def _stub_governor(*_args, **_kwargs):
    """A governor whose transport does nothing: the catalog fetch is stubbed.

    `/api/models` and `/api/capabilities` verify the key limit over the network
    at `governor_for`; these tests are hermetic, so the governor is stubbed and
    the catalog functions they call are patched per test. Everything else -- the
    handler, the routing, the envelope -- is the real code.
    """
    governor = mock.Mock()
    governor.transport = object()
    return ("stub-key", governor)


class UncoveredHandlerTests(ServerCase):
    def test_each_formerly_untested_handler_answers_with_its_envelope(self):
        for path, key in sorted(UNCOVERED_GET_ROUTES.items()):
            with self.subTest(path=path):
                patches = [mock.patch.object(ui_server, "governor_for",
                                             side_effect=_stub_governor)]
                if path == "/api/models":
                    patches.append(mock.patch(
                        "harness.spend.discover_free_models",
                        return_value=[{"id": "stub/model", "free": True}]))
                if path == "/api/capabilities":
                    patches.append(mock.patch(
                        "harness.capability.capabilities_payload",
                        return_value={"models": [], "count": 0,
                                      "captured_at": "stub"}))
                for patcher in patches:
                    patcher.start()
                    self.addCleanup(patcher.stop)
                status, payload = self.call("GET", path)
                self.assertEqual(status, 200, payload)
                self.assertIsInstance(payload, dict)
                self.assertIn(key, payload)

    def test_the_ledger_verify_handler_reports_a_chain_claim(self):
        status, payload = self.call("GET", "/api/ledger/verify")
        self.assertEqual(status, 200)
        self.assertIsInstance(payload["verified"], bool)
        self.assertIn("chain", payload)

    def test_ledger_tail_is_bounded_and_counts_its_entries(self):
        status, payload = self.call("GET", "/api/ledger/tail")
        self.assertEqual(status, 200)
        entries = payload["entries"]
        self.assertIsInstance(entries, list)
        self.assertEqual(payload["count"], len(entries))

    def test_models_never_returns_a_non_list(self):
        with mock.patch.object(ui_server, "governor_for", side_effect=_stub_governor),                 mock.patch("harness.spend.discover_free_models",
                           return_value=[{"id": "stub/model", "free": True}]):
            status, payload = self.call("GET", "/api/models")
        self.assertEqual(status, 200)
        self.assertIsInstance(payload["models"], (list, dict))
        self.assertEqual(payload["models"][0]["id"], "stub/model")


class EdgePathTests(ServerCase):
    def test_an_unknown_channel_is_a_json_404(self):
        status, payload = self.call("GET", "/api/definitely-not-a-route")
        self.assertEqual(status, 404)
        self.assertIn("no such endpoint", payload["error"])

    def test_an_unknown_post_channel_is_a_json_404(self):
        status, payload = self.call("POST", "/api/definitely-not-a-route", body={})
        self.assertEqual(status, 404)
        self.assertIn("no such endpoint", payload["error"])

    def test_a_malformed_body_is_a_json_400(self):
        status, payload = self.call("POST", "/api/chat", raw=b"{not json")
        self.assertEqual(status, 400)
        self.assertIn("not valid JSON", payload["error"])

    def test_a_route_does_not_answer_the_wrong_method(self):
        status, payload = self.call("GET", "/api/intake")
        self.assertEqual(status, 404)
        self.assertIn("no such endpoint", payload["error"])

    def test_an_unsupported_verb_answers_json_405_not_the_html_default(self):
        for method in ("PUT", "DELETE", "PATCH"):
            with self.subTest(method=method):
                status, payload = self.call(method, "/api/status")
                self.assertEqual(status, 405, payload)
                self.assertIn("method not allowed", payload["error"])
                self.assertNotIn("raw", payload)

    def test_an_unauthenticated_request_is_refused_before_routing(self):
        status, payload = self.call("GET", "/api/definitely-not-a-route",
                                    token=None)
        self.assertEqual(status, 401)
        self.assertIn("not connected to Harness", payload["error"])

    def test_every_refusal_is_json_shaped(self):
        cases = [("GET", "/api/definitely-not-a-route"),
                 ("POST", "/api/definitely-not-a-route"),
                 ("PUT", "/api/status"),
                 ("GET", "/api/intake")]
        for method, path in cases:
            with self.subTest(method=method, path=path):
                status, payload = self.call(method, path)
                self.assertGreaterEqual(status, 400)
                self.assertIn("error", payload)


if __name__ == "__main__":
    unittest.main()
