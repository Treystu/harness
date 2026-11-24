"""#574: the UI server owns its request log on disk.

Pins the three things the issue found missing: a process-owned destination
(not a launcher's stderr), a startup marker that identifies the writer so an
old file cannot pass for the live process, and a request record for every
response -- including the keepalive probe that only ever produced a 200.
"""
import http.client
import io
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from harness import ui as ui_module
from harness.server import UiRequestHandler, UiServer, main, make_server
from harness.serve_log import ServeLog, default_log_path, open_serve_log

ui_main = ui_module.main


def _get(port, path="/"):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", path, headers={"Host": "127.0.0.1"})
        resp = conn.getresponse()
        resp.read()
        return resp.status
    finally:
        conn.close()


class ServeLogTests(unittest.TestCase):
    def test_startup_marker_names_the_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "logs" / "serve.log"
            log = open_serve_log(path, pid=4242, port=8765)
            try:
                first = path.read_text(encoding="utf-8").splitlines()[0]
            finally:
                log.close()
        self.assertIn("=== harness serve start ", first)
        self.assertIn("pid=4242", first)
        self.assertIn("port=8765", first)
        self.assertIn(str(path.name), first)

    def test_each_process_appends_its_own_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "serve.log"
            with open_serve_log(path, pid=1, port=8000):
                pass
            with open_serve_log(path, pid=2, port=8001):
                pass
            marks = [ln for ln in path.read_text(encoding="utf-8").splitlines()
                     if ln.startswith("=== harness serve start ")]
        self.assertEqual(len(marks), 2)
        self.assertIn("pid=1", marks[0])
        self.assertIn("pid=2", marks[1])

    def test_write_stamps_utc_and_flushes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "serve.log"
            log = ServeLog(path)
            try:
                log.write('[ui] "GET / HTTP/1.1" 200 -\n')
                on_disk = path.read_text(encoding="utf-8")
            finally:
                log.close()
        self.assertRegex(on_disk, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z ")
        self.assertIn('[ui] "GET / HTTP/1.1" 200 -', on_disk)

    def test_default_path_is_under_the_harness_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get("HARNESS_HOME")
            os.environ["HARNESS_HOME"] = tmp
            try:
                resolved = default_log_path()
            finally:
                if old is None:
                    os.environ.pop("HARNESS_HOME", None)
                else:
                    os.environ["HARNESS_HOME"] = old
        self.assertEqual(resolved, Path(tmp) / "logs" / "serve.log")


class ServerServeLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="harness-serve-log-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _server(self):
        path = Path(self.tmp) / "logs" / "serve.log"
        httpd = make_server("127.0.0.1", 0, log_path=path)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return httpd, path

    def _wait_for(self, path, marker, count=1):
        for _ in range(60):
            text = path.read_text(encoding="utf-8") if path.exists() else ""
            if text.count(marker) >= count:
                return text
            threading.Event().wait(0.05)
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def test_requests_land_in_the_file_alongside_the_marker(self):
        httpd, path = self._server()
        status = _get(httpd.server_address[1], "/")
        text = self._wait_for(path, 'GET / HTTP/1.1" 200')
        self.assertEqual(status, 200)
        self.assertIn('"GET / HTTP/1.1" 200', text)
        marker_at = text.index("=== harness serve start ")
        request_at = text.index('"GET / HTTP/1.1" 200')
        self.assertLess(marker_at, request_at)
        self.assertIn("pid=", text.splitlines()[0])

    def test_a_probe_leaves_a_record(self):
        # The keepalive probe is a plain GET /; before #574 it left only a 200.
        httpd, path = self._server()
        port = httpd.server_address[1]
        self.assertEqual(_get(port, "/"), 200)
        self.assertEqual(_get(port, "/"), 200)
        text = self._wait_for(path, '"GET / HTTP/1.1" 200', count=2)
        self.assertEqual(text.count('"GET / HTTP/1.1" 200'), 2)

    def test_a_token_in_the_url_is_redacted_in_the_file(self):
        httpd, path = self._server()
        _get(httpd.server_address[1], "/?token=super-secret-value&page=1")
        text = self._wait_for(path, "page=1")
        self.assertIn("token=REDACTED", text)
        self.assertNotIn("super-secret-value", text)

    def test_a_key_in_the_url_is_redacted_in_the_file(self):
        # #653: the file sink covers the credential family, not just token=.
        httpd, path = self._server()
        _get(httpd.server_address[1], "/?api_key=sk-live-abcdef&page=1")
        text = self._wait_for(path, "page=1")
        self.assertIn("api_key=REDACTED", text)
        self.assertNotIn("sk-live-abcdef", text)

    def test_no_path_means_no_file_and_close_is_safe(self):
        httpd = make_server("127.0.0.1", 0)
        self.assertIsNone(httpd.serve_log)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        self.assertEqual(_get(httpd.server_address[1], "/"), 200)

    def test_server_close_closes_the_log(self):
        httpd, _path = self._server()
        log = httpd.serve_log
        self.assertFalse(log._fh.closed)
        httpd.shutdown()
        httpd.server_close()
        self.assertTrue(log._fh.closed)


class CommandWiringTests(unittest.TestCase):
    """The commands pass a log path, so the product -- not the launcher -- writes."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="harness-serve-log-cmd-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = Path(self.tmp) / "logs" / "serve.log"

    def test_handler_writes_the_redacted_line_to_the_attached_log(self):
        log = open_serve_log(self.path, pid=7, port=1)
        self.addCleanup(log.close)
        handler = UiRequestHandler.__new__(UiRequestHandler)
        handler.server = type("S", (), {"serve_log": log})()
        with mock.patch("sys.stderr", new=io.StringIO()):
            handler.log_message("%s", 'GET /?token=abc&x=1" 200')
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("token=REDACTED", text)
        self.assertNotIn("token=abc", text)

    def test_each_credential_parameter_name_is_redacted_on_both_sinks(self):
        # #653: a credential under any of these names travelled in plaintext
        # while only token= was scrubbed; the value must not reach stderr or
        # the on-disk sink, and the name must stay readable.
        names = ("token", "key", "api_key", "apikey", "api-key", "auth",
                 "access_token", "refresh_token", "password", "passwd",
                 "secret", "client_secret", "session_id", "TOKEN", "Api_Key")
        log = open_serve_log(self.path, pid=7, port=1)
        self.addCleanup(log.close)
        handler = UiRequestHandler.__new__(UiRequestHandler)
        handler.server = type("S", (), {"serve_log": log})()
        err = io.StringIO()
        with mock.patch("sys.stderr", new=err):
            for index, name in enumerate(names):
                handler.log_message(
                    "%s", 'GET /?%s=secretvalue%d&page=1" 200' % (name, index))
        for sink in (self.path.read_text(encoding="utf-8"), err.getvalue()):
            for index, name in enumerate(names):
                self.assertIn("%s=REDACTED" % name, sink)
                self.assertNotIn("secretvalue%d" % index, sink)
            # The scrubber replaces values, not the rest of the request line.
            self.assertIn("page=1", sink)
            self.assertIn("GET /?", sink)

    def test_a_parameter_that_only_ends_in_a_credential_name_keeps_its_value(self):
        # The word boundary is what keeps ordinary parameters out of the net.
        log = open_serve_log(self.path, pid=7, port=1)
        self.addCleanup(log.close)
        handler = UiRequestHandler.__new__(UiRequestHandler)
        handler.server = type("S", (), {"serve_log": log})()
        with mock.patch("sys.stderr", new=io.StringIO()):
            handler.log_message(
                "%s", 'GET /?monkey=banana&keys=visible HTTP/1.1" 200')
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("monkey=banana", text)
        self.assertIn("keys=visible", text)
        self.assertNotIn("REDACTED", text)

    def test_handler_without_a_server_still_logs_to_stderr(self):
        handler = UiRequestHandler.__new__(UiRequestHandler)
        stream = io.StringIO()
        with mock.patch("sys.stderr", new=stream):
            handler.log_message("%s", "standalone line")
        self.assertIn("[ui] standalone line", stream.getvalue())

    def test_serve_command_opens_its_own_log_and_says_where(self):
        stream = io.StringIO()
        with mock.patch.object(UiServer, "serve_forever", side_effect=KeyboardInterrupt), \
                mock.patch("harness.server.load_or_create_ui_token", return_value="tok"), \
                mock.patch("harness.server.write_ui_handoff", return_value="/tmp/handoff"), \
                mock.patch("sys.stderr", new=stream):
            main(["--port", "0", "--log-file", str(self.path)])
        self.assertIn("=== harness serve start ", self.path.read_text(encoding="utf-8"))
        self.assertIn("[OK] request log:", stream.getvalue())

    def test_desktop_command_opens_its_own_log(self):
        class _Thread:
            def __init__(self, *a, **k):
                pass

            def start(self):
                return None

            def join(self, *a, **k):
                return None

        with mock.patch("harness.ui.load_or_create_ui_token", return_value="tok"), \
                mock.patch("harness.ui.write_ui_handoff", return_value="/tmp/handoff"), \
                mock.patch("harness.ui.threading.Thread", _Thread), \
                mock.patch("harness.ui.osal.open_url"), \
                mock.patch("sys.stderr", new=io.StringIO()):
            ui_main(["--port", "0", "--browser", "--log-file", str(self.path)])
        self.assertIn("=== harness serve start ", self.path.read_text(encoding="utf-8"))
