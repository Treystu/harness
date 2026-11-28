"""#683 rows 15-19 and 31: server-side cache, identity, logging, recovery.

Each test pins the behaviour the finding described at the cited path, with no
network: the handlers, the cache, the git boundary and the recovery listing are
all exercised directly.
"""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from harness import server as srv


class SnapshotCacheTests(unittest.TestCase):
    """#683 finding 16: superseded snapshot rows must not accumulate."""

    def test_superseded_snapshot_fingerprints_are_evicted(self):
        ui = srv.UiState()
        for index in range(6):
            ui.cached(("site_snapshot", "ledger.jsonl", index, index),
                      lambda index=index: index)
        snapshot_keys = [key for key in ui._api_cache
                         if isinstance(key, tuple) and key[0] == "site_snapshot"]
        self.assertEqual(len(snapshot_keys), 1)
        self.assertEqual(ui._api_cache[snapshot_keys[0]][1], 5)

    def test_other_endpoints_keep_their_entries(self):
        ui = srv.UiState()
        ui.cached("ledger_verify", lambda: "ok")
        ui.cached(("site_snapshot", "a", 1, 1), lambda: "snap")
        ui.cached(("site_snapshot", "a", 2, 2), lambda: "snap2")
        self.assertIn("ledger_verify", ui._api_cache)

    def test_expired_entries_are_dropped_on_insert(self):
        ui = srv.UiState()
        ui.cached("spend", lambda: 1, now=1000.0)
        ui.cached("other", lambda: 2, now=1000.0 + ui.CACHE_TTL + 1)
        self.assertNotIn("spend", ui._api_cache)

    def test_a_fresh_entry_is_served_without_rebuilding(self):
        ui = srv.UiState()
        calls = []
        ui.cached("k", lambda: calls.append(1) or "v", now=1000.0)
        self.assertEqual(ui.cached("k", lambda: calls.append(2),
                                   now=1000.0), "v")
        self.assertEqual(calls, [1])


