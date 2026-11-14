"""The CLI version surface and the package entry point (#328, #529)."""
import contextlib
import io
import sys
import unittest
from unittest import mock

from harness import __version__, cli


class VersionSurfaceTests(unittest.TestCase):
    """``harness --version`` / ``-v`` / ``version`` all answer, exit 0."""

    def _answer(self, argv):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), \
                self.assertRaises(SystemExit) as ctx:
            cli.main(argv)
        return ctx.exception.code, stdout.getvalue().strip()

    def test_version_flags_print_the_package_version(self):
        for argv in (["--version"], ["-v"], ["version"]):
            code, out = self._answer(argv)
            self.assertEqual(code, 0, argv)
            self.assertEqual(out, f"harness {__version__}", argv)

    def test_version_is_documented_in_help(self):
        from harness.cli_parser import build_parser

        help_text = build_parser().format_help()
        self.assertIn("--version", help_text)


class PackageEntryPointTests(unittest.TestCase):
    """``python -m harness`` runs the same CLI, not a missing-__main__ error."""

    def test_package_main_prints_the_version(self):
        import runpy

        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", ["harness", "--version"]), \
                contextlib.redirect_stdout(stdout), \
                self.assertRaises(SystemExit) as ctx:
            runpy.run_module("harness", run_name="__main__")
        self.assertEqual(ctx.exception.code, 0)
        self.assertEqual(stdout.getvalue().strip(), f"harness {__version__}")


if __name__ == "__main__":
    unittest.main()
