"""Capture/describe backend registration (#480 BR1).

The perception bridge needs the same explicit registration surface the input
side already has (``driver_core.osal.register_input_backend``): a non-desktop
driver observes the owner display through a backend that lives outside
``driver_core``. These tests pin the contract hermetically -- no screen, no
display server, no platform image tool:

* a registered backend answers before the declared native reader, and the
  one fit rule still owns the pixels;
* a plugin bug arrives as a named refusal, never as an exception thrown out
  of a screen observation mid-step;
* a backend that cannot describe refuses by name instead of an empty screen;
* withdrawing the backend hands observation back to the native path.
"""
import unittest
from unittest import mock

from driver_core import osal


PNG = "/tmp/shot.png"


def _backend(capture=None, describe=None, *, platform="windows",
             name="windows-bridge"):
    def default_capture():
        return PNG, ""

    return osal.capture_backend(
        capture=capture or default_capture, describe=describe,
        name=name, platform=platform)


class CaptureBackendRegistrationTests(unittest.TestCase):
    def setUp(self):
        for platform in osal.SUPPORTED:
            osal.disable_capture_backend(platform)
            self.addCleanup(osal.disable_capture_backend, platform)

    def _platform(self, name="windows"):
        return mock.patch.object(osal, "platform_name", return_value=name)

    def test_registered_backend_answers_before_the_native_reader(self):
        osal.register_capture_backend("windows", _backend())
        with self._platform(), \
                mock.patch.object(osal, "_capture_windows",
                                  side_effect=AssertionError("native ran")):
            path, detail = osal.capture_screen(max_side=None)
        self.assertEqual(path, PNG)
        self.assertEqual(detail, "")

    def test_registered_backend_is_fitted_by_the_one_fit_rule(self):
        osal.register_capture_backend("windows", _backend())
        with self._platform(), \
                mock.patch.object(osal, "fit_image",
                                  return_value=("/tmp/fitted.png", "fitted")) \
                as fit:
            path, detail = osal.capture_screen(max_side=1234)
        self.assertEqual(path, "/tmp/fitted.png")
        self.assertEqual(detail, "")
        fit.assert_called_once_with(PNG, max_side=1234)

    def test_backend_failure_refuses_without_raising(self):
        def boom():
            raise RuntimeError("bridge down")

        osal.register_capture_backend("windows",
                                      _backend(capture=boom))
        with self._platform():
            path, detail = osal.capture_screen(max_side=None)
        self.assertIsNone(path)
        self.assertEqual(
            detail, "capture backend 'windows-bridge' failed: bridge down")

    def test_backend_named_refusal_propagates_unchanged(self):
        def refuse():
            raise osal.OsalError("the hand reports the session is locked")

        osal.register_capture_backend("windows", _backend(capture=refuse))
        with self._platform():
            with self.assertRaises(osal.OsalError) as caught:
                osal.capture_screen(max_side=None)
        self.assertIn("locked", str(caught.exception))

    def test_non_path_result_refuses_by_name(self):
        osal.register_capture_backend(
            "windows", _backend(capture=lambda: (b"raw-bytes", "")))
        with self._platform():
            path, detail = osal.capture_screen(max_side=None)
        self.assertIsNone(path)
        self.assertIn("returned bytes instead of a path", detail)

    def test_non_string_detail_is_coerced(self):
        osal.register_capture_backend(
            "windows", _backend(capture=lambda: (PNG, 7)))
        with self._platform():
            path, detail = osal.capture_screen(max_side=None)
        self.assertEqual(path, PNG)
        self.assertEqual(detail, "7")

    def test_registered_describe_answers_before_the_native_reader(self):
        fields = {"window_title": "Bridged Window"}
        osal.register_capture_backend(
            "windows", _backend(describe=lambda: (fields, "")))
        with self._platform(), \
                mock.patch.object(osal, "_describe_windows",
                                  side_effect=AssertionError("native ran")):
            got, detail = osal.describe_screen()
        self.assertEqual(got, fields)
        self.assertEqual(detail, "")

    def test_describe_failure_refuses_without_raising(self):
        def boom():
            raise RuntimeError("describe bridge down")

        osal.register_capture_backend("windows", _backend(describe=boom))
        with self._platform():
            fields, detail = osal.describe_screen()
        self.assertIsNone(fields)
        self.assertEqual(
            detail, "capture backend 'windows-bridge' failed: "
                    "describe bridge down")

    def test_describe_named_refusal_propagates_unchanged(self):
        def refuse():
            raise osal.OsalError("the hand reports the session is locked")

        osal.register_capture_backend("windows", _backend(describe=refuse))
        with self._platform():
            with self.assertRaises(osal.OsalError) as caught:
                osal.describe_screen()
        self.assertIn("locked", str(caught.exception))

    def test_describe_returning_non_dict_refuses(self):
        osal.register_capture_backend(
            "windows", _backend(describe=lambda: ("a title", "")))
        with self._platform():
            fields, detail = osal.describe_screen()
        self.assertIsNone(fields)
        self.assertIn("returned str instead of a field dict", detail)

    def test_capture_only_backend_refuses_to_describe_by_name(self):
        osal.register_capture_backend("windows", _backend())
        with self._platform():
            fields, detail = osal.describe_screen()
        self.assertIsNone(fields)
        self.assertIn("does not describe the screen", detail)

    def test_disable_restores_the_native_path(self):
        registered = osal.register_capture_backend("windows", _backend())
        withdrawn = osal.disable_capture_backend("windows")
        self.assertIs(withdrawn, registered)
        self.assertIsNone(osal.disable_capture_backend("windows"))
        with self._platform(), \
                mock.patch.object(osal, "_capture_windows",
                                  return_value=(PNG, "native")):
            path, detail = osal.capture_screen(max_side=None)
        self.assertEqual((path, detail), (PNG, "native"))

    def test_registry_is_per_platform(self):
        osal.register_capture_backend(
            "linux", _backend(platform="linux", name="linux-bridge"))
        self.assertIn("linux", osal.capture_backends())
        self.assertNotIn("windows", osal.capture_backends())

    def test_registered_record_is_immutable(self):
        record = _backend()
        with self.assertRaises(AttributeError):
            record.name = "renamed"
        self.assertEqual(record.supported_kinds, ("capture",))
        self.assertEqual(record.platform, "windows")

    def test_describing_record_declares_both_kinds(self):
        record = _backend(describe=lambda: ({}, ""))
        self.assertEqual(record.supported_kinds, osal.CAPTURE_KINDS)

    def test_registration_refuses_an_undeclared_platform(self):
        with self.assertRaises(osal.OsalError):
            osal.register_capture_backend("freebsd", _backend())

    def test_registration_refuses_an_unbuilt_backend(self):
        with self.assertRaises(osal.OsalError) as caught:
            osal.register_capture_backend("windows", lambda: (PNG, ""))
        self.assertIn("capture_backend()", str(caught.exception))

    def test_registration_refuses_a_platform_mismatch(self):
        with self.assertRaises(osal.OsalError) as caught:
            osal.register_capture_backend("linux", _backend())
        self.assertIn("declares platform 'windows'", str(caught.exception))

    def test_builder_refuses_non_callables(self):
        with self.assertRaises(osal.OsalError):
            osal.capture_backend(capture=None, platform="windows")
        with self.assertRaises(osal.OsalError):
            osal.capture_backend(capture=lambda: (PNG, ""), describe="words",
                                 platform="windows")

    def test_builder_refuses_a_blank_name(self):
        with self.assertRaises(osal.OsalError):
            osal.capture_backend(capture=lambda: (PNG, ""), name="   ",
                                 platform="windows")

    def test_builder_derives_a_platform_name(self):
        record = osal.capture_backend(capture=lambda: (PNG, ""),
                                      platform="linux")
        self.assertEqual(record.name, "linux-native-capture")

    def test_native_record_covers_the_declared_platforms(self):
        windows = osal.native_capture_backend("windows")
        linux = osal.native_capture_backend("linux")
        darwin = osal.native_capture_backend("darwin")
        self.assertEqual(windows.supported_kinds, osal.CAPTURE_KINDS)
        self.assertEqual(linux.supported_kinds, osal.CAPTURE_KINDS)
        self.assertEqual(darwin.supported_kinds, ("capture",))
        self.assertIsNone(osal.native_capture_backend("freebsd"))
        self.assertEqual(darwin.name, "darwin-native-capture")

    def test_registering_the_native_reader_changes_only_the_name(self):
        osal.register_native_capture_backend("linux")
        self.assertIn("linux", osal.capture_backends())
        with self._platform("linux"), \
                mock.patch.object(osal, "_capture_linux",
                                  return_value=(PNG, "native linux")), \
                mock.patch.object(osal, "_describe_linux",
                                  return_value=({"window_title": "T"}, "")):
            path, detail = osal.capture_screen(max_side=None)
            fields, why = osal.describe_screen()
        self.assertEqual((path, detail), (PNG, "native linux"))
        self.assertEqual((fields, why), ({"window_title": "T"}, ""))

    def test_native_registration_refuses_an_undeclared_platform(self):
        with self.assertRaises(osal.OsalError):
            osal.register_native_capture_backend("freebsd")

    def test_unsupported_platform_still_refuses_without_a_backend(self):
        with self._platform("freebsd"):
            path, detail = osal.capture_screen(max_side=None)
            fields, why = osal.describe_screen()
        self.assertIsNone(path)
        self.assertIn("not supported on freebsd", detail)
        self.assertIsNone(fields)
        self.assertIn("platform gap", why)


if __name__ == "__main__":
    unittest.main()
