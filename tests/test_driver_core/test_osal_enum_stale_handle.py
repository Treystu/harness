"""Hermetic tests for Win32 error 1400 handling during EnumWindows traversal."""

import unittest
from unittest import mock

from driver_core import osal
from driver_core.errors import OsalError


class _UnicodeBuffer:
    def __init__(self):
        self.value = ""


class _FakeCtypes:
    _last_error = 0

    @classmethod
    def set_last_error(cls, code):
        cls._last_error = code

    @classmethod
    def get_last_error(cls):
        return cls._last_error

    @staticmethod
    def create_unicode_buffer(_size):
        return _UnicodeBuffer()


class _VanishingWindowUser32:
    def __init__(self):
        self.titles = {
            1: "Target Window",
            2: "Vanished Length",
            3: "Vanished Text",
            4: "Target Window",
        }
        self.visible = {1, 2, 3, 4}
        self.length_errors = {}
        self.text_errors = {}
        self.visible_errors = set()

    def EnumWindows(self, proc, _param):
        for hwnd in sorted(self.titles):
            if not proc(hwnd, 0):
                return False
        return True

    def IsWindowVisible(self, hwnd):
        if hwnd in self.visible_errors:
            raise RuntimeError("injected visibility boom")
        return hwnd in self.visible

    def GetWindowTextLengthW(self, hwnd):
        if hwnd in self.length_errors:
            _FakeCtypes.set_last_error(self.length_errors[hwnd])
            return 0
        return len(self.titles[hwnd])

    def GetWindowTextW(self, hwnd, buffer, size):
        if hwnd in self.text_errors:
            _FakeCtypes.set_last_error(self.text_errors[hwnd])
            return 0
        buffer.value = self.titles[hwnd][: size - 1]
        return len(buffer.value)


class WindowsEnumStaleHandleTests(unittest.TestCase):
    def _api_with(self, user32):
        with mock.patch.object(osal, "platform_name", return_value="windows"):
            return osal._WindowsWindowApi(bind=lambda: (_FakeCtypes, user32, lambda visit: visit))

    def test_win32_error_1400_skips_vanished_handles_and_continues(self):
        user32 = _VanishingWindowUser32()
        user32.length_errors[2] = 1400
        user32.text_errors[3] = 1400
        api = self._api_with(user32)
        self.assertEqual(api.find_exact_visible("Target Window"), [1, 4])

    def test_non_1400_osal_error_still_aborts_enumeration(self):
        user32 = _VanishingWindowUser32()
        user32.length_errors[2] = 5
        api = self._api_with(user32)
        with self.assertRaisesRegex(OsalError, r"Win32 error 5"):
            api.find_exact_visible("Target Window")

    def test_non_osal_exception_still_aborts_and_wraps_cleanly(self):
        user32 = _VanishingWindowUser32()
        user32.visible_errors.add(2)
        api = self._api_with(user32)
        with self.assertRaisesRegex(OsalError, "window enumeration callback failed: injected visibility boom"):
            api.find_exact_visible("Target Window")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
