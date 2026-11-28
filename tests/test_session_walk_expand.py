"""The session-list walk must reach lanes under headings past its first page.

Reproduced from dispatch 7127392246 (Kalshi Paper Burndown), whose own trace shows
three separate refusals before the lane was ever tried:

1. `session-list-expand-1: 'Show more' matched 2 settled rows` - the sidebar has
   one section control per project, the single-row click could not choose, and the
   exception ended the whole walk on page one, above `B Kalshi-Trader`.
2. `narrow-walk: the search field holds text this query did not write
   ('Kalshi Paper Burndow')` - a one-glyph OCR slip on the run's own query was
   treated as foreign text.
3. `identify-6-settled` censused `B Kalshi-Trader, Kalshi Paper Burndown` and the
   route walk then skipped that exact, project-scoped row.

Each test here fails against the code as it stood before those cures. The walk is
exercised through its real method bodies with a surface that answers like the
measured app does (two section controls, the target row only on page two).
"""
import unittest

from scripts import windows_freebuff_dispatch as dispatch

LABEL = "Kalshi Paper Burndown"
PROJECT = "Kalshi-Trader"

PAGE_ONE = [
    {"text": "Projects", "x": 90, "y": 250, "x1": 150},
    {"text": "B Harness", "x": 90, "y": 290, "x1": 230},
    {"text": "Lane 1", "x": 100, "y": 330, "x1": 200},
    {"text": "Show more", "x": 100, "y": 370, "x1": 200},
    {"text": "B SCMessenger", "x": 90, "y": 405, "x1": 250},
    {"text": "SCMessenger", "x": 100, "y": 445, "x1": 250},
    {"text": "Show more", "x": 100, "y": 485, "x1": 200},
]

PAGE_TWO = [
    {"text": "B Kalshi-Trader", "x": 90, "y": 250, "x1": 250},
    {"text": "Kalshi Paper Burndown", "x": 100, "y": 290, "x1": 330},
    {"text": "Ra Kalshi Paper Rotation ar", "x": 100, "y": 330, "x1": 330},
]


class _WalkSurface(dispatch.Dispatch):
    """A surface that answers exactly like the measured run, without a desktop."""

    def __init__(self, pages):
        self.label = LABEL
        self.project = PROJECT
        self.thread = "7d4a9b14"
        self.text = dispatch.CONTINUATION
        self.output = None
        self.pages = pages
        self.page = 0
        self.clicks = []
        self.notes = []

        class _Audit:
            def append(_self, kind, **fields):
                self.notes.append((kind, fields))

        self.audit = _Audit()

    # --- the census surface -------------------------------------------------
    def scroll_sidebar_to_top(self, steps=8):
        self.page = 0
        return self.frame("frame-top")

    def locate_exact_text(self, *args, **kwargs):
        # No dialog control is on screen in these frames, so the search dialog
        # reads as closed and the walks proceed against the sidebar census.
        raise RuntimeError("label not present")

    def settled_roster(self, step, region, attempts=6):
        return self.frame(step), list(self.pages[min(self.page, len(self.pages) - 1)])

    def read_roster(self, step, frame, region):
        return list(self.pages[min(self.page, len(self.pages) - 1)])

    def frame(self, step):
        return _Frame(step)

    def advance_sidebar(self, step, frame, deltas=(-240, -900)):
        if self.page + 1 >= len(self.pages):
            return frame, False
        self.page += 1
        return self.frame(f"{step}-after"), True

    def click_exact_row(self, step, frame, row):
        # Coordinate-bound, like the real method: no text re-match, so several
        # rows reading "Show more" cannot make this refuse.
        self.clicks.append((step, row["text"]))
        return row

    def click_roster_row(self, step, frame, rows, label):
        matches = [row for row in rows if row["text"].strip() == label.strip()]
        if len(matches) != 1:
            raise RuntimeError(f"{step}: {label!r} matched {len(matches)} settled rows")
        self.clicks.append((step, matches[0]["text"]))
        return matches[0]

    def scroll_by(self, step, frame, point, delta):
        return self.advance_sidebar(step, frame)[1]

    def routes(self):
        return []


