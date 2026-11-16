"""#481: a bounded target names its pixel space, and consent binds to it.

The issue's DPI discipline is one sentence -- "all coordinates name their space
(capture is logical px at 125% on the owner machine)" -- and it is the half of
#481 that can be proven without a desktop. A rectangle with no space is a
coordinate a 125%-scaled machine can aim 25% off, so the model must carry the
space rather than let a consumer infer it.

These tests pin:

* the canonical record always carries ``space``, defaulting to the space
  capture produces;
* ``client-physical`` requires a declared ``scale``, a logical target refuses
  one, and every undeclared or impossible value is refused by name;
* two targets that differ only in their declared space are different consent
  subjects, which is what makes the declaration load-bearing rather than
  decorative;
* the schema version moved, so a consumer pinned to ``target@1`` refuses the
  new record instead of half-reading it.
"""
import unittest

from driver_core import osal, targeting
from driver_core.actions import DEFAULT_VOCABULARY
from driver_core.audit import MemoryAuditLog
from driver_core.errors import ConsentError, VocabularyError
from driver_core.executor import Consent, Executor
from driver_core.executor_registry import build_driver_registry


class DeclaredSpaceTests(unittest.TestCase):
    def test_the_canonical_record_always_names_a_space(self):
        resolved = targeting.resolve_target(
            {"window": "Notes", "rect": [10, 20, 300, 40]})
        self.assertEqual(resolved["space"], targeting.DEFAULT_SPACE)
        self.assertEqual(targeting.DEFAULT_SPACE, "client-logical")

    def test_the_default_is_the_space_capture_produces(self):
        # Not a convenience: capture is logical pixels, so an unstated space
        # must resolve to the space the pixels actually came from.
        self.assertEqual(
            targeting.resolve_target(
                {"window": "N", "rect": [0, 0, 1, 1]})["space"],
            "client-logical")

    def test_a_logical_target_may_say_so_explicitly(self):
        resolved = targeting.resolve_target(
            {"window": "Notes", "rect": [0, 0, 10, 10],
             "space": "client-logical"})
        self.assertEqual(resolved["space"], "client-logical")
        self.assertNotIn("scale", resolved)

    def test_a_physical_target_carries_its_scale(self):
        resolved = targeting.resolve_target(
            {"window": "Notes", "rect": [10, 20, 300, 40],
             "space": "client-physical", "scale": 1.25})
        self.assertEqual(resolved["space"], "client-physical")
        self.assertEqual(resolved["scale"], 1.25)

    def test_an_undeclared_space_is_refused_by_name(self):
        with self.assertRaises(targeting.TargetError) as ctx:
            targeting.resolve_target(
                {"window": "Notes", "rect": [0, 0, 10, 10],
                 "space": "device"})
        self.assertIn("not a declared pixel space", str(ctx.exception))

    def test_a_non_string_space_is_refused(self):
        for space in (1, ["client-logical"], {"space": "client-logical"}):
            with self.assertRaises(targeting.TargetError):
                targeting.resolve_target(
                    {"window": "Notes", "rect": [0, 0, 10, 10],
                     "space": space})

    def test_a_physical_target_without_a_scale_is_refused(self):
        with self.assertRaises(targeting.TargetError) as ctx:
            targeting.resolve_target(
                {"window": "Notes", "rect": [0, 0, 10, 10],
                 "space": "client-physical"})
        self.assertIn("must declare its scale", str(ctx.exception))

    def test_a_logical_target_may_not_declare_a_scale(self):
        with self.assertRaises(targeting.TargetError) as ctx:
            targeting.resolve_target(
                {"window": "Notes", "rect": [0, 0, 10, 10], "scale": 1.25})
        self.assertIn("declares no scale", str(ctx.exception))

    def test_an_impossible_scale_is_refused(self):
        for scale in (0, -1.25, 0.0, float("nan"), float("inf"), True, "1.25",
                      targeting.MAX_SCALE + 0.01):
            with self.assertRaises(targeting.TargetError):
                targeting.resolve_target(
                    {"window": "Notes", "rect": [0, 0, 10, 10],
                     "space": "client-physical", "scale": scale})

    def test_a_scale_inside_the_limit_is_accepted(self):
        resolved = targeting.resolve_target(
            {"window": "Notes", "rect": [0, 0, 10, 10],
             "space": "client-physical", "scale": targeting.MAX_SCALE})
        self.assertEqual(resolved["scale"], float(targeting.MAX_SCALE))

    def test_an_undeclared_key_is_still_refused(self):
        for extra in ({"dpi": 120}, {"unit": "px"}, {"point": [1, 1]}):
            value = {"window": "Notes", "rect": [0, 0, 10, 10]}
            value.update(extra)
            with self.assertRaises(targeting.TargetError):
                targeting.resolve_target(value)

    def test_an_unbounded_title_still_has_no_space(self):
        # A title names a window, not a point: inventing a space for it would
        # be exactly the guessing this model exists to prevent.
        self.assertEqual(targeting.resolve_target("Notes"), "Notes")

    def test_the_schema_needs_re_reading_by_v1_consumers(self):
        self.assertEqual(targeting.TARGET_SCHEMA, "target@2")
        resolved = targeting.resolve_target(
            {"window": "Notes", "rect": [0, 0, 1, 1]})
        self.assertNotEqual(resolved["schema"], "target@1")

    def test_describe_names_the_space_and_the_scale(self):
        logical = targeting.resolve_target(
            {"window": "Notes", "rect": [10, 20, 300, 40]})
        physical = targeting.resolve_target(
            {"window": "Notes", "rect": [10, 20, 300, 40],
             "space": "client-physical", "scale": 1.25})
        self.assertIn("client-logical", targeting.describe(logical))
        self.assertIn("client-physical", targeting.describe(physical))
        self.assertIn("x1.25", targeting.describe(physical))


