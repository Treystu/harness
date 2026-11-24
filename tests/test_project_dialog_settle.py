"""The New project dialog animates in; one fixed sleep is not a read.

Measured 2026-11-24 on the launch cold run: the adapter captured one second after
clicking New project, refused with "the name control 'Project name' was not
visible", and the identical frame one settle later resolved every anchor. These
tests pin the retry and the refusal that survives it.
"""
import unittest
from unittest.mock import Mock, patch

from scripts import windows_freebuff_dispatch as dispatch


class _Surface:
    def __init__(self, visible_from):
        self.visible_from = visible_from
        self.frames = 0
        self.audit = Mock()
        self.calls = []

    def frame(self, step=None):
        self.frames += 1
        return f"frame-{self.frames}"

    def locate_exact_text(self, step, frame, label, region):
        self.calls.append((step, label, region))
        index = int(str(frame).split("-")[-1])
        if index < self.visible_from:
            raise RuntimeError(f"{label} not visible yet")
        return [100, 200]


class ProjectDialogSettleTests(unittest.TestCase):
    def test_a_dialog_that_settles_late_is_read_rather_than_refused(self):
        surface = _Surface(visible_from=3)
        with patch.object(dispatch.time, "sleep", Mock()):
            frame, name_point, _, create_point, _ = dispatch.project_dialog_anchors(
                surface, "project-dialog")
        self.assertEqual(frame, "frame-3")
        self.assertEqual(name_point, [100, 200])
        self.assertEqual(create_point, [100, 200])
        steps = [c.kwargs.get("step_id") for c in surface.audit.append.call_args_list]
        self.assertIn("project-dialog-settled", steps)

    def test_a_dialog_that_never_settles_is_still_refused_by_name(self):
        surface = _Surface(visible_from=99)
        with patch.object(dispatch.time, "sleep", Mock()):
            with self.assertRaisesRegex(RuntimeError, "not visible; not clicking a guess"):
                dispatch.project_dialog_anchors(surface, "project-dialog", attempts=2)

    def test_the_measured_create_button_is_inside_its_region(self):
        _, region = dispatch.PROJECT_DIALOG["create"]
        left, top, right, bottom = region
        self.assertTrue(left <= 1083 <= right and top <= 698 <= bottom)


class CreatedProjectRowTests(unittest.TestCase):
    """The created row carries the folder icon's glyph; exact equality loses it."""

    def test_a_row_with_the_icon_glyph_still_names_the_created_project(self):
        self.assertTrue(dispatch.Dispatch.exact_session_title(
            "B robby-battery-helper", "robby-battery-helper"))

    def test_a_different_project_is_not_matched(self):
        self.assertFalse(dispatch.Dispatch.exact_session_title(
            "B robby-battery-helper-old", "robby-battery-helper"))


if __name__ == "__main__":
    unittest.main()