class _Frame:
    def __init__(self, step):
        self.step = step
        self.size = (1800, 1131)

    def crop(self, _region):
        return self

    def convert(self, _mode):
        return self

    def point(self, _table):
        return self

    def getbbox(self):
        return None


class SessionWalkExpandTests(unittest.TestCase):
    def test_two_section_controls_no_longer_end_the_walk(self):
        surface = _WalkSurface([PAGE_ONE, PAGE_TWO])
        self.assertTrue(surface.walk_session_list(),
                        "the walk must reach the target row on page two")
        picked = [text for step, text in surface.clicks if step.startswith("session-list-pick")]
        self.assertEqual(picked, ["Kalshi Paper Burndown"])
        self.assertTrue(any(fields.get("step_id") == "session-list-expanded-1"
                            for _kind, fields in surface.notes))

    def test_every_section_control_is_expanded_once_within_the_bound(self):
        surface = _WalkSurface([PAGE_ONE])
        frame, rows, expanded = surface.expand_sections(1, _Frame("f"), list(PAGE_ONE), "walk")
        self.assertEqual(expanded, 2)
        texts = [text for step, text in surface.clicks if step.startswith("walk-expand-1")]
        self.assertEqual(texts, ["Show more", "Show more"])

    def test_the_target_project_section_is_expanded_first(self):
        rows = [{"text": "B SCMessenger", "x": 90, "y": 250, "x1": 250},
                {"text": "Show more", "x": 100, "y": 290, "x1": 200},
                {"text": "B Kalshi-Trader", "x": 90, "y": 330, "x1": 250},
                {"text": "Show more", "x": 100, "y": 370, "x1": 200}]
        surface = _WalkSurface([rows])
        surface.expand_sections(1, _Frame("f"), list(rows), "walk")
        first = surface.clicks[0]
        self.assertEqual(first[1], "Show more")
        self.assertEqual(surface.clicks[0][0], "walk-expand-1-1")
        # The target's own section is the second census row, so it must be the
        # one ordered first: proven by which row object was handed to the click.
        self.assertEqual(surface.notes[0][1].get("step_id"), "walk-expanded-1")

    def test_a_project_scoped_exact_row_is_opened_by_the_route_walk(self):
        surface = _WalkSurface([PAGE_TWO])
        self.assertTrue(surface.identify_by_route(),
                        "an exact title under this lane's own project heading is the lane")
        self.assertTrue(any(text == "Kalshi Paper Burndown" for _step, text in surface.clicks))

    def test_an_exact_row_under_another_project_is_still_not_clicked(self):
        foreign = [{"text": "B Other", "x": 90, "y": 250, "x1": 200},
                   {"text": "Kalshi Paper Burndown", "x": 100, "y": 290, "x1": 330}]
        surface = _WalkSurface([foreign])
        self.assertFalse(surface.identify_by_route())
        self.assertFalse(any(text == "Kalshi Paper Burndown" for _step, text in surface.clicks))


class QueryReadbackSlipTests(unittest.TestCase):
    """The readback proves the query landed; one misread glyph is not foreign text."""

    def _surface(self, reading):
        surface = _WalkSurface([PAGE_ONE])
        surface.locate_exact_text = lambda *a, **k: [100, 200]
        surface.act = lambda *a, **k: None
        surface.read_lines = lambda *a, **k: [reading]
        return surface

    def test_one_glyph_slip_is_accepted(self):
        surface = self._surface("Kalshi Paper Burndow")
        self.assertIsNotNone(surface.query_search_field(_Frame("f")))

    def test_different_text_is_still_refused(self):
        surface = self._surface("Continue the SCMessenger queue please")
        with self.assertRaises(RuntimeError) as caught:
            surface.query_search_field(_Frame("f"))
        self.assertIn("not typing over it", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
