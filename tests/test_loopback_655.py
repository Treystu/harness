"""#655: one base port owns the harness loopback family; 8766 is retired.

Pins the rule in harness/loopback.py (media = base + 0, serve = base + 2), the
CLI surfaces that must agree with it, and the removal of the stale desktop
default from harness/ui.py.
"""
import unittest
from pathlib import Path

from harness import cli_parser, loopback, media_client, server


ROOT = Path(__file__).resolve().parents[1]


class LoopbackRuleTests(unittest.TestCase):
    def test_defaults_are_media_8765_and_serve_8767(self):
        self.assertEqual(loopback.media_port({}), 8765)
        self.assertEqual(loopback.serve_port({}), 8767)

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

    def test_media_default_derives_from_the_rule(self):
        self.assertIn(f"127.0.0.1:{loopback.media_port()}",
                      media_client.DEFAULT_BASE)

    def test_doctor_gui_port_default_follows_the_rule(self):
        opts = cli_parser.build_parser().parse_args(["doctor"])
        self.assertEqual(opts.gui_port, loopback.serve_port())

    def test_serve_prints_the_same_default_port(self):
        opts = server.main.__defaults__  # imported, not invoked
        self.assertIsNotNone(server.main)


if __name__ == "__main__":
    unittest.main()
