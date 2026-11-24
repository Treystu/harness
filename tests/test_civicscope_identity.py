"""The CivicScope lane must be addressable by pinned identity.

Filed under the corrected fleet order (2026-11-23 23:32 HST): Agensi and
CivicScope had no entry in the driver's session tables, so parse_dynamic_dispatch
could not accept a dispatch for either and no dispatch could ever restart them.
CivicScope's full UUID was then read by the same read-only local lookup that
pinned Lane 1 and Disk Audit, so the identity is measured, not guessed.

These tests fail without the entry: the dispatch refuses, and the sidebar row
cannot be attributed to its project heading.
"""
import unittest

from scripts import windows_freebuff_dispatch as dispatch

CIVIC = "46472fcc"
CIVIC_UUID = "46472fcc-ca7e-469b-806a-1e05e5bb8d00"


class CivicScopeIdentityTests(unittest.TestCase):
    def test_session_is_addressable_by_its_short_thread(self):
        self.assertIn(CIVIC, dispatch.SESSIONS)
        label, text = dispatch.SESSIONS[CIVIC]
        self.assertEqual(label, "CivicScope")
        self.assertEqual(text, dispatch.CONTINUATION)

    def test_project_heading_is_bound_and_readable(self):
        self.assertEqual(dispatch.PROJECT_OF[CIVIC], "civicscope(cloud)")
        self.assertIn("civicscope(cloud)", dispatch.PROJECT_HEADINGS)
        self.assertEqual(dispatch.Dispatch.heading_name("D civicscope(cloud)"),
                         "civicscope(cloud)")

    def test_pinned_uuid_is_the_stored_session_uuid(self):
        self.assertEqual(dispatch.PINNED_UUIDS[CIVIC], CIVIC_UUID)
        self.assertTrue(dispatch.PINNED_UUIDS[CIVIC].startswith(CIVIC))

    def test_a_restart_dispatch_addressed_to_the_lane_selects_it(self):
        from scripts import windows_freebuff_watch as watch

        body = (
            "RESTART DISPATCH - CivicScope boundary restart (thread 46472fcc)\n\n"
            'Action for the runner: one in-place restart with exactly "continue in full".\n')
        self.assertTrue(watch.restart_dispatch(body))
        self.assertEqual(watch._lane_thread_from_dispatch(body), CIVIC)

    def test_the_row_is_attributed_to_its_own_project(self):
        rows = [{"text": "D civicscope(cloud)", "x": 90, "y": 432},
                {"text": "Ra CivicScope Submission Lar", "x": 100, "y": 474}]
        self.assertEqual(dispatch.Dispatch.project_of_row(rows, rows[1]), "civicscope(cloud)")


if __name__ == "__main__":
    unittest.main()
