"""#473: router health and the ordering produced at each rotation.

The Champion router-ranking brief could not execute: nothing in the record said
which order rotation actually walked or what health it had observed, so the
dynamic ranker's decisions were unobservable (#466 brief, unblocker "persist
router health and the ordering produced at each rotation").

The rows are the trace family the run already holds -- one ``router.rotation``
row per decision, written where the decision is made
(:meth:`harness.router.Router._rotation_ordered`). These tests pin the ordered
sequence, the health that produced it, the transitions across rotations, the
absent-when-unknown rule, and legacy tolerance. No second event stream, table or
reader is introduced.
"""
import os
import tempfile
import unittest

from harness.decision_trace import DecisionTrace, read_trace_events
from harness.ledger import AutonomyLedger
from harness.router import ROTATION_EVENT, Router, read_rotations
from tests._fake import P1, P2, JUDGE


def _ledger():
    td = tempfile.TemporaryDirectory()
    ledger = AutonomyLedger(os.path.join(td.name, "ledger.jsonl"))
    return td, ledger


def _router(ledger, pool=None):
    return Router(panel=[P1], judge=JUDGE, apply_model=P1,
                  apply_pool=pool or [P1, P2, JUDGE],
                  trace=DecisionTrace(ledger), use_free=True)


class RotationOrderTests(unittest.TestCase):
    def test_each_rotation_records_the_order_it_produced(self):
        td, ledger = _ledger()
        self.addCleanup(td.cleanup)
        router = _router(ledger)
        router.note_model_result(P2, ok=False)  # P2 sinks below JUDGE

        ordered = router.apply_pool
        self.assertEqual(ordered, [P1, JUDGE, P2])

        rows = read_rotations(ledger, lane="apply")
        self.assertTrue(rows)
        payload = rows[-1]
        self.assertEqual(payload["lane"], "apply")
        self.assertEqual(payload["declared"], [P1, P2, JUDGE])
        self.assertEqual(payload["ordered"], ordered)
        self.assertIs(payload["ranked"], True)
        # Only the observed model carries health; the observed value is the
        # ranker's own input, not a summary this run computed.
        self.assertEqual(payload["health"], {P2: {"errors": 1}})
        self.assertNotIn(P1, payload["health"])
        self.assertEqual(payload["primary"], P1)
        self.assertEqual(payload["pool_size"], 3)

    def test_health_transitions_are_visible_across_rotations(self):
        td, ledger = _ledger()
        self.addCleanup(td.cleanup)
        router = _router(ledger)

        router.note_model_result(P2, ok=False)
        router.apply_pool
        router.note_model_result(P2, ok=False)
        router.apply_pool
        first, second = read_rotations(ledger, lane="apply")[-2:]
        self.assertEqual(first["health"][P2]["errors"], 1)
        self.assertEqual(second["health"][P2]["errors"], 2)

        # A success walks the count back down (the ranker's own rule), and the
        # next rotation records the walked-back value.
        router.note_model_result(P2, ok=True)
        router.note_model_result(P2, ok=True)
        router.apply_pool
        third = read_rotations(ledger, lane="apply")[-1]
        self.assertEqual(third["health"][P2]["errors"], 0)

    def test_an_unobserved_pool_records_no_health_and_no_ranking(self):
        """Unknown values are absent, never fabricated."""
        td, ledger = _ledger()
        self.addCleanup(td.cleanup)
        router = _router(ledger)

        ordered = router.apply_pool
        self.assertEqual(ordered, [P1, P2, JUDGE])
        payload = read_rotations(ledger, lane="apply")[-1]
        self.assertIs(payload["ranked"], False)
        self.assertNotIn("health", payload)
        self.assertEqual(payload["ordered"], payload["declared"])

    def test_a_pool_with_one_member_is_not_a_rotation(self):
        td, ledger = _ledger()
        self.addCleanup(td.cleanup)
        router = _router(ledger, pool=[P1])
        self.assertEqual(router.apply_pool, [P1])
        self.assertEqual(read_rotations(ledger, lane="apply"), [])


