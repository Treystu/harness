"""#655: one base port owns the harness loopback family; 8766 is retired.

Pins the rule in harness/loopback.py (media = base + 0, serve = base + 2), the
CLI/doctor/server surfaces that must agree with it, and the removal of the
stale desktop default from harness/ui.py.
"""
import unittest
from pathlib import Path
from unittest.mock import patch

from harness import cli_parser, doctor, loopback, media_client, server


ROOT = Path(__file__).resolve().parents[1]


class LoopbackRuleTests(unittest.TestCase):
    def test_defaults_are_media_8765_and_serve_8767(self):
        self.assertEqual(loopback.media_port({}), 8765)
        self.assertEqual(loopback.serve_port({}), 8767)
        self.assertEqual(loopback.serve_base_url({}), "http://127.0.0.1:8767")
        self.assertEqual(loopback.media_base_url({}), "http://127.0.0.1:8765")

    def test_one_env_setting_moves_the_family(self):
        env = {"HARNESS_BASE_PORT": "9000"}
        self.assertEqual(loopback.media_port(env), 9000)
        self.assertEqual(loopback.serve_port(env), 9002)

    def test_a_bad_base_port_falls_back_to_the_documented_default(self):
        for raw in ("", "  ", "not-a-port", "0", "70000"):
            self.assertEqual(loopback.base_port({"HARNESS_BASE_PORT": raw}),
                             8765, raw)


class SurfacesAgreeTests(unittest.TestCase):
    def test_desktop_no_longer_carries_the_8766_default(self):
        source = (ROOT / "harness" / "ui.py").read_text(encoding="utf-8")
        self.assertNotIn("default=8766", source)
        self.assertIn("default=serve_port()", source)

    def test_serve_and_desktop_share_one_default(self):
        import inspect
        source = (ROOT / "harness" / "server.py").read_text(encoding="utf-8")
        self.assertIn("default=serve_port()", source)
        self.assertEqual(
            inspect.signature(server.make_server).parameters["port"].default,
            loopback.serve_port())
        self.assertEqual(server.main.__module__, "harness.server")

        captured = []

        class _DummyServer:
            def __init__(self, addr, handler):
                self.addr = addr
                self.server_address = (addr[0], 49152)
                self.daemon_threads = False
                self.ui = None
                self.identity = None

        with patch.object(server, "UiServer", side_effect=lambda addr, h: captured.append(addr) or _DummyServer(addr, h)), \
             patch.object(server, "BackendMonitor", return_value=object()), \
             patch.object(server, "serve_identity", return_value="test"):
            srv = server.make_server("127.0.0.1", port=None, auth_token="tok", owner_token="tok")
            self.assertEqual(captured, [("127.0.0.1", loopback.serve_port())])
            self.assertIsNotNone(srv)

    def test_media_default_derives_from_the_rule(self):
        self.assertIn(f"127.0.0.1:{loopback.media_port()}",
                      media_client.DEFAULT_BASE)

    def test_doctor_gui_port_default_follows_the_rule(self):
        opts = cli_parser.build_parser().parse_args(["doctor"])
        self.assertEqual(opts.gui_port, loopback.serve_port())

        seen = []
        with patch.object(doctor, "check_dns", return_value={"name": "dns", "status": "OK"}), \
             patch.object(doctor, "check_python", return_value={"name": "python", "status": "OK"}), \
             patch.object(doctor, "check_ruff", return_value={"name": "ruff", "status": "OK"}), \
             patch.object(doctor, "check_openrouter_key", return_value={"name": "key", "status": "OK"}), \
             patch.object(doctor, "check_jev_key", return_value={"name": "jev", "status": "OK"}), \
             patch.object(doctor, "check_typesafe", return_value={"name": "ts", "status": "OK"}), \
             patch.object(doctor, "check_driver", return_value={"name": "drv", "status": "OK"}), \
             patch.object(doctor, "check_gui_port", side_effect=lambda p: seen.append(p) or {"name": "gui", "status": "OK"}), \
             patch.object(doctor, "check_ledger", return_value={"name": "ledger", "status": "OK"}), \
             patch.object(doctor, "check_mcp_stdio", return_value={"name": "mcp", "status": "OK"}):
            doctor.run_doctor(type("S", (), {"ledger_path": None, "mcp_auth_token": None})())
        self.assertEqual(seen, [loopback.serve_port()])


if __name__ == "__main__":
    unittest.main()
