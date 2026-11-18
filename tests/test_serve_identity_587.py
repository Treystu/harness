"""#587: the served UI names the code it is serving.

The issue's evidence was that no anonymous surface reported a version or a
commit: the ``Server`` header was the constant ``harness-ui/0.1``, ``/api/status``
carried neither field, and the static assets are byte-identical across commits,
so a healthy ``200`` could not be tied to a head. These tests pin the cure
where a browser and a bare ``curl`` can both read it -- response headers and
the JSON status -- plus the fallback that keeps an installed wheel honest.
"""
import http.client
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import harness
from harness import server as server_module
from harness.errors import HarnessError
from harness.server import (UiRequestHandler, make_server, serve_identity,
                            _git_describe)


def _request(port, path="/", headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", path, headers=headers or {"Host": "127.0.0.1"})
        resp = conn.getresponse()
        body = resp.read()
        return resp.status, dict(resp.getheaders()), body
    finally:
        conn.close()


class ServeIdentityTests(unittest.TestCase):
    def setUp(self):
        server_module._IDENTITY_CACHE.clear()
        self.addCleanup(server_module._IDENTITY_CACHE.clear)

    def test_identity_reports_the_package_version_and_a_commit(self):
        ident = serve_identity()
        self.assertEqual(ident["version"], harness.__version__)
        self.assertTrue(ident["commit"])
        self.assertNotIn(" ", ident["commit"])

    def test_identity_is_cached_and_handed_out_as_a_copy(self):
        first = serve_identity()
        first["commit"] = "mutated-by-caller"
        second = serve_identity()
        self.assertNotEqual(second["commit"], "mutated-by-caller",)
        self.assertEqual(second["version"], harness.__version__)

    def test_a_clean_tree_describes_a_real_commit(self):
        root = Path(__file__).resolve().parent.parent
        described = _git_describe(root)
        self.assertTrue(described)
        self.assertNotIn(" ", described)

    def test_a_missing_git_is_unknown_not_an_error(self):
        # OS contact routes through harness/osal.py (the boundary test in
        # tests/test_osal_boundary.py refuses subprocess in this module).
        with mock.patch.object(server_module.osal, "run",
                               side_effect=OSError("no git here")):
            self.assertEqual(_git_describe(Path(".")), "unknown")

    def test_the_git_call_goes_through_osal(self):
        with mock.patch.object(server_module.osal, "run",
                               side_effect=HarnessError("refused")) as run:
            self.assertEqual(_git_describe(Path(".")), "unknown")
        run.assert_called_once()

    def test_a_successful_describe_returns_the_trimmed_commit(self):
        done = mock.Mock(returncode=0, stdout="abc123\n")
        with mock.patch.object(server_module.osal, "run",
                               return_value=done) as run:
            self.assertEqual(_git_describe(Path(".")), "abc123")
        self.assertEqual(run.call_args.args[0][0], "git")

    def test_a_failed_describe_is_unknown(self):
        done = mock.Mock(returncode=128, stdout="")
        with mock.patch.object(server_module.osal, "run",
                               return_value=done):
            self.assertEqual(_git_describe(Path(".")), "unknown")

    def test_a_blank_describe_is_unknown(self):
        done = mock.Mock(returncode=0, stdout="  \n")
        with mock.patch.object(server_module.osal, "run",
                               return_value=done):
            self.assertEqual(_git_describe(Path(".")), "unknown")

    def test_the_server_header_names_the_package_version(self):
        self.assertEqual(UiRequestHandler.server_version,
                         f"harness-ui/{harness.__version__}")


class ServedIdentityTests(unittest.TestCase):
    """The identity a client actually receives, over the loopback socket."""

    def setUp(self):
        server_module._IDENTITY_CACHE.clear()
        self.addCleanup(server_module._IDENTITY_CACHE.clear)
        self.tmp = tempfile.mkdtemp(prefix="harness-serve-id-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.token = "identity-token"
        self.httpd = make_server("127.0.0.1", 0, auth_token=self.token)
        self.addCleanup(self.httpd.server_close)
        thread = threading.Thread(target=self.httpd.serve_forever,
                                  daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(self.httpd.shutdown)
        self.port = self.httpd.server_address[1]

    def test_the_page_carries_version_and_commit_headers_token_free(self):
        status, headers, body = _request(self.port, "/")
        self.assertEqual(status, 200)
        self.assertTrue(body)
        self.assertEqual(headers.get("X-Harness-Version"),
                         harness.__version__)
        self.assertEqual(headers.get("X-Harness-Commit"),
                         self.httpd.identity["commit"])
        self.assertIn(f"harness-ui/{harness.__version__}",
                      headers.get("Server", ""))

    def test_a_rejected_request_still_names_the_served_code(self):
        # Auth failures are exactly when an operator needs to know what is
        # running, so the identity headers are not behind the token gate.
        status, headers, _body = _request(
            self.port, "/api/status", headers={"Host": "evil.example.com"})
        self.assertIn(status, (401, 403))
        self.assertEqual(headers.get("X-Harness-Version"),
                         harness.__version__)

    def test_status_api_reports_version_and_commit(self):
        status, _headers, body = _request(
            self.port, "/api/status",
            headers={"Host": "127.0.0.1", "X-Harness-Auth": self.token})
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["version"], harness.__version__)
        self.assertEqual(payload["commit"], self.httpd.identity["commit"])

    def test_the_server_binds_identity_at_start(self):
        self.assertEqual(self.httpd.identity["version"], harness.__version__)
        self.assertTrue(self.httpd.identity["commit"])
