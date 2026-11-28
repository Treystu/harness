"""The bystander observation must not gate a dispatch on the sidebar's scroll.

Measured 2026-11-24: dispatch 7127830177 (Kalshi) and 7127395609 (Disk Audit) both
parked with "locate-bystander-lane: exact OCR label 'Lane 1' was not verified". The
previous lane's walk had scrolled Lane 1's row out of the sidebar, so a probe whose
stated job is to wITNESS a bystander across the input ended the run before the
target lane's own first phase ever ran.

The probe now reveals the row inside a bound and records an unobserved bystander
when it still cannot be seen. These tests fail against the previous code, which
raised out of observe_running in exactly that case.
"""
import unittest

from scripts import windows_freebuff_dispatch as dispatch


class _Probe(dispatch.Dispatch):
    """A surface where Lane 1's row may or may not be reachable at all."""

    def __init__(self, reachable):
        self.label = "Lane 1"
        self.project = "Harness"
        self.thread = dispatch.THREAD
        self.text = dispatch.CONTINUATION
        self.output = None
        self.reachable = reachable
        self.steps = []
        self.notes = []

        class _Audit:
            def append(_self, kind, **fields):
                self.notes.append((kind, fields))

        class _Api:
            @staticmethod
            def foreground():
                return 1

        class _Window:
            handle = 1
            api = _Api()

        self.audit = _Audit()
        self.window = _Window()

    def frame(self, step):
        self.steps.append(step)
        return _Frame(step)

    def require_foreground(self):
        return 1

    def close_search_if_open(self, frame):
        return frame

    def scroll_sidebar_to_top(self, steps=8):
        self.steps.append("sidebar-top")
        return _Frame("sidebar-top")

    def locate_exact_text(self, step, frame, label, region, **kwargs):
        if not self.reachable:
            raise RuntimeError(f"{step}: exact OCR label {label!r} was not verified")
        return ([200, 400], [180, 380, 240, 420]) if kwargs.get("with_bounds") else [200, 400]

    def yes(self, *args, **kwargs):
        return None

    def act(self, step, action, params):
        self.steps.append(step)

    def verify_lane(self, frame):
        return None

    def stop_visible(self, frame):
        return True

    def working_banner(self, step, frame):
        return 12

    @property
    def window_api(self):
        return self.window.api


class BystanderToleranceTests(unittest.TestCase):
    def test_absent_bystander_is_recorded_not_raised(self):
        probe = _Probe(reachable=False)
        probe.observe_running()  # must not raise
        kinds = {fields.get("step_id") for _kind, fields in probe.notes}
        self.assertIn("bystander-unobserved", kinds)
        self.assertNotIn("bystander-stop", kinds)
        # It never clicked a guess in the sidebar.
        self.assertFalse(any(step == "navigate-to-bystander" for step in probe.steps))

    def test_the_row_is_revealed_before_the_probe_gives_up(self):
        probe = _Probe(reachable=False)
        probe.observe_running()
        self.assertIn("sidebar-top", probe.steps)

    def test_a_visible_bystander_is_still_witnessed(self):
        probe = _Probe(reachable=True)
        probe.output = _TempOutput()
        probe.observe_running()
        kinds = {fields.get("step_id") for _kind, fields in probe.notes}
        self.assertIn("bystander-stop", kinds)
        self.assertIn("navigate-to-bystander", probe.steps)


class _Frame:
    """Enough of a PIL image for the read-back comparison to be a no-op."""

    def __init__(self, step):
        self.step = step
        self.size = (1800, 1131)

    def crop(self, _region):
        return self

    def tobytes(self):
        return b""


class _TempOutput:
    """The Stop-frame digest is read off disk; an empty dir keeps it honest."""

    def __truediv__(self, name):
        return self

    def read_bytes(self):
        return b""


if __name__ == "__main__":
    unittest.main()
