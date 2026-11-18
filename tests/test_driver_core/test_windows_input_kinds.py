"""#481: the native Windows input kinds, proved above the ctypes edge.

The ctypes binding cannot run on the CI that gates this change, so the tests
are layered deliberately: every *decision* the backend makes -- what counts as
a bounded target, which pixel space a rectangle is in, what happens with no
foreground window, how a key name resolves -- is exercised against injected
window and input APIs. The one real binding is exercised against a fake
``user32``, which is the part most likely to be wrong (an argument type, a
restype) and the part worth proving without a Windows host.
"""
import unittest
from unittest import mock

from driver_core import osal
from driver_core.errors import OsalError


class FakeWindowApi:
    """The window half: exact-title matches, focus, foreground handle."""

    def __init__(self, titles=("Notes",), foreground=101):
        self.titles = list(titles)
        self.foreground_handle = foreground
        self.focused = []

    def find_exact_visible(self, title):
        return [101] if title in self.titles else []

    def focus(self, hwnd, title):
        self.focused.append((hwnd, title))
        return True

    def foreground(self):
        return self.foreground_handle

    def title_of(self, hwnd):
        return self.titles[0] if self.titles else ""


class FakeInputApi:
    """The input half: geometry plus the events a backend asked for."""

    def __init__(self, scale=1.0, screen_origin=(100, 200)):
        self.scale = scale
        self.screen_origin = screen_origin
        self.calls = []

    def dpi_scale(self, hwnd):
        if isinstance(self.scale, Exception):
            raise self.scale
        return self.scale

    def client_to_screen(self, hwnd, x, y):
        self.calls.append(("map", x, y))
        return (self.screen_origin[0] + x, self.screen_origin[1] + y)

    def click(self, x, y):
        self.calls.append(("click", x, y))

    def type_text(self, text):
        self.calls.append(("type", text))

    def key(self, codes):
        self.calls.append(("key", tuple(codes)))

    def scroll(self, direction):
        self.calls.append(("scroll", direction))


def _full(window=None, sender=None):
    return osal.windows_input_backend(
        window_api=window or FakeWindowApi(),
        input_api=sender or FakeInputApi(), full=True)


def _target(rect=(10, 20, 100, 40), *, window="Notes",
            space="client-logical", schema=osal.BOUNDED_TARGET_SCHEMA):
    record = {"window": window, "rect": list(rect), "space": space}
    if schema is not None:
        record["schema"] = schema
    return record


class DefaultBuildTests(unittest.TestCase):
    def test_the_default_is_still_focus_only(self):
        backend = osal.windows_input_backend(window_api=FakeWindowApi())
        self.assertEqual(backend.supported_kinds, ("focus",))
        self.assertEqual(backend.name, osal.WINDOWS_INPUT_BACKEND_NAME)

    def test_the_full_build_names_itself_apart_and_declares_six_kinds(self):
        backend = _full()
        self.assertEqual(backend.name, osal.WINDOWS_INPUT_BACKEND_FULL_NAME)
        self.assertEqual(backend.platform, "windows")
        self.assertEqual(backend.supported_kinds, osal.INPUT_KINDS)

    def test_a_kind_outside_the_build_refuses_by_name(self):
        backend = osal.windows_input_backend(window_api=FakeWindowApi())
        ok, detail = backend("click", target=_target())
        self.assertFalse(ok)
        self.assertIn("does not support 'click'", detail)
        self.assertIn("focus", detail)

    def test_focus_still_requires_one_exact_title(self):
        backend = _full(window=FakeWindowApi(titles=()))
        ok, detail = backend("focus", target="Notes")
        self.assertFalse(ok)
        self.assertIn("found 0", detail)


