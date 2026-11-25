"""Hermetic tests for laptop driver watch operator control (CLI, server API, installer)."""

import http.client
import io
import json
import os
from pathlib import Path
import shutil
import sys
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

    def test_install_registers_logon_and_repeating_task_and_updates_driver_root(self):
        ok_proc = laptop_driver_ctl.osal.CommandResult(0, "Ready\n", "")
        with patch.object(laptop_driver_ctl, "_scheduler_enabled", return_value=True), \
             patch.object(laptop_driver_ctl.osal, "run", return_value=ok_proc) as run_mock:
            res = laptop_driver_ctl.install_laptop_watch(driver_root=self.tmp)
            self.assertTrue(res["task_registered"])
            self.assertEqual(res["task_state"], "Ready")
            self.assertTrue(res["supervisor_task_registered"])
            self.assertEqual(res["supervisor_task_state"], "Ready")
            res2 = laptop_driver_ctl.install_laptop_watch(driver_root=self.tmp + "_next")
            self.assertTrue(res2["task_registered"])
        scripts_called = "\n".join(c.args[0][-1] for c in run_mock.call_args_list)
        self.assertIn("-AtLogOn", scripts_called)
        self.assertIn("-RepetitionInterval", scripts_called)
        self.assertIn("-Minutes 1", scripts_called)
        self.assertIn("Register-ScheduledTask", scripts_called)
        self.assertIn("HarnessLaptopDriverSupervisor", scripts_called)
        self.assertIn("Disable-ScheduledTask", scripts_called)
        ctl = json.loads((self.watch_dir / "control.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(ctl["driver_root"], self.tmp + "_next")
        self.assertEqual(ctl["interval_minutes"], 1)
        self.assertEqual(laptop_driver_ctl.driver_watch_status()["consecutive_failures"], 0)
        self.assertEqual(laptop_driver_ctl.driver_watch_status()["supervisor_task_name"], "HarnessLaptopDriverSupervisor")

    def test_materialized_run_watch_py_covers_states_rotation_lock_and_alerts(self):
        res = laptop_driver_ctl.install_laptop_watch(driver_root=self.tmp)
        runner_path = Path(res["runner"])
        sup_ps1_path = Path(res["supervisor_ps1"])
        self.assertTrue(sup_ps1_path.is_file())
        self.assertTrue(Path(res["supervisor_vbs"]).is_file())
        sup_text = sup_ps1_path.read_text(encoding="utf-8")
        self.assertNotIn("{watch_dir}", sup_text)
        self.assertNotIn("{{", sup_text)
        if laptop_driver_ctl.osal.IS_WINDOWS:
            chk = laptop_driver_ctl.osal.run([
                "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                f"$e=$null; $t=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('{sup_ps1_path}', [ref]$t, [ref]$e); if ($e.Count -gt 0) {{ throw ($e | Out-String) }}"
            ], timeout=15)
            self.assertEqual(chk.returncode, 0, chk.stderr or chk.stdout)
        import importlib.util

        spec = importlib.util.spec_from_file_location("test_run_watch_mod", str(runner_path))
        mod = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {
            "HARNESS_DRIVER_WATCH_DIR": str(self.watch_dir),
            "HARNESS_DRIVER_LOG_PATH": str(self.log_path),
            "HARNESS_DRIVER_WATCH_NO_ALERT": "",
        }):
            spec.loader.exec_module(mod)
            # 1. Paused control (escalation error fallback + real report_paused=True path)
            (self.watch_dir / "control.json").write_text(
                json.dumps({"enabled": True, "paused": True, "driver_root": self.tmp}),
                encoding="utf-8",
            )
            self.assertEqual(mod.run_tick(), 0)
            paused_st = json.loads((self.watch_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(paused_st["state"], "paused")
            self.assertFalse(paused_st["paused_escalated"])

            scripts_dir = Path(self.tmp) / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            (scripts_dir / "__init__.py").write_text("", encoding="utf-8")
            (scripts_dir / "windows_freebuff_watch.py").write_text(
                "def local_control_state(): return {'paused': True}\n"
                "def report_paused(ctl): return True\n",
                encoding="utf-8",
            )
            with patch.dict(sys.modules, {k: v for k, v in sys.modules.items() if not k.startswith("scripts")}):
                for key in list(sys.modules):
                    if key == "scripts" or key.startswith("scripts."):
                        del sys.modules[key]
                self.assertEqual(mod.run_tick(), 0)
            paused_ok = json.loads((self.watch_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(paused_ok["state"], "paused")
            self.assertTrue(paused_ok["paused_escalated"])

            # 2. Stopped control
            (self.watch_dir / "control.json").write_text(
                json.dumps({"enabled": False, "paused": False, "driver_root": self.tmp}),
                encoding="utf-8",
            )
            self.assertEqual(mod.run_tick(), 0)
            self.assertEqual(json.loads((self.watch_dir / "status.json").read_text(encoding="utf-8"))["state"], "stopped")

            # 3. Missing driver_root triggers error + failure counter + rate-limited alert
            missing_root = str(Path(self.tmp) / "does-not-exist")
            (self.watch_dir / "control.json").write_text(
                json.dumps({"enabled": True, "paused": False, "driver_root": missing_root, "repo": "Treystu/harness", "dispatch_issue": 684}),
                encoding="utf-8",
            )
            fake_gh = laptop_driver_ctl.osal.CommandResult(0, "ok", "")
            with patch.object(mod.subprocess, "run", return_value=fake_gh) as sub_mock:
                self.assertEqual(mod.run_tick(), 2)
                st = json.loads((self.watch_dir / "status.json").read_text(encoding="utf-8"))
                self.assertEqual(st["state"], "error")
                self.assertEqual(st["consecutive_failures"], 1)
                self.assertTrue(st["alerted_failure"])
                self.assertTrue(sub_mock.called)

            # 4. Log rotation + active tick calling mocked scripts.windows_freebuff_watch.main()
            scripts_dir = Path(self.tmp) / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            (scripts_dir / "__init__.py").write_text("", encoding="utf-8")
            (scripts_dir / "windows_freebuff_watch.py").write_text(
                "def main():\n    print('mock watch tick')\n    return 0\n",
                encoding="utf-8",
            )
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self.log_path.write_bytes(b"x" * (mod.MAX_LOG_BYTES + 10))
            (self.watch_dir / "control.json").write_text(
                json.dumps({"enabled": True, "paused": False, "driver_root": self.tmp}),
                encoding="utf-8",
            )
            with patch.dict(sys.modules, {k: v for k, v in sys.modules.items() if not k.startswith("scripts")}):
                for key in list(sys.modules):
                    if key == "scripts" or key.startswith("scripts."):
                        del sys.modules[key]
                self.assertEqual(mod.run_tick(force=True, echo=True), 0)
            st_ok = json.loads((self.watch_dir / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(st_ok["state"], "idle_watching")
            self.assertEqual(st_ok["consecutive_failures"], 0)
            self.assertFalse(st_ok["alerted_failure"])
            self.assertTrue(self.log_path.with_suffix(".log.1").is_file())

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
