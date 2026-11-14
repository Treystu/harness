"""#481 -- the bounded input-target model and the consent it binds.

``docs/driver.md`` states the gap: the parameters for ``click`` and
``submit_irreversible`` "do not identify a sufficiently bounded target". These
tests pin the model that closes it, headless and without a display:

* the legacy exact-title string resolves to itself, marked unbounded, so every
  existing caller and consent keeps working unchanged;
* the bounded mapping resolves to one canonical record (``target@1``) carrying
  the exact title and the exact client-relative rectangle;
* every malformed shape is refused by name -- unknown keys, missing keys, a
  blank or oversized title, control characters, a rectangle that is not four
  integers, a degenerate rectangle, and one beyond the declared bounds;
* the executor normalises before consent, so a consent given for the exact
  bounded target authorises it, a consent for a different rectangle does not,
  and a legacy consent still authorises the legacy string.
"""
import unittest

from driver_core import targeting
from driver_core.actions import DEFAULT_VOCABULARY
from driver_core.errors import ConsentError, VocabularyError
from driver_core.executor import Consent, Executor
from driver_core.executor_registry import build_driver_registry
from driver_core.audit import MemoryAuditLog


class LegacyTitleTests(unittest.TestCase):
    def test_a_title_resolves_to_itself(self):
        self.assertEqual(targeting.resolve_target("Harness smoke target"),
                         "Harness smoke target")

    def test_a_title_is_reported_as_unbounded(self):
        resolved = targeting.resolve_target("OK")
        self.assertFalse(targeting.is_bounded(resolved))
        self.assertIn("unbounded", targeting.describe(resolved))

    def test_a_blank_or_missing_title_is_refused(self):
        for value in ("", "   ", "\t", None, 7, ["OK"]):
            with self.assertRaises(targeting.TargetError):
                targeting.resolve_target(value)

    def test_an_oversized_title_is_refused(self):
        with self.assertRaises(targeting.TargetError):
            targeting.resolve_target("x" * (targeting.MAX_TITLE_LENGTH + 1))

    def test_a_title_at_the_limit_is_accepted(self):
        self.assertEqual(
            targeting.resolve_target("x" * targeting.MAX_TITLE_LENGTH),
            "x" * targeting.MAX_TITLE_LENGTH)

    def test_control_characters_in_a_title_are_refused(self):
        with self.assertRaises(targeting.TargetError):
            targeting.resolve_target("two\nlines")


class BoundedTargetTests(unittest.TestCase):
    def test_a_bounded_target_resolves_to_the_canonical_record(self):
        resolved = targeting.resolve_target(
            {"window": "Notes", "rect": [10, 20, 300, 40]})
        self.assertEqual(resolved, {
            "schema": targeting.TARGET_SCHEMA,
            "window": "Notes",
            "rect": [10, 20, 300, 40],
        })
        self.assertTrue(targeting.is_bounded(resolved))

    def test_the_canonical_record_is_a_copy_not_the_caller_mapping(self):
        supplied = {"window": "Notes", "rect": [1, 2, 3, 4]}
        resolved = targeting.resolve_target(supplied)
        supplied["rect"].append(5)
        self.assertEqual(resolved["rect"], [1, 2, 3, 4])

    def test_unknown_keys_are_refused_rather_than_ignored(self):
        for extra in ({"offset": 3}, {"selector": "#go"}, {"rect": [0, 0, 1, 1],
                                                            "window": "N",
                                                            "point": [1, 1]}):
            with self.assertRaises(targeting.TargetError):
                targeting.resolve_target(extra)

    def test_missing_keys_are_refused(self):
        for value in ({"window": "Notes"}, {"rect": [0, 0, 1, 1]}, {}):
            with self.assertRaises(targeting.TargetError):
                targeting.resolve_target(value)

    def test_a_rectangle_must_be_four_integers(self):
        for rect in ([0, 0, 10], [0, 0, 10, 10, 10], "0,0,10,10", None,
                     [0.5, 0, 10, 10], [True, 0, 10, 10], [0, 0, "10", 10]):
            with self.assertRaises(targeting.TargetError):
                targeting.resolve_target({"window": "Notes", "rect": rect})

    def test_a_negative_origin_is_refused(self):
        for rect in ([-1, 0, 10, 10], [0, -1, 10, 10]):
            with self.assertRaises(targeting.TargetError):
                targeting.resolve_target({"window": "Notes", "rect": rect})

    def test_a_degenerate_rectangle_is_refused(self):
        for rect in ([0, 0, 0, 10], [0, 0, 10, 0], [0, 0, -5, 10]):
            with self.assertRaises(targeting.TargetError):
                targeting.resolve_target({"window": "Notes", "rect": rect})

    def test_a_rectangle_beyond_the_declared_bounds_is_refused(self):
        # Over on a side, over on an origin, and over on area -- each refused
        # by the rule that owns it rather than by an accident of ordering.
        for rect in ([0, 0, targeting.MAX_SIDE + 1, 10],
                     [targeting.MAX_SIDE + 1, 0, 10, 10],
                     [0, 0, 8000, 8000]):
            with self.assertRaises(targeting.TargetError):
                targeting.resolve_target({"window": "Notes", "rect": rect})

    def test_a_target_error_is_a_vocabulary_error(self):
        # Callers already catch VocabularyError for an undeclared name or
        # parameter; an unbounded target is the same class of refusal.
        with self.assertRaises(VocabularyError):
            targeting.resolve_target({"window": ""})

    def test_describe_names_the_window_and_the_rectangle(self):
        resolved = targeting.resolve_target(
            {"window": "Notes", "rect": [10, 20, 300, 40]})
        rendered = targeting.describe(resolved)
        self.assertIn("'Notes'", rendered)
        self.assertIn("[10, 20, 300, 40]", rendered)