class ClickTargetTests(unittest.TestCase):
    def test_a_bare_title_is_refused_as_an_aim_point(self):
        sender = FakeInputApi()
        ok, detail = _full(sender=sender)("click", target="Notes")
        self.assertFalse(ok)
        self.assertIn("bounded target", detail)
        self.assertIn("not an aim point", detail)
        self.assertEqual(sender.calls, [])

    def test_a_target_without_the_declared_schema_is_refused(self):
        ok, detail = _full()("click", target=_target(schema=None))
        self.assertFalse(ok)
        self.assertIn("bounded target", detail)

    def test_a_target_with_a_non_integer_rect_is_refused(self):
        ok, detail = _full()("click", target=_target(rect=(1, 2, "3", 4)))
        self.assertFalse(ok)
        self.assertIn("four integers", detail)

    def test_a_logical_rectangle_is_converted_by_the_window_dpi(self):
        sender = FakeInputApi(scale=1.25)
        ok, detail = _full(sender=sender)("click", target=_target())
        self.assertTrue(ok, detail)
        # centre of [10, 20, 100, 40] is (60, 40); x1.25 -> (75, 50)
        self.assertEqual(sender.calls,
                         [("map", 75, 50), ("click", 175, 250)])
        self.assertIn("client-logical", detail)
        self.assertIn("(175, 250)", detail)

    def test_a_physical_rectangle_is_not_rescaled(self):
        sender = FakeInputApi(scale=1.25)
        ok, detail = _full(sender=sender)(
            "click", target=_target(space="client-physical"))
        self.assertTrue(ok, detail)
        self.assertEqual(sender.calls,
                         [("map", 60, 40), ("click", 160, 240)])
        self.assertIn("client-physical", detail)

    def test_an_unreadable_dpi_refuses_instead_of_assuming_96(self):
        sender = FakeInputApi(scale=OsalError("no DPI for this window"))
        ok, detail = _full(sender=sender)("click", target=_target())
        self.assertFalse(ok)
        self.assertIn("no DPI", detail)
        self.assertEqual(sender.calls, [])

    def test_a_window_that_does_not_match_refuses_before_aiming(self):
        sender = FakeInputApi()
        ok, detail = _full(window=FakeWindowApi(titles=()),
                           sender=sender)("click", target=_target())
        self.assertFalse(ok)
        self.assertIn("found 0", detail)
        self.assertEqual(sender.calls, [])

    def test_an_undeclared_space_is_refused(self):
        ok, detail = _full()("click", target=_target(space="screen"))
        self.assertFalse(ok)
        self.assertIn("undeclared space", detail)

    def test_submit_uses_the_same_bounded_aim(self):
        sender = FakeInputApi()
        ok, detail = _full(sender=sender)(
            "submit", target=_target())
        self.assertTrue(ok, detail)
        self.assertEqual(sender.calls[-1], ("click", 160, 240))
        self.assertIn("submit", detail)


class TypeKeyScrollTests(unittest.TestCase):
    def test_type_refuses_with_no_foreground_window(self):
        sender = FakeInputApi()
        backend = _full(window=FakeWindowApi(foreground=None), sender=sender)
        ok, detail = backend("type", value="hello")
        self.assertFalse(ok)
        self.assertIn("needs a foreground window", detail)
        self.assertIn("input into nothing is refused", detail)
        self.assertEqual(sender.calls, [])

    def test_type_names_the_window_it_typed_into(self):
        sender = FakeInputApi()
        ok, detail = _full(sender=sender)("type", value="hello")
        self.assertTrue(ok, detail)
        self.assertEqual(sender.calls, [("type", "hello")])
        self.assertIn("'Notes'", detail)
        self.assertIn("5 characters", detail)

    def test_type_refuses_an_empty_string(self):
        ok, detail = _full()("type", value="")
        self.assertFalse(ok)
        self.assertIn("non-empty string", detail)

    def test_key_resolves_a_declared_chord(self):
        sender = FakeInputApi()
        ok, detail = _full(sender=sender)("key", value="ctrl+s")
        self.assertTrue(ok, detail)
        self.assertEqual(sender.calls, [("key", (0x11, 0x53))])

    def test_key_refuses_an_undeclared_name_with_the_table(self):
        sender = FakeInputApi()
        ok, detail = _full(sender=sender)("key", value="ctrl+banana")
        self.assertFalse(ok)
        self.assertIn("'banana' is not declared", detail)
        self.assertIn("backspace", detail)
        self.assertEqual(sender.calls, [])

    def test_scroll_performs_a_declared_direction(self):
        sender = FakeInputApi()
        backend = _full(sender=sender)
        self.assertTrue(backend("scroll", value="up")[0])
        self.assertTrue(backend("scroll", value="down")[0])
        self.assertEqual(sender.calls, [("scroll", "up"), ("scroll", "down")])

    def test_scroll_refuses_an_undeclared_direction(self):
        sender = FakeInputApi()
        ok, detail = _full(sender=sender)("scroll", value="sideways")
        self.assertFalse(ok)
        self.assertIn("scroll direction", detail)
        self.assertEqual(sender.calls, [])

    def test_scroll_refuses_with_no_foreground_window(self):
        backend = _full(window=FakeWindowApi(foreground=None))
        ok, detail = backend("scroll", value="down")
        self.assertFalse(ok)
        self.assertIn("needs a foreground window", detail)


