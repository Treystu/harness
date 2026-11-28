"""#830 slice 1: the settings census the GUI classification is held to.

Acceptance item 1 requires the full settings universe to be enumerated from
``config.py``'s own key map, with every key carrying a GUI classification --
and a test that fails when a new key lands in the map unclassified. These
tests are that census: the three ``GUI_*_SETTINGS`` sets must partition
``_ENV_NAMES`` exactly, the writable set must be exactly what
``update_config`` enforces, and every secret must be absent-or-nulled in the
GUI read (``_settings_view``).

Hermetic: refusal assertions raise before any disk write, so they need no
CONFIG_DIR patching; the round-trip sweep isolates CONFIG_DIR in a temp dir
and clears the env pins for the keys under test.
"""
import inspect
import os
import tempfile
import unittest
from unittest import mock

from harness import config as config_module
from harness.config import (
    GUI_READ_ONLY_SETTINGS,
    GUI_SECRET_SETTINGS,
    GUI_WRITABLE_SETTINGS,
    _ENV_NAMES,
    load_settings,
    update_config,
)
from harness.errors import HarnessError


class GuiSettingsCensusTests(unittest.TestCase):
    def test_the_three_classes_partition_the_key_map_exactly(self):
        env_keys = set(_ENV_NAMES)
        self.assertEqual(
            GUI_WRITABLE_SETTINGS | GUI_SECRET_SETTINGS
            | GUI_READ_ONLY_SETTINGS,
            env_keys,
            "every key in _ENV_NAMES must carry a GUI classification",
        )
        self.assertFalse(
            GUI_WRITABLE_SETTINGS & GUI_SECRET_SETTINGS,
            "writable and secret overlap",
        )
        self.assertFalse(
            GUI_WRITABLE_SETTINGS & GUI_READ_ONLY_SETTINGS,
            "writable and read-only overlap",
        )
        self.assertFalse(
            GUI_SECRET_SETTINGS & GUI_READ_ONLY_SETTINGS,
            "secret and read-only overlap",
        )

    def test_update_config_enforces_exactly_the_writable_set(self):
        # The ONE config owner must draw its allow-list from the census map,
        # not from a second literal that can drift.
        self.assertIn(
            "GUI_WRITABLE_SETTINGS", inspect.getsource(update_config))
        # Every non-writable known key is refused before any disk write.
        for key in sorted(set(_ENV_NAMES) - set(GUI_WRITABLE_SETTINGS)):
            with self.assertRaises(HarnessError, msg=key) as ctx:
                update_config({key: "anything"})
            self.assertIn("not runtime-updatable", str(ctx.exception), key)

    def test_secrets_are_absent_or_nulled_in_the_gui_read(self):
        from harness.server import _settings_view
        view = _settings_view()
        for key in sorted(GUI_SECRET_SETTINGS):
            if key in view:
                # The invariant is never-echoed: the value is always None.
                # The _present flag is advisory (absent when unconfigured,
                # False when explicitly empty), so only None is pinned here.
                self.assertIsNone(view[key], key)
            # Provider keys never reach the browser at all: absence is the
            # strongest redaction.
        for key in ("fireworks_key", "meta_key", "groq_key", "cerebras_key"):
            self.assertNotIn(key, view)


class GuiWritableRoundTripTests(unittest.TestCase):
    """Every writable key persists through the ONE owner and reads back."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="harness-gui-census-")
        self._cfg_patch = mock.patch.object(
            config_module, "CONFIG_DIR", self._tmp)
        self._cfg_patch.start()
        self.addCleanup(self._cfg_patch.stop)
        self._saved_env = {}
        for env in set(_ENV_NAMES.values()):
            self._saved_env[env] = os.environ.get(env)
            os.environ.pop(env, None)
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        for env, val in self._saved_env.items():
            if val is None:
                os.environ.pop(env, None)
            else:
                os.environ[env] = val

    def test_every_writable_key_round_trips(self):
        current = load_settings()
        values = {}
        for key in sorted(GUI_WRITABLE_SETTINGS):
            if key == "hourglass_stages":
                values[key] = "context,planning"
            else:
                values[key] = getattr(current, key)
        updated = update_config(dict(values))
        for key in sorted(GUI_WRITABLE_SETTINGS):
            if key == "hourglass_stages":
                self.assertEqual(updated.hourglass_stages,
                                 ["context", "planning"])
            else:
                self.assertEqual(getattr(updated, key),
                                 getattr(current, key), key)


if __name__ == "__main__":
    unittest.main()
