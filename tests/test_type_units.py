"""The launch mission is multi-line; a newline has to be a real Return press.

Measured 2026-11-24 while preparing the launch cold run: the mission of record
(`dispatch/robby-battery-helper/MISSION-2026-11-17.md`, 2972 bytes) is prose with
paragraph breaks, and the literal typer sent every character as Unicode U+000A,
which this composer does not break on. `type_units` is the pure rule that fixes
it, so the behaviour is testable on any host rather than only on the laptop.
"""
import unittest

from driver_core.osal import VK_RETURN, OsalError, type_units


class TypeUnitsTests(unittest.TestCase):
    def test_a_newline_becomes_a_return_press(self):
        self.assertEqual(type_units("a\nb"),
                         [("unicode", ord("a")), ("key", (VK_RETURN,)),
                          ("unicode", ord("b"))])

    def test_a_crlf_pair_is_one_return(self):
        self.assertEqual(type_units("a\r\nb"),
                         [("unicode", ord("a")), ("key", (VK_RETURN,)),
                          ("unicode", ord("b"))])

    def test_another_control_character_is_refused_before_typing(self):
        with self.assertRaisesRegex(OsalError, "control character"):
            type_units("a\tb")

    def test_plain_text_is_unchanged(self):
        self.assertEqual(type_units("sha256:02f80742cbc8"),
                         [("unicode", ord(c)) for c in "sha256:02f80742cbc8"])


if __name__ == "__main__":
    unittest.main()