class KeyComboParseTests(unittest.TestCase):
    def test_a_single_letter_and_digit_are_themselves(self):
        self.assertEqual(osal.parse_key_combo("a"), (ord("A"),))
        self.assertEqual(osal.parse_key_combo("7"), (ord("7"),))

    def test_named_keys_and_f_keys_resolve(self):
        self.assertEqual(osal.parse_key_combo("enter"), (0x0D,))
        self.assertEqual(osal.parse_key_combo("f12"), (0x7B,))

    def test_a_repeated_key_is_refused(self):
        with self.assertRaises(OsalError) as caught:
            osal.parse_key_combo("ctrl+ctrl")
        self.assertIn("names a key twice", str(caught.exception))

    def test_too_long_a_chord_is_refused(self):
        with self.assertRaises(OsalError) as caught:
            osal.parse_key_combo("ctrl+alt+shift+a+b")
        self.assertIn("at most", str(caught.exception))

    def test_an_empty_token_is_refused(self):
        with self.assertRaises(OsalError) as caught:
            osal.parse_key_combo("ctrl++s")
        self.assertIn("empty token", str(caught.exception))


class FakeCtypes:
    """Just enough ctypes for the binding block to declare itself."""

    c_int = int
    c_ubyte = int
    c_ulong = int
    c_long = int
    c_void_p = int
    Structure = object
    POINTER = staticmethod(lambda entry: entry)
    byref = staticmethod(lambda point: point)

    def __init__(self, user32):
        self._user32 = user32

    def WinDLL(self, name, **kwargs):
        return self._user32


class Point:
    def __init__(self):
        self.x = 0
        self.y = 0


def _sender(user32):
    binding = (FakeCtypes(user32), user32, Point)
    with mock.patch.object(osal, "platform_name", return_value="windows"):
        return osal._WindowsInputApi(bind=lambda: binding)


