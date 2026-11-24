"""A lost desktop must be reported as one, never as "the list does not hold it".

Measured 2026-11-24 on Kalshi dispatch 7127830177: every scroll_freebuff in the run
failed with

    FreeBuff is not the foreground window; held by hwnd 1049510 pid 12304
    title 'Windows Security'

so the sidebar never moved, every census returned the same viewport, the walk
concluded the list had ended, and the run was filed as

    the project session list does not hold 'Kalshi Paper Burndown'

That sentence is true of the list and false about the cause. These tests fail
against the previous code, where scroll_by swallowed the refusal and the walk went
on to produce the misleading message.
"""
import unittest

from scripts import windows_freebuff_dispatch as dispatch

PAGE = [
    {"text": "Projects", "x": 90, "y": 250, "x1": 150},
    {"text": "B Harness", "x": 90, "y": 290, "x1": 230},
    {"text": "Lane 1", "x": 100, "y": 330, "x1": 200},
]

HELD = ("search-scroll-1: executor failed: FreeBuff is not the foreground window; "
        "held by hwnd 1049510 pid 12304 title 'Windows Security'")


class _HeldSurface(dispatch.Dispatch):
    def __init__(self):
        self.label = "Kalshi Paper Burndown"
        self.project = "Kalshi-Trader"
        self.thread = "7d4a9b14"
        self.text = dispatch.CONTINUATION
        self.output = None
        self.notes = []

        class _Audit:
            def append(_self, kind, **fields):
                self.notes.append((kind, fields))

        self.audit = _Audit()

    def act(self, step, action, params):
        raise RuntimeError(HELD)

    def frame(self, step):
        return _Frame()

    def read_roster(self, step, frame, region):
        return list(PAGE)

    def settled_roster(self, step, region, attempts=6):
        return _Frame(), list(PAGE)

    def scroll_sidebar_to_top(self, steps=8):
        return _Frame()

    def click_exact_row(self, step, frame, row):
        return row

    def scroll_by(self, step, frame, point, delta):
        return dispatch.Dispatch.scroll_by(self, step, frame, point, delta)


class _Frame:
    size = (1800, 1131)

    def crop(self, _region):
        return self

    def convert(self, _mode):
        return self

    def point(self, _table):
        return self

    def getbbox(self):
        return None


class ForegroundLostTests(unittest.TestCase):
    def test_a_lost_desktop_raises_its_own_error(self):
        surface = _HeldSurface()
        with self.assertRaises(dispatch.ForegroundLost) as caught:
            dispatch.Dispatch.scroll_by(surface, "search-scroll-1", _Frame(), [196, 850], -900)
        self.assertIn("Windows Security", str(caught.exception))

    def test_the_walk_reports_a_lost_desktop_not_a_missing_lane(self):
        surface = _HeldSurface()
        with self.assertRaises(dispatch.ForegroundLost):
            dispatch.Dispatch.walk_session_list(surface)
        messages = [str(fields.get("reason") or "") for _kind, fields in surface.notes]
        self.assertFalse(any("does not hold" in message for message in messages),
                         "a lost desktop must never be filed as a missing lane")

    def test_the_navigation_layer_does_not_swallow_it(self):
        surface = _HeldSurface()
        surface.selected_label_matches = lambda wait=None: False
        with self.assertRaises(dispatch.ForegroundLost):
            dispatch.Dispatch.navigate_by_session_list(surface)


if __name__ == "__main__":
    unittest.main()