class VocabularyDeclarationTests(unittest.TestCase):
    def test_click_and_submit_declare_the_target_normaliser(self):
        for name in ("click", "submit_irreversible"):
            action = DEFAULT_VOCABULARY.resolve(name)
            self.assertEqual(action.normalisers, {"target": "resolve_target"})

    def test_actions_without_a_target_are_unchanged(self):
        self.assertEqual(DEFAULT_VOCABULARY.resolve("focus").normalisers, {})
        self.assertEqual(DEFAULT_VOCABULARY.resolve("scroll").normalisers, {})

    def test_the_vocabulary_versions_the_change(self):
        self.assertEqual(DEFAULT_VOCABULARY.identity(),
                         "driver-core-actions@1.1.0")


class ConsentBindingTests(unittest.TestCase):
    """A consent is bound to the *resolved* target, not the raw one."""

    def setUp(self):
        from driver_core import osal
        self.vocabulary = DEFAULT_VOCABULARY
        # An input backend so the action is executable at all; the executor
        # runs dry, so nothing is ever sent anywhere.
        osal.register_input_backend(
            osal.platform_name(), lambda kind, **kwargs: (True, ""))
        self.addCleanup(osal.disable_input_backend)

    def _executor(self):
        registry = build_driver_registry(allow_write=True)
        return Executor(vocabulary=self.vocabulary, registry=registry,
                        audit=MemoryAuditLog(), dry_run=True)

    def _consent(self, resolved):
        return Consent(True, "click", {"target": resolved})

    def test_a_bounded_consent_authorises_the_exact_window_and_rectangle(self):
        bounded = targeting.resolve_target(
            {"window": "Notes", "rect": [10, 20, 300, 40]})
        result = self._executor().execute(
            "click", {"target": {"window": "Notes",
                                  "rect": [10, 20, 300, 40]}},
            consent=self._consent(bounded))
        self.assertTrue(result.ok)
        self.assertEqual(result.params, {"target": bounded})

    def test_a_consent_for_another_rectangle_does_not_travel(self):
        approved = targeting.resolve_target(
            {"window": "Notes", "rect": [10, 20, 300, 40]})
        with self.assertRaises(ConsentError):
            # Same window, one pixel right: a different consent subject.
            self._executor().execute(
                "click", {"target": {"window": "Notes",
                                      "rect": [11, 20, 300, 40]}},
                consent=self._consent(approved))

    def test_a_legacy_title_consent_still_authorises_the_legacy_title(self):
        result = self._executor().execute(
            "click", {"target": "OK"}, consent=self._consent("OK"))
        self.assertTrue(result.ok)
        self.assertEqual(result.params, {"target": "OK"})

    def test_a_malformed_target_is_refused_before_any_executor_runs(self):
        executor = self._executor()
        for bad in ({"window": "Notes", "rect": [0, 0, 0, 0]},
                    {"window": "", "rect": [0, 0, 10, 10]},
                    {"window": "Notes", "rect": [0, 0, 10, 10],
                     "point": [1, 1]}):
            with self.assertRaises(VocabularyError):
                executor.execute("click", {"target": bad},
                                 consent=self._consent(bad))


if __name__ == "__main__":
    unittest.main()