class WindowsInputApiTests(unittest.TestCase):
    def setUp(self):
        self.user32 = mock.MagicMock()
        self.user32.SetCursorPos.return_value = 1
        self.user32.ClientToScreen.side_effect = self._to_screen

    @staticmethod
    def _to_screen(hwnd, point):
        point.x += 10
        point.y += 20
        return 1

    def test_it_refuses_to_construct_off_windows(self):
        with mock.patch.object(osal, "platform_name", return_value="linux"):
            with self.assertRaises(OsalError) as caught:
                osal._WindowsInputApi()
        self.assertIn("does not exist", str(caught.exception))

    def test_the_binding_declares_every_entry_point(self):
        module, user32, point = osal._bind_input_events(
            ctypes_module=FakeCtypes(self.user32))
        self.assertIsInstance(module, FakeCtypes)
        self.assertIs(point, self.user32.ClientToScreen.argtypes[1])
        self.assertEqual(user32.SetCursorPos.argtypes, (int, int))
        self.assertEqual(user32.keybd_event.argtypes, (int, int, int, int))
        self.assertEqual(user32.mouse_event.argtypes,
                         (int, int, int, int, int))
        self.assertEqual(user32.ClientToScreen.argtypes, (int, point))
        self.assertEqual(user32.GetDpiForWindow.restype, int)

    def test_moving_refuses_when_windows_says_no(self):
        self.user32.SetCursorPos.return_value = 0
        with self.assertRaises(OsalError) as caught:
            _sender(self.user32).move(5, 6)
        self.assertIn("SetCursorPos refused", str(caught.exception))

    def test_a_click_moves_then_presses_and_releases(self):
        sender = _sender(self.user32)
        sender.click(11, 12)
        self.assertEqual(self.user32.SetCursorPos.call_args, mock.call(11, 12))
        self.assertEqual(
            self.user32.mouse_event.call_args_list,
            [mock.call(osal.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0),
             mock.call(osal.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)])

    def test_typing_sends_one_unicode_pair_per_character(self):
        sender = _sender(self.user32)
        sender.type_text("ab")
        self.assertEqual(
            self.user32.keybd_event.call_args_list,
            [mock.call(0, ord("a"), osal.KEYEVENTF_UNICODE, 0),
             mock.call(0, ord("a"),
                       osal.KEYEVENTF_UNICODE | osal.KEYEVENTF_KEYUP, 0),
             mock.call(0, ord("b"), osal.KEYEVENTF_UNICODE, 0),
             mock.call(0, ord("b"),
                       osal.KEYEVENTF_UNICODE | osal.KEYEVENTF_KEYUP, 0)])

    def test_a_character_outside_the_bmp_is_refused_whole(self):
        sender = _sender(self.user32)
        with self.assertRaises(OsalError) as caught:
            sender.type_text("a\U0001F600")
        self.assertIn("outside the BMP", str(caught.exception))

    def test_a_chord_releases_in_reverse(self):
        sender = _sender(self.user32)
        sender.key((0x11, 0x53))
        self.assertEqual(
            self.user32.keybd_event.call_args_list,
            [mock.call(0x11, 0, 0, 0), mock.call(0x53, 0, 0, 0),
             mock.call(0x53, 0, osal.KEYEVENTF_KEYUP, 0),
             mock.call(0x11, 0, osal.KEYEVENTF_KEYUP, 0)])

    def test_scroll_signs_the_wheel_delta(self):
        sender = _sender(self.user32)
        sender.scroll("up")
        sender.scroll("down")
        self.assertEqual(
            self.user32.mouse_event.call_args_list,
            [mock.call(osal.MOUSEEVENTF_WHEEL, 0, 0, osal.SCROLL_DELTA, 0),
             mock.call(osal.MOUSEEVENTF_WHEEL, 0, 0, -osal.SCROLL_DELTA, 0)])

    def test_dpi_scale_is_the_ratio_to_96(self):
        self.user32.GetDpiForWindow.return_value = 120
        self.assertEqual(_sender(self.user32).dpi_scale(7), 1.25)

    def test_a_refused_dpi_read_refuses_by_name(self):
        self.user32.GetDpiForWindow.return_value = 0
        with self.assertRaises(OsalError) as caught:
            _sender(self.user32).dpi_scale(7)
        self.assertIn("no scale can be derived", str(caught.exception))

    def test_client_to_screen_returns_the_mapped_point(self):
        self.assertEqual(_sender(self.user32).client_to_screen(7, 5, 6),
                         (15, 26))

    def test_a_refused_mapping_refuses_by_name(self):
        self.user32.ClientToScreen.side_effect = None
        self.user32.ClientToScreen.return_value = 0
        with self.assertRaises(OsalError) as caught:
            _sender(self.user32).client_to_screen(7, 5, 6)
        self.assertIn("ClientToScreen failed", str(caught.exception))


class WiringTests(unittest.TestCase):
    def test_a_registered_full_backend_serves_send_input(self):
        sender = FakeInputApi()
        with mock.patch.object(osal, "platform_name",
                               return_value="windows"):
            backend = osal.register_native_input_backend(
                "windows", window_api=FakeWindowApi(),
                input_api=sender, full=True)
            try:
                ok, detail = osal.send_input("click", target=_target())
            finally:
                osal.disable_input_backend("windows")
        self.assertTrue(ok, detail)
        self.assertEqual(backend.supported_kinds, osal.INPUT_KINDS)
        self.assertEqual(sender.calls[-1], ("click", 160, 240))

    def test_registration_refuses_a_platform_with_no_native_implementation(self):
        with self.assertRaises(OsalError) as caught:
            osal.register_native_input_backend("linux")
        self.assertIn("no native input backend", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