class OneHomeTests(unittest.TestCase):
    def test_rows_are_the_existing_trace_family_not_a_new_stream(self):
        td, ledger = _ledger()
        self.addCleanup(td.cleanup)
        router = _router(ledger)
        router.note_model_result(P2, ok=False)
        router.apply_pool

        events = ledger.entries()
        self.assertEqual({e["event"] for e in events}, {"decision_trace"})
        kinds = {e["kind"] for e in events}
        self.assertEqual(kinds, {ROTATION_EVENT})
        # The same reader the trace family already has sees them.
        same = read_trace_events(ledger, kinds=[ROTATION_EVENT])
        self.assertEqual(len(same), len(read_rotations(ledger)))

    def test_no_trace_means_no_row_and_unchanged_routing(self):
        td, ledger = _ledger()
        self.addCleanup(td.cleanup)
        router = Router(panel=[P1], judge=JUDGE, apply_model=P1,
                        apply_pool=[P1, P2, JUDGE], use_free=True)
        router.note_model_result(P2, ok=False)
        self.assertEqual(router.apply_pool, [P1, JUDGE, P2])
        self.assertEqual(ledger.entries(), [])

    def test_session_wiring_records_on_the_runs_own_ledger(self):
        from harness.config import load_settings
        from harness.session import router_for

        td, ledger = _ledger()
        self.addCleanup(td.cleanup)
        settings = load_settings({"panel": [P1], "judge": JUDGE,
                                  "apply_model": P1})
        router = router_for(settings, ledger=ledger)
        self.assertIsNotNone(router.trace)
        router.note_model_result(P2, ok=False)
        router.apply_pool
        self.assertTrue(read_rotations(ledger))


class McpAssemblyTests(unittest.TestCase):
    """#683 row 68: the MCP entry hands the router the run's own ledger."""

    def test_the_mcp_entry_passes_its_ledger_to_the_router(self):
        from unittest import mock

        from harness import mcp, session
        from harness.config import load_settings

        td, ledger = _ledger()
        self.addCleanup(td.cleanup)
        settings = load_settings({"panel": [P1], "judge": JUDGE,
                                  "apply_model": P1})
        captured = {}

        class _Server:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def serve_forever(self):
                return None

        with mock.patch.object(mcp, "load_settings", return_value=settings), \
                mock.patch.object(mcp, "McpServer", _Server), \
                mock.patch.object(mcp, "resolve_hourglass", return_value=None), \
                mock.patch.object(session, "HttpTransport"), \
                mock.patch.object(session, "governor_for",
                                  return_value=("key", mock.Mock())), \
                mock.patch.object(session, "ledger_for", return_value=ledger), \
                mock.patch.object(session, "pre_run_warning"), \
                mock.patch.object(session, "engine_for",
                                  return_value=mock.Mock()):
            self.assertIsNone(mcp.main([]))

        router = captured["router"]
        self.assertIsNotNone(router.trace)
        self.assertIs(router.trace.ledger, ledger)
        router.note_model_result(P2, ok=False)
        router.apply_pool
        self.assertTrue(read_rotations(ledger))


class LegacyToleranceTests(unittest.TestCase):
    def test_a_ledger_written_before_473_reads_as_no_rotations(self):
        td, ledger = _ledger()
        self.addCleanup(td.cleanup)
        ledger.ensure_offered_task_id("t1", model="(agent)", source="test_setup")
        ledger.append("model_result", task_id="t1", status="ok", cost=0.0)
        self.assertEqual(read_rotations(ledger), [])
        self.assertEqual(read_trace_events(ledger, kinds=[ROTATION_EVENT]), [])

    def test_a_rotation_row_without_health_still_reads(self):
        td, ledger = _ledger()
        self.addCleanup(td.cleanup)
        DecisionTrace(ledger).record(ROTATION_EVENT, payload={
            "lane": "apply", "declared": [P1, P2], "ordered": [P1, P2],
            "ranked": False, "pool_size": 2, "primary": P1})
        row = read_rotations(ledger)[0]
        self.assertEqual(row["lane"], "apply")
        self.assertNotIn("health", row)


if __name__ == "__main__":
    unittest.main()
