"""Hermetic tests for laptop driver watch operator control (CLI, server API, installer)."""

import http.client
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

from harness import cli, laptop_driver_ctl
from harness.errors import HarnessError
from harness.server import make_server
from tests.test_server import _request


class LaptopDriverWatchControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="harness-watch-ctl-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.watch_dir = Path(self.tmp) / "driver-watch"
        self.log_path = Path(self.tmp) / "logs" / "driver-watch.log"
        env_patch = patch.dict(os.environ, {
            "HARNESS_DRIVER_WATCH_DIR": str(self.watch_dir),
            "HARNESS_DRIVER_LOG_PATH": str(self.log_path),
            "HARNESS_DRIVER_WATCH_NO_SCHEDULER": "1",
        })
        env_patch.start()
        self.addCleanup(env_patch.stop)

    def test_status_and_state_transitions_start_pause_resume_stop(self):
        initial = laptop_driver_ctl.driver_watch_status()
        self.assertEqual(initial["state"], "stopped")
        self.assertFalse(initial["enabled"])

        started = laptop_driver_ctl.driver_watch_control("start", driver_root=self.tmp)
        self.assertEqual(started["state"], "running")
        self.assertTrue(started["enabled"])
        self.assertFalse(started["paused"])
        self.assertEqual(started["driver_root"], self.tmp)

        paused = laptop_driver_ctl.driver_watch_control("pause")
        self.assertEqual(paused["state"], "paused")
        self.assertTrue(paused["paused"])

        resumed = laptop_driver_ctl.driver_watch_control("resume")
        self.assertEqual(resumed["state"], "running")
        self.assertFalse(resumed["paused"])

        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text("line1\nline2\n", encoding="utf-8")
        checked = laptop_driver_ctl.driver_watch_control("status")
        self.assertEqual(checked["state"], "running")
        run_once = laptop_driver_ctl.driver_watch_control("run-once")
        self.assertEqual(run_once["state"], "running")
        stopped = laptop_driver_ctl.driver_watch_control("stop")
        self.assertEqual(stopped["state"], "stopped")
        self.assertEqual(stopped["log_tail"], ["line1", "line2"])

    def test_default_paths_and_disabled_scheduler_fallback(self):
        with patch.dict(os.environ, {"HARNESS_DRIVER_WATCH_DIR": "", "HARNESS_DRIVER_LOG_PATH": "", "HARNESS_DRIVER_WATCH_NO_SCHEDULER": ""}):
            self.assertEqual(laptop_driver_ctl.watch_dir(), Path.home() / ".harness" / "driver-watch")
            self.assertEqual(laptop_driver_ctl.log_path(), Path.home() / ".harness" / "logs" / "driver-watch.log")
            self.assertEqual(laptop_driver_ctl._scheduler_enabled(), laptop_driver_ctl.osal.IS_WINDOWS)
        self.assertEqual(laptop_driver_ctl._run_ps("Get-Date"), "")

    def test_unreadable_control_file_and_invalid_action_fail_closed(self):
        self.watch_dir.mkdir(parents=True, exist_ok=True)
        (self.watch_dir / "control.json").write_bytes(
            b'\xef\xbb\xbf{"enabled": true, "paused": false}\n'
        )
        bom_status = laptop_driver_ctl.driver_watch_status()
        self.assertEqual(bom_status["state"], "running")

        (self.watch_dir / "control.json").write_text("{bad json", encoding="utf-8")
        st = laptop_driver_ctl.driver_watch_status()
        self.assertEqual(st["state"], "stopped")
        with self.assertRaisesRegex(HarnessError, "unsupported driver-watch action"):
            laptop_driver_ctl.driver_watch_control("bogus")

    def test_install_materializes_standalone_wrappers_and_cli_runs_without_key(self):
        out = io.StringIO()
        with patch("sys.stdout", out):
            rc = cli.main(["driver-watch", "install", "--driver-root", self.tmp, "--json"])
        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertTrue(Path(payload["runner"]).is_file())
        self.assertTrue(Path(payload["vbs"]).is_file())
        self.assertTrue(Path(payload["ps1"]).is_file())
        self.assertTrue(Path(payload["cmd"]).is_file())
        self.assertIn("watch-hidden.vbs", Path(payload["vbs"]).read_text(encoding="utf-8"))

        out2 = io.StringIO()
        with patch("sys.stdout", out2):
            rc2 = laptop_driver_ctl.run_cli(["status"])
        self.assertEqual(rc2, 0)
        self.assertIn("driver-watch state=", out2.getvalue())

    def test_windows_scheduler_paths_run_hidden_and_handle_errors(self):
        ok_proc = laptop_driver_ctl.osal.CommandResult(0, "Ready\n", "")
        with patch.object(laptop_driver_ctl, "_scheduler_enabled", return_value=True), \
             patch.object(laptop_driver_ctl.osal, "run", return_value=ok_proc) as run_mock:
            self.assertEqual(laptop_driver_ctl._task_state("HarnessLaptopDriverWatch"), "Ready")
            for act in ("start", "stop", "run-once"):
                laptop_driver_ctl._set_task_state(act)
        cmd = run_mock.call_args.args[0]
        self.assertIn("-WindowStyle", cmd)
        self.assertIn("Hidden", cmd)

        bad_proc = laptop_driver_ctl.osal.CommandResult(1, "", "Access is denied")
        with patch.object(laptop_driver_ctl, "_scheduler_enabled", return_value=True), \
             patch.object(laptop_driver_ctl.osal, "run", return_value=bad_proc):
            with self.assertRaisesRegex(HarnessError, "scheduled task command failed"):
                laptop_driver_ctl._run_ps("Get-Date")

    def test_server_watch_endpoints_require_auth_when_configured_and_control_state(self):
        httpd = make_server("127.0.0.1", 0, auth_token="secret-tok")
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close(), thread.join(timeout=10)))

        def call(method, path, body=None, token=None):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
            try:
                headers = {"Authorization": f"Bearer {token}"} if token else {}
                return _request(conn, method, path, body=body, headers=headers)
            finally:
                conn.close()

        code, _ = call("GET", "/api/driver/watch/status")
        self.assertEqual(code, 401)

        code, data = call("GET", "/api/driver/watch/status", token="secret-tok")
        self.assertEqual(code, 200)
        self.assertEqual(data["state"], "stopped")

        code, data = call("POST", "/api/driver/watch/control", {"action": "start"}, token="secret-tok")
        self.assertEqual(code, 200)
        self.assertEqual(data["state"], "running")

        code, err = call("POST", "/api/driver/watch/control", {"action": "invalid"}, token="secret-tok")
        self.assertEqual(code, 400)
        self.assertIn("unsupported driver-watch action", err["error"])


if __name__ == "__main__":
    unittest.main()