class LedgerFingerprintTests(unittest.TestCase):
    """#683 finding 15: every file verification reads is in the key."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="ledger-fp-")
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "ledger.jsonl")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{}\n")
        self.segment = self.path + ".20260101T000000.000000"
        with open(self.segment, "w", encoding="utf-8") as handle:
            handle.write("a\n")
        self.settings = SimpleNamespace(ledger_path=self.path)

    def test_the_active_file_and_its_segments_are_both_fingerprinted(self):
        fingerprint = srv._ledger_fingerprint(self.settings)
        self.assertEqual(len(fingerprint), 2)
        self.assertEqual(fingerprint[1][0], self.path)

    def test_a_changed_segment_changes_the_fingerprint(self):
        first = srv._ledger_fingerprint(self.settings)
        with open(self.segment, "a", encoding="utf-8") as handle:
            handle.write("b\n")
        second = srv._ledger_fingerprint(self.settings)
        self.assertNotEqual(first, second)

    def test_the_snapshot_key_moves_when_only_a_segment_moves(self):
        first = srv._ledger_fingerprint(self.settings)
        with open(self.segment, "a", encoding="utf-8") as handle:
            handle.write("c\n")
        self.assertNotEqual(first, srv._ledger_fingerprint(self.settings))


class LedgerFingerprintFallbackTests(unittest.TestCase):
    """A ledger that cannot be read still keys its own path."""

    def _missing(self, name):
        return os.path.join(tempfile.gettempdir(), f"{name}-{os.getpid()}.jsonl")

    def test_a_missing_ledger_file_still_keys_its_path(self):
        path = self._missing("absent-ledger")
        self.assertFalse(os.path.exists(path))
        fingerprint = srv._ledger_fingerprint(
            SimpleNamespace(ledger_path=path))
        # No segment to enumerate, so the active path is the whole key.
        self.assertEqual(fingerprint, (path, None, None))

    def test_a_ledger_that_cannot_be_opened_falls_back_to_the_active_path(self):
        path = self._missing("unopenable-ledger")
        with mock.patch.object(srv, "ledger_for",
                               side_effect=srv.HarnessError("unreadable")):
            fingerprint = srv._ledger_fingerprint(
                SimpleNamespace(ledger_path=path))
        self.assertEqual(fingerprint, ((path, None, None),))


class LogSinkFailureTests(unittest.TestCase):
    """#683 finding 18: a failing log sink must not kill the response."""

    class _FailingSink:
        def write(self, line):
            raise OSError(28, "No space left on device")

        def close(self):
            pass

    def _handler(self):
        handler = srv.UiRequestHandler.__new__(srv.UiRequestHandler)
        handler.server = SimpleNamespace(serve_log=self._FailingSink())
        return handler

    def test_a_failing_sink_is_reported_once_and_never_raises(self):
        handler = self._handler()
        messages = []
        with mock.patch.object(srv.sys, "stderr",
                               new=SimpleNamespace(write=messages.append)):
            handler.log_message("GET %s", "/")
            handler.log_message("GET %s", "/again")
        self.assertTrue(handler._log_degraded)
        self.assertIn("request logging disabled", "".join(messages))
        self.assertEqual(len(messages), 2)

    def test_a_stderr_that_also_fails_still_disables_logging_once(self):
        handler = self._handler()

        class _Dead:
            def write(self, line):
                raise OSError(9, "bad file descriptor")

        with mock.patch.object(srv.sys, "stderr", new=_Dead()):
            handler.log_message("GET %s", "/")
            handler.log_message("GET %s", "/again")
        self.assertTrue(handler._log_degraded)

    def test_the_response_still_goes_out_with_a_failing_sink(self):
        import http.client
        import threading

        httpd = srv.make_server("127.0.0.1", 0, auth_token="t")
        self.addCleanup(httpd.server_close)
        httpd.serve_log = self._FailingSink()
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port,
                                          timeout=5)
        try:
            conn.request("GET", "/", headers={"Host": "127.0.0.1"})
            response = conn.getresponse()
            response.read()
            self.assertEqual(response.status, 200)
        finally:
            conn.close()


class LiveRecoveryTests(unittest.TestCase):
    """#683 finding 31: an in-flight request is not a recovered one."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="recovery-")
        self.addCleanup(self._tmp.cleanup)
        checkpoint_dir = Path(self._tmp.name) / "chat_checkpoints"
        checkpoint_dir.mkdir(parents=True)
        (checkpoint_dir / "req-live.json").write_text(json.dumps({
            "schema": "harness-lifecycle-v1", "status": "running",
            "lane": "chat", "session_id": "sess-live",
            "request_id": "req-live", "stage": "route",
            "original_request": "do the thing",
            "updated_at": time.time(),
        }), encoding="utf-8")

    def test_a_live_request_is_excluded_from_recovery_until_it_ends(self):
        ui = srv.UiState(history_dir=self._tmp.name)
        self.assertEqual([item["request_id"]
                          for item in ui.recovered_requests()], ["req-live"])
        # The id only counts while this server is running a request.
        ui.runs["run-1"] = {"status": "running"}
        ui._on_event({"status": "running", "request_id": "req-live", "seq": 1})
        self.assertEqual(ui.recovered_requests(), [])
        ui.runs["run-1"]["status"] = "done"
        ui._on_event({"status": "complete", "request_id": "req-live", "seq": 2})
        self.assertEqual(len(ui.recovered_requests()), 1)

    def test_a_checkpoint_from_a_stale_lifecycle_stays_visible(self):
        # A lifecycle that only wrote durable state must not be mistaken for
        # a live run (the state-report fixtures do exactly this).
        ui = srv.UiState(history_dir=self._tmp.name)
        ui._on_event({"status": "running", "request_id": "req-live", "seq": 1})
        self.assertEqual(len(ui.recovered_requests()), 1)
        ui._on_event({"status": "complete", "request_id": "req-live", "seq": 2})
        self.assertEqual(len(ui.recovered_requests()), 1)


if __name__ == "__main__":
    unittest.main()
