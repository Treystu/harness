"""#653: the serve log scrubs the whole credential-parameter family.

The old scrubber matched only ``token=``, so a credential arriving as ``key=``,
``api_key=``, ``auth=``, ``access_token=`` or ``password=`` reached both sinks
(stderr and the #574 on-disk serve log) in plaintext. These tests drive each
enumerated name through a real request line and assert that no value reaches
either sink, that the name survives, and that the rest of the query does too.
"""
import http.client
import io
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from harness.server import (UiRequestHandler, _CREDENTIAL_PARAMS,
                            _TOKEN_IN_LOG_RE, make_server)
from harness.serve_log import open_serve_log

SECRET = "s3cr3t-value-653"


def _get(port, path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", path, headers={"Host": "127.0.0.1"})
        resp = conn.getresponse()
        resp.read()
        return resp.status
    finally:
        conn.close()


class ScrubPatternTests(unittest.TestCase):
    def test_the_family_is_enumerated(self):
        for name in ("token", "key", "api_key", "auth", "access_token",
                     "password"):
            self.assertIn(name, _CREDENTIAL_PARAMS, name)

    def test_every_family_name_loses_its_value_and_keeps_its_name(self):
        for name in _CREDENTIAL_PARAMS:
            line = f'GET /?{name}={SECRET}&page=1 HTTP/1.1'
            scrubbed = _TOKEN_IN_LOG_RE.sub(r"\1REDACTED", line)
            self.assertNotIn(SECRET, scrubbed, name)
            self.assertIn(f"{name}=REDACTED", scrubbed, name)
            self.assertIn("page=1", scrubbed, name)

    def test_names_are_matched_case_insensitively(self):
        line = f"GET /?API_KEY={SECRET} HTTP/1.1"
        scrubbed = _TOKEN_IN_LOG_RE.sub(r"\1REDACTED", line)
        self.assertNotIn(SECRET, scrubbed)
        self.assertIn("API_KEY=REDACTED", scrubbed)

    def test_a_longer_name_is_not_matched_as_its_suffix(self):
        # api_key= must not leave "api_key=" half-scrubbed by the `key` arm.
        line = f"GET /?api_key={SECRET} HTTP/1.1"
        self.assertIn("api_key=REDACTED", _TOKEN_IN_LOG_RE.sub(r"\1REDACTED", line))

    def test_a_name_without_an_equals_sign_is_untouched(self):
        line = "GET /?author=treystu HTTP/1.1"
        self.assertEqual(_TOKEN_IN_LOG_RE.sub(r"\1REDACTED", line), line)


class BothSinksTests(unittest.TestCase):
    """The one owner (log_message) covers stderr and the file together."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="harness-scrub-653-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = Path(self.tmp) / "logs" / "serve.log"

    def test_each_family_name_is_redacted_on_both_sinks(self):
        log = open_serve_log(self.path, pid=653, port=1)
        self.addCleanup(log.close)
        handler = UiRequestHandler.__new__(UiRequestHandler)
        handler.server = type("S", (), {"serve_log": log})()
        stream = io.StringIO()
        for name in _CREDENTIAL_PARAMS:
            with mock.patch("sys.stderr", new=stream):
                handler.log_message(
                    "%s", f'GET /?{name}={SECRET}-{name}&x=1 HTTP/1.1" 200')
            on_disk = self.path.read_text(encoding="utf-8")
            in_stream = stream.getvalue()
            self.assertNotIn(SECRET, on_disk, name)
            self.assertNotIn(SECRET, in_stream, name)
            self.assertIn(f"{name}=REDACTED", on_disk, name)
            self.assertIn(f"{name}=REDACTED", in_stream, name)


class LiveRequestTests(unittest.TestCase):
    """A real request through the server leaves no value on either sink."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="harness-scrub-live-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = Path(self.tmp) / "serve.log"

    def _server(self):
        httpd = make_server("127.0.0.1", 0, log_path=self.path)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return httpd

    def _wait_for(self, needle):
        for _ in range(80):
            text = (self.path.read_text(encoding="utf-8")
                    if self.path.exists() else "")
            if needle in text:
                return text
            threading.Event().wait(0.05)
        return self.path.read_text(encoding="utf-8") if self.path.exists() else ""

    def test_a_key_request_is_scrubbed_in_the_file(self):
        httpd = self._server()
        status = _get(httpd.server_address[1], f"/?api_key={SECRET}&page=7")
        text = self._wait_for("page=7")
        self.assertEqual(status, 200)
        self.assertIn("api_key=REDACTED", text)
        self.assertNotIn(SECRET, text)


if __name__ == "__main__":
    unittest.main()
