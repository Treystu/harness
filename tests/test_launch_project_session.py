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

try:
    from PIL import Image, ImageDraw
except ImportError:  # hermetic CI legs install no imaging stack
    # The fake surface below only needs a frame object that crops and hashes
    # bytes; without this the module failed to import at all and took the whole
    # hermetic leg red with it (measured 2026-11-25 on the repo .venv, which has
    # no Pillow, while the interpreter the watch runs under does).
    class _Canvas:
        # The fake surface paints one 32x32 near-white send arrow at this box;
        # that is the only region the launcher measures.
        ARROW = (1488, 1052, 1520, 1084)

        def __init__(self, size=(1800, 1131), color=(0, 0, 0), bbox=None):
            self.size = size
            self.width, self.height = size
            self._pixels = bytes(color)
            self._bbox = bbox

        def crop(self, region):
            left, top, right, bottom = region
            x0, y0 = max(self.ARROW[0], left), max(self.ARROW[1], top)
            x1, y1 = min(self.ARROW[2], right), min(self.ARROW[3], bottom)
            window = (right - left, bottom - top)
            if x1 <= x0 or y1 <= y0:
                return _Canvas(window, bbox=None)
            return _Canvas(window, bbox=(x0 - left, y0 - top, x1 - left, y1 - top))

        def convert(self, _mode):
            return self

        def point(self, _fn):
            return self

        def getbbox(self):
            return self._bbox

        def tobytes(self):
            return self._pixels

    class Image:  # type: ignore[no-redef]
        @staticmethod
        def new(_mode, size, color=(0, 0, 0)):
            return _Canvas(size, color)

    class ImageDraw:  # type: ignore[no-redef]
        class _Pen:
            def rectangle(self, *_args, **_kwargs):
                return None

        @staticmethod
        def Draw(_image):
            return ImageDraw._Pen()

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
