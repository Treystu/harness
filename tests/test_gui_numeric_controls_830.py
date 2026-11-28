"""#830 slice 3: the numeric run-limit controls and the env-pin surface.

The settings pane renders one control per GUI-writable numeric key, with the
bounds the server itself enforces. These tests pin the three things that make
that honest:

1. ``GUI_NUMERIC_RANGES`` matches real loader behaviour at both edges -- an
   offered bound is accepted and one step past it is refused -- so a range
   change in the loader cannot leave a control that offers a value the
   server rejects.
2. ``_settings_view`` publishes those ranges and the env-pin map, which is
   what the pane renders from.
3. ``env_pinned_settings`` reports a pin only when the variable is set, and
   never returns a value (only the public variable name).

Hermetic: CONFIG_DIR is a temp dir per test and every HARNESS_* variable is
cleared/restored, so the operator's real config is never touched.
"""
import os
import tempfile
import unittest
from unittest import mock

from harness import config as config_module
from harness.config import (
    GUI_NUMERIC_RANGES,
    GUI_WRITABLE_SETTINGS,
    _ENV_NAMES,
    env_pinned_settings,
    load_settings,
    update_config,
)
from harness.errors import HarnessError


def _step(hi, lo):
    """One step just outside a range, integer or fractional."""
    return 1 if isinstance(lo, int) and isinstance(hi, int) else 0.01


class NumericRangeTableTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="harness-gui-limits-")
        patch = mock.patch.object(config_module, "CONFIG_DIR", self._tmp)
        patch.start()
        self.addCleanup(patch.stop)
        self._saved = {}
        for env in set(_ENV_NAMES.values()):
            self._saved[env] = os.environ.get(env)
            os.environ.pop(env, None)
        self.addCleanup(self._restore)

    def _restore(self):
        for env, val in self._saved.items():
            if val is None:
                os.environ.pop(env, None)
            else:
                os.environ[env] = val

    def test_every_numeric_key_is_gui_writable(self):
        self.assertTrue(set(GUI_NUMERIC_RANGES) <= set(GUI_WRITABLE_SETTINGS))
        self.assertTrue(GUI_NUMERIC_RANGES)

    def test_the_table_covers_every_writable_integer_setting(self):
        # The pane must not silently miss a numeric key: every writable key
        # whose loaded value is an int/float (not bool) needs a range.
        settings = load_settings()
        for key in sorted(GUI_WRITABLE_SETTINGS):
            value = getattr(settings, key, None)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            self.assertIn(key, GUI_NUMERIC_RANGES, key)

    def test_both_edges_are_accepted_and_one_step_past_is_refused(self):
        for key, (lo, hi) in sorted(GUI_NUMERIC_RANGES.items()):
            step = _step(hi, lo)
            update_config({key: lo})          # lower bound is legal
            update_config({key: hi})          # upper bound is legal
            below = lo - step
            above = hi + step
            if key == "max_rotations":
                # 0 is the legal floor; the loader refuses a negative one.
                below = -1
            with self.assertRaises(HarnessError, msg=f"{key} below"):
                update_config({key: below})
            with self.assertRaises(HarnessError, msg=f"{key} above"):
                update_config({key: above})


class SettingsViewPublishesControlsTests(unittest.TestCase):
    def test_the_view_carries_the_ranges_the_pane_renders(self):
        from harness.server import _settings_view
        view = _settings_view()
        surfaced = view.get("gui_numeric_ranges") or {}
        self.assertEqual(set(surfaced), set(GUI_NUMERIC_RANGES))
        for key, (lo, hi) in GUI_NUMERIC_RANGES.items():
            self.assertEqual(surfaced[key], [lo, hi], key)
        self.assertIsInstance(view.get("env_pinned"), dict)

    def test_a_pinned_key_is_reported_with_its_variable_name(self):
        saved = os.environ.get("HARNESS_MAX_TOKENS")
        try:
            os.environ["HARNESS_MAX_TOKENS"] = "4096"
            pinned = env_pinned_settings()
            self.assertEqual(pinned.get("max_tokens"), "HARNESS_MAX_TOKENS")
            from harness.server import _settings_view
            self.assertEqual(
                _settings_view()["env_pinned"].get("max_tokens"),
                "HARNESS_MAX_TOKENS")
        finally:
            if saved is None:
                os.environ.pop("HARNESS_MAX_TOKENS", None)
            else:
                os.environ["HARNESS_MAX_TOKENS"] = saved

    def test_an_unset_variable_is_not_reported_as_a_pin(self):
        saved = os.environ.pop("HARNESS_MAX_ROTATIONS", None)
        try:
            self.assertNotIn("max_rotations", env_pinned_settings())
        finally:
            if saved is not None:
                os.environ["HARNESS_MAX_ROTATIONS"] = saved

    def test_pins_carry_names_not_values(self):
        saved = os.environ.get("HARNESS_MCP_TOOL_TIMEOUT")
        try:
            os.environ["HARNESS_MCP_TOOL_TIMEOUT"] = "900"
            pinned = env_pinned_settings()
            self.assertEqual(pinned.get("mcp_tool_timeout"),
                             "HARNESS_MCP_TOOL_TIMEOUT")
            self.assertNotIn("900", pinned.values())
        finally:
            if saved is None:
                os.environ.pop("HARNESS_MCP_TOOL_TIMEOUT", None)
            else:
                os.environ["HARNESS_MCP_TOOL_TIMEOUT"] = saved


if __name__ == "__main__":
    unittest.main()