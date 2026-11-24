"""Dispatch 7125887396: the send gate stood on a channel that is usually absent.

Prepare proved the SCMessenger lane, typed the continuation exactly once, and the
send then refused because the accessibility helper answers [] on this handle. The
route is corroboration; the settled exact-selection is the identity the send may
stand on, which is what these tests pin.
"""
import unittest
from unittest.mock import Mock

from scripts.windows_freebuff_dispatch import Dispatch


def _dispatch(selection, standing=True, thread="2ae32937"):
    dispatch = object.__new__(Dispatch)
    dispatch.thread = thread
    dispatch.label = "SCMessenger"
    dispatch.project = "SCMessenger"
    dispatch.standing = standing
    dispatch.audit = Mock()
    dispatch.routes = Mock(return_value=[])
    dispatch.selected_exact_session = Mock(return_value=selection)
    dispatch.require_foreground = Mock(return_value=1)
    return dispatch


class SendRouteFallbackTests(unittest.TestCase):
    def test_a_dead_tree_does_not_refuse_a_send_the_selection_proves(self):
        dispatch = _dispatch(True)
        dispatch.verify_active_session()
        steps = [c.kwargs.get("step_id") for c in dispatch.audit.append.call_args_list]
        self.assertIn("active-session-id", steps)
        recorded = [c.kwargs for c in dispatch.audit.append.call_args_list
                    if c.kwargs.get("step_id") == "active-session-id"][-1]
        self.assertEqual(recorded.get("route_fallback"), "exact-scoped-selection")
        self.assertEqual(recorded.get("pinned_uuid"), "2ae32937-c991-4c33-87d4-68b8c956ba98")

    def test_a_selection_that_is_not_the_pinned_lane_still_refuses(self):
        dispatch = _dispatch(False)
        dispatch.phase = "prepare"
        with self.assertRaisesRegex(RuntimeError, "did not expose the exact pinned thread"):
            dispatch.verify_active_session()

    def test_the_staged_continuation_proves_the_send_when_no_selection_is_readable(self):
        """7126349762: the ring was drawn as an outline the fill probe cannot see."""
        dispatch = _dispatch(False)
        dispatch.phase = "send"
        dispatch.text = "continue in full"
        dispatch.saw_text = Mock(return_value=True)
        dispatch.frame = Mock(return_value=Mock())
        dispatch.verify_active_session()
        recorded = [c.kwargs for c in dispatch.audit.append.call_args_list
                    if c.kwargs.get("step_id") == "active-session-id"][-1]
        self.assertEqual(recorded.get("route_fallback"), "staged-continuation")

    def test_a_composer_without_the_continuation_still_refuses_at_send(self):
        dispatch = _dispatch(False)
        dispatch.phase = "send"
        dispatch.text = "continue in full"
        dispatch.saw_text = Mock(return_value=False)
        dispatch.frame = Mock(return_value=Mock())
        with self.assertRaisesRegex(RuntimeError, "did not expose the exact pinned thread"):
            dispatch.verify_active_session()

    def test_a_live_route_is_still_the_primary_proof(self):
        dispatch = _dispatch(True)
        dispatch.routes = Mock(return_value=["freebuff://chat/2ae32937-c991-4c33-87d4-68b8c956ba98"])
        dispatch.verify_active_session()
        dispatch.selected_exact_session.assert_not_called()

    def test_a_non_standing_send_keeps_the_strict_route_requirement(self):
        dispatch = _dispatch(True, standing=False)
        with self.assertRaisesRegex(RuntimeError, "did not expose the exact pinned thread"):
            dispatch.verify_active_session()
        dispatch.selected_exact_session.assert_not_called()


class StrayContinuationReconcileTests(unittest.TestCase):
    """Dispatch 7125887396 typed once and its send was refused, which left the
    continuation staged. The next run must adopt that text, not retype it, so the
    lane receives exactly one continuation."""

    def _dispatch(self, text="continue in full"):
        dispatch = object.__new__(Dispatch)
        dispatch.text = text
        return dispatch

    def test_a_composer_holding_the_approved_text_is_staged_not_foreign(self):
        dispatch = self._dispatch()
        self.assertEqual(
            dispatch.composer_written_route(["continue in full"],
                                            "Ask Freebuff... Use / for commands, @ for files"),
            "staged")

    def test_any_other_draft_stays_foreign_and_is_never_typed_over(self):
        dispatch = self._dispatch()
        self.assertEqual(
            dispatch.composer_written_route(["owner module with an owner test"],
                                            "Ask Freebuff... Use / for commands, @ for files"),
            "foreign")
