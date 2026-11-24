"""The launch type, pinned: no duplicate, no typing into a live composer, one send.

Dispatch 7094914841 orders exactly one creation of project `robby-battery-helper`
and one session carrying the mission of record. These tests pin the three ways
that could go wrong - a project that already exists, a composer that is not empty,
and a second send - with a fake surface, so the rule is checkable without the
desktop.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

from scripts import windows_freebuff_dispatch as dispatch


class _Surface:
    def __init__(self, rows, *, placeholder_present=True, carrier_reads=True,
                 stop_after=1):
        self.rows = rows
        self.placeholder_present = placeholder_present
        self.carrier_reads = carrier_reads
        self.stop_after = stop_after
        self.text = ""
        self.audit = Mock()
        self.output = Path(tempfile.mkdtemp(prefix="launch-"))
        self.acts = []
        self.frames = 0

    def settled_roster(self, step, region, attempts=5):
        return self.frame(), self.rows

    def frame(self, step=None):
        self.frames += 1
        image = Image.new("RGB", (1800, 1131), (20, 20, 20))
        draw = ImageDraw.Draw(image)
        # The send arrow's own outline: 34x34 of near-white.
        draw.rectangle((1488, 1052, 1520, 1084), fill=(250, 250, 250))
        return image

    def settle_view(self, step):
        return self.frame(step)

    def locate_exact_text(self, step, frame, text, region):
        if not self.placeholder_present:
            raise RuntimeError("placeholder absent")
        return [900, 980]

    def read_lines(self, step, frame, region):
        return ["sha256:02f80742cbc8 MISSION text"] if self.carrier_reads else ["something else"]

    def yes(self, *args, **kwargs):
        return True

    def act(self, step, action, params):
        self.acts.append((step, action.name))

    def stop_visible(self, frame):
        return self.frames > self.stop_after

    @staticmethod
    def _norm(text):
        return "".join(str(text).casefold().split())


class LaunchProjectSessionTests(unittest.TestCase):
    def _run(self, surface, mission="sha256:02f80742cbc8\nMISSION text", carrier="sha256:02f80742cbc8"):
        with patch.object(dispatch, "create_project",
                          return_value={"text": "robby-battery-helper", "x": 100, "y": 300}), \
                patch.object(dispatch.time, "sleep", Mock()):
            return dispatch.launch_project_session(surface, "robby-battery-helper", mission, carrier)

    def test_a_project_that_already_has_a_row_is_refused_not_duplicated(self):
        surface = _Surface(rows=[{"text": "robby-battery-helper"}])
        with self.assertRaisesRegex(RuntimeError, "would duplicate a session"):
            self._run(surface)
        self.assertEqual(surface.acts, [])

    def test_the_mission_is_typed_once_and_sent_once(self):
        surface = _Surface(rows=[{"text": "Harness"}])
        self._run(surface)
        kinds = [name for _, name in surface.acts]
        self.assertEqual(kinds.count("type_freebuff"), 1)
        self.assertEqual(kinds.count("send_freebuff"), 1)

    def test_a_composer_that_does_not_read_back_the_carrier_is_not_sent(self):
        surface = _Surface(rows=[{"text": "Harness"}], carrier_reads=False)
        with self.assertRaisesRegex(RuntimeError, "carrier line"):
            self._run(surface)
        self.assertNotIn("send_freebuff", [name for _, name in surface.acts])

    def test_the_one_send_marker_bounds_a_second_launch(self):
        surface = _Surface(rows=[{"text": "Harness"}])
        self._run(surface)
        again = _Surface(rows=[{"text": "Harness"}])
        again.output = surface.output
        with self.assertRaisesRegex(RuntimeError, "one-send marker"):
            self._run(again)


if __name__ == "__main__":
    unittest.main()