class SpaceConsentTests(unittest.TestCase):
    """The declaration is load-bearing: it is part of what consent binds to."""

    def setUp(self):
        osal.register_input_backend(
            osal.platform_name(), lambda kind, **kwargs: (True, ""))
        self.addCleanup(osal.disable_input_backend)

    def _executor(self):
        return Executor(vocabulary=DEFAULT_VOCABULARY,
                        registry=build_driver_registry(allow_write=True),
                        audit=MemoryAuditLog(), dry_run=True)

    def _consent(self, resolved):
        return Consent(True, "click", {"target": resolved})

    def test_a_consent_for_the_same_rectangle_in_another_space_does_not_travel(self):
        logical = targeting.resolve_target(
            {"window": "Notes", "rect": [10, 20, 300, 40]})
        with self.assertRaises(ConsentError):
            self._executor().execute(
                "click",
                {"target": {"window": "Notes", "rect": [10, 20, 300, 40],
                            "space": "client-physical", "scale": 1.25}},
                consent=self._consent(logical))

    def test_a_consent_for_a_logical_target_authorises_it(self):
        resolved = targeting.resolve_target(
            {"window": "Notes", "rect": [10, 20, 300, 40]})
        result = self._executor().execute(
            "click",
            {"target": {"window": "Notes", "rect": [10, 20, 300, 40]}},
            consent=self._consent(resolved))
        self.assertTrue(result.ok)
        self.assertEqual(result.params["target"]["space"], "client-logical")

    def test_an_impossible_space_is_refused_before_any_executor_runs(self):
        for bad in ({"window": "Notes", "rect": [0, 0, 10, 10],
                     "space": "device"},
                    {"window": "Notes", "rect": [0, 0, 10, 10],
                     "space": "client-physical"}):
            with self.assertRaises(VocabularyError):
                self._executor().execute("click", {"target": bad},
                                         consent=self._consent(bad))


if __name__ == "__main__":
    unittest.main()
