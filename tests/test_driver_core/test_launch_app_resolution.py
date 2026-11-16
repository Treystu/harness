"""#482: a launch that started nothing must not report a hand-off.

``cmd /c start "" <value>`` exits 0 when the program does not exist, and its
error is written to a console the launcher discards. Before this preflight, a
declared value that was not installed came back as a *successful* launch and
surfaced two seconds later as a vision-verification failure -- the wrong
verdict, from the wrong subsystem, after a paid capture.

These tests pin the refusal instead, hermetically: the launcher is never
constructed for a value that resolves to nothing, the refusal names the
declared value and the application, and the paths that used to work (an
absolute existing program, a bare name found on PATH) are handed on unchanged.
"""
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from driver_core import osal


class _Process:
    def __init__(self):
        self.pid = 5252
        self.killed = False

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def popen(argv, **kwargs):
            self.calls.append(argv)
            return _Process()

        self._popen = mock.patch.object(subprocess, "Popen", popen)
        self._popen.start()
        self.addCleanup(self._popen.stop)
        self._platform = mock.patch.object(osal, "platform_name",
                                           return_value="windows")
        self._platform.start()
        self.addCleanup(self._platform.stop)

    def _which(self, found):
        patcher = mock.patch.object(osal.shutil, "which",
                                    lambda name: found(name) if callable(found)
                                    else found)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_bare_name_missing_from_path_is_refused_and_starts_nothing(self):
        self._which(None)
        output, detail = osal.launch_app("freebuff", "FreeBuff.exe")
        self.assertIsNone(output)
        self.assertIn("FreeBuff.exe", detail)
        self.assertIn("freebuff", detail)
        self.assertIn("nothing was started", detail)
        self.assertEqual(self.calls, [])

    def test_a_bare_name_found_on_path_is_handed_on_unchanged(self):
        self._which("C:\\Program Files\\FreeBuff\\FreeBuff.exe")
        output, detail = osal.launch_app("freebuff", "FreeBuff.exe")
        self.assertEqual(detail, "")
        self.assertEqual(output["app"], "freebuff")
        self.assertEqual(self.calls[0], ["cmd", "/c", "start", "", "FreeBuff.exe"])

    def test_an_absolute_path_that_does_not_exist_is_refused(self):
        self._which("unused")
        missing = os.path.join(tempfile.gettempdir(), "not-installed-482.exe")
        output, detail = osal.launch_app("freebuff", missing)
        self.assertIsNone(output)
        # The refusal names the value as repr'd, so a Windows path keeps its
        # separators legible rather than being re-interpreted as escapes.
        self.assertIn(repr(missing), detail)
        self.assertIn("absolute path that does not exist", detail)
        self.assertEqual(self.calls, [])

    def test_an_absolute_path_that_exists_is_handed_on(self):
        self._which("unused")
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as handle:
            path = handle.name
        self.addCleanup(os.remove, path)
        output, detail = osal.launch_app("notepad", path)
        self.assertEqual(detail, "")
        self.assertEqual(self.calls[0], ["cmd", "/c", "start", "", path])
        self.assertEqual(output["pid"], 5252)

    def test_the_allowlist_values_are_what_is_checked(self):
        # Not the logical name: the declared value is the program, and the
        # refusal quotes that value rather than the label it was filed under.
        seen = []
        self._which(lambda name: seen.append(name))
        osal.launch_app("notepad", "notepad.exe")
        self.assertEqual(seen, ["notepad.exe"])

    def test_other_platforms_are_untouched(self):
        with mock.patch.object(osal, "platform_name", return_value="darwin"):
            which = mock.patch.object(osal.shutil, "which",
                                      side_effect=AssertionError("not consulted"))
            which.start()
            self.addCleanup(which.stop)
            output, detail = osal.launch_app("notepad", "TextEdit")
        self.assertEqual(detail, "")
        self.assertEqual(self.calls[0], ["open", "-a", "TextEdit"])
        self.assertEqual(output["app"], "notepad")

    def test_a_launcher_that_does_not_hand_off_is_still_killed(self):
        self._which("C:\\Windows\\notepad.exe")

        class Hang(_Process):
            def wait(self, timeout=None):
                raise subprocess.TimeoutExpired(["launcher"], timeout)

        hang = Hang()
        with mock.patch.object(subprocess, "Popen", lambda argv, **k: hang):
            output, detail = osal.launch_app("notepad", "notepad.exe")
        self.assertIsNone(output)
        self.assertTrue(hang.killed)
        self.assertIn("did not hand off", detail)


if __name__ == "__main__":
    unittest.main()
