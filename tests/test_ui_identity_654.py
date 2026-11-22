"""#654: the served GUI renders the version and commit the server exposes.

The server half landed (identity headers + version/commit in the status
payload). These tests pin the display half: the served page carries the
identity element, the client fetches the payload that holds the values, and the
payload really does carry them at the exact head under test.
"""
import http.client
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from harness.server import make_server

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "identity-test-token"


class ServedIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="harness-identity-654-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.httpd = make_server("127.0.0.1", 0, auth_token=TOKEN,
                                 owner_token=TOKEN)
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 2)
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def _request(self, path):
        conn = http.client.HTTPConnection("127.0.0.1",
                                          self.httpd.server_address[1],
                                          timeout=5)
        try:
            conn.request("GET", path, headers={"Host": "127.0.0.1",
                                               "X-Harness-Auth": TOKEN})
            resp = conn.getresponse()
            return resp.status, resp.getheaders(), resp.read().decode("utf-8")
        finally:
            conn.close()

    def test_the_served_page_carries_the_identity_element(self):
        status, _headers, body = self._request("/")
        self.assertEqual(status, 200)
        self.assertIn('id="harness-identity"', body)

    def test_the_served_client_fetches_the_payload_that_holds_identity(self):
        status, _headers, body = self._request("/app.js")
        self.assertEqual(status, 200)
        self.assertIn("loadHarnessIdentity", body)
        self.assertIn("/api/status", body)
        self.assertIn("harness-identity", body)

    def test_the_status_payload_carries_version_and_commit(self):
        status, headers, body = self._request("/api/status")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertTrue(str(payload.get("version") or "").strip())
        self.assertTrue(str(payload.get("commit") or "").strip())
        header_map = {k.lower(): v for k, v in headers}
        self.assertEqual(header_map.get("x-harness-version"),
                         payload["version"])
        self.assertEqual(header_map.get("x-harness-commit"), payload["commit"])


class ClientRenderTests(unittest.TestCase):
    def test_the_client_render_uses_the_payload_fields(self):
        app = (ROOT / "harness" / "ui" / "app.js").read_text(encoding="utf-8")
        self.assertIn("state.version", app)
        self.assertIn("state.commit", app)
        self.assertIn("el.hidden = false", app)

    def test_the_short_commit_extracts_the_describe_suffix(self):
        # A `git describe` string (v0.5.1-200-g3f2e9eb) must yield "3f2e9eb";
        # slicing the describe prefix would render "Harness v0.5.1 (v0.5.1-)".
        app = (ROOT / "harness" / "ui" / "app.js").read_text(encoding="utf-8")
        self.assertIn(r"-g([0-9a-f]{7,40})", app)
        self.assertNotEqual(
            app.split("function shortCommit", 1)[1].split("}\n", 1)[0]
            .strip().splitlines()[-1].strip(),
            "return value.slice(0, 7);")

    def test_the_identity_is_not_hidden_by_default_in_css(self):
        css = (ROOT / "harness" / "ui" / "app.css").read_text(encoding="utf-8")
        self.assertIn(".harness-identity", css)
        self.assertNotIn("display: none", css.split(".harness-identity", 1)[1][:200])


if __name__ == "__main__":
    unittest.main()
