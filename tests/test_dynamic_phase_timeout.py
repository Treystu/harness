"""A claimed dispatch's phase bound must cover the walk the app actually renders.

Measured 2026-11-24: CivicScope (dispatch 7127711668) was parked at
"search: driver tree terminated after deadline" while its trace showed the walk
still censusing page 11 of the expanded session list. The old bound was 240 s.
Expanding every collapsed section is the cure for the Kalshi/Harness Audit
refusals, and it makes the walk deeper, so the bound has to follow it.

This test fails against the previous code: dynamic_phase_timeout did not exist and
the bound was the literal 240.
"""
import unittest

from scripts import windows_freebuff_watch as watch


class DynamicPhaseTimeoutTests(unittest.TestCase):
    def test_the_walk_bound_covers_the_measured_deep_list(self):
        self.assertGreaterEqual(watch.dynamic_phase_timeout("result-dyn-7127711668-46472fcc"), 480)

    def test_the_bound_is_not_unbounded(self):
        # A census that never ends is a different defect from a census cut short.
        self.assertLessEqual(watch.dynamic_phase_timeout("result-dyn-x-y"), 900)

    def test_an_empty_item_keeps_the_shorter_bound(self):
        self.assertEqual(watch.dynamic_phase_timeout(""), 240)


if __name__ == "__main__":
    unittest.main()
