"""Tier-0 chunking policy owner (#308).

``tests/test_waist.py`` already pins the policy's user-visible behaviour
through the waist's compatibility re-export. These tests pin the owner's own
edges -- the measurements and the split helpers a plan reaches only when a
node cannot fit one pass -- so the module that now owns the policy is covered
where it lives.
"""
import os
import tempfile
import unittest
from types import SimpleNamespace

from harness.config import DEFAULT_APPLY_MAX_TOKENS
from harness.dag import DAGNode, TaskDAG
from harness.plan_chunker import (
    _line_ranges,
    _passes_to_read,
    _slice_marker,
    _split_text,
    _target_text,
    chunk_oversized_nodes,
    rung_read_budgets,
    single_pass_output_tokens,
)


class SinglePassOutputTokensTests(unittest.TestCase):
    def test_pinned_budget_wins(self):
        self.assertEqual(single_pass_output_tokens(4096), 4096)

    def test_missing_or_unusable_budget_falls_back_to_the_apply_default(self):
        for value in (None, "not-a-number", 0, -5):
            with self.subTest(value=value):
                self.assertEqual(single_pass_output_tokens(value),
                                 DEFAULT_APPLY_MAX_TOKENS)


class SplitTextTests(unittest.TestCase):
    def test_word_boundary_split_loses_nothing(self):
        text = "alpha beta gamma delta epsilon zeta eta theta"
        parts = _split_text(text, 12)
        self.assertEqual(" ".join(parts), text)
        for part in parts:
            self.assertLessEqual(len(part), 12)

    def test_unbreakable_token_is_hard_split(self):
        text = "x" * 25
        parts = _split_text(text, 10)
        self.assertEqual("".join(parts), text)
        self.assertTrue(all(len(part) <= 10 for part in parts))

    def test_pending_piece_closes_before_a_hard_split(self):
        parts = _split_text("ab " + "x" * 25, 10)
        # Only the whitespace at the break point is trimmed.
        self.assertEqual(parts[0], "ab")
        self.assertEqual("".join(parts[1:]), "x" * 25)
        self.assertTrue(all(len(part) <= 10 for part in parts))

    def test_empty_text_still_yields_one_piece(self):
        self.assertEqual(_split_text("", 10), [""])


class TargetTextTests(unittest.TestCase):
    def test_absolute_and_relative_targets_are_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "target.py")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("value = 1\n")
            self.assertEqual(_target_text(None, path), "value = 1\n")
            self.assertEqual(_target_text(tmp, "target.py"), "value = 1\n")

    def test_unreadable_target_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(_target_text(tmp, "absent.py"))


class PassesToReadTests(unittest.TestCase):
    def test_unmeasured_budget_never_invents_a_split(self):
        self.assertEqual(_passes_to_read("x = 1\n" * 100, 0), 1)

    def test_measured_budget_scales_with_the_file(self):
        text = "x = 1\n" * 400
        self.assertGreater(_passes_to_read(text, 50), 1)


class RungReadBudgetsTests(unittest.TestCase):
    def test_each_node_reads_its_own_rung_context(self):
        profiles = {"m/roomy": SimpleNamespace(context_length=262144)}
        plan = {"nodes": (
            "not-a-dict",
            {"node_id": "task_1", "route": {"ladder": ["m/roomy"]}},
            {"node_id": "task_2", "route": {"ladder": ["m/unknown"]}},
            {"node_id": "task_3", "route": None},
        )}
        budgets = rung_read_budgets(plan, profiles=profiles)
        self.assertGreater(budgets["task_1"], 0)
        self.assertEqual(budgets["task_2"], 0)
        self.assertEqual(budgets["task_3"], 0)


class LineRangesTests(unittest.TestCase):
    def test_ranges_cover_the_file_exactly_once(self):
        self.assertEqual(_line_ranges(10, 2), [(1, 5), (6, 10)])

    def test_tail_passes_share_the_last_slice(self):
        self.assertEqual(_line_ranges(2, 4), [(1, 1), (2, 2), (2, 2), (2, 2)])

    def test_zero_line_file_still_names_a_range_per_pass(self):
        self.assertEqual(_line_ranges(0, 2), [(1, 1), (1, 1)])


class ChunkOversizedNodesEdgesTests(unittest.TestCase):
    def test_empty_dag_is_returned_unchanged(self):
        dag = TaskDAG(nodes={})
        self.assertIs(chunk_oversized_nodes(dag), dag)

    def test_instruction_only_node_splits_without_a_range_marker(self):
        text = "Rewrite the scheduler so passes stay ordered. " * 80
        dag = TaskDAG(nodes={"task_1": DAGNode(
            node_id="task_1", instruction=text)})
        fitted = chunk_oversized_nodes(dag)
        chunks = list(fitted.nodes.values())
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertIn("[pass ", chunk.instruction)
            self.assertNotIn("apply ONLY", chunk.instruction)
            self.assertIsNone(chunk.backend)

    def test_node_that_already_names_a_backend_keeps_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "big.py"), "w", encoding="utf-8") as handle:
                handle.write("".join(f"line_{i} = {i}\n" for i in range(1300)))
            dag = TaskDAG(nodes={"task_1": DAGNode(
                node_id="task_1", instruction="Rename the helper",
                target_files=("big.py",), backend="patch")})
            fitted = chunk_oversized_nodes(dag, root=tmp)
        self.assertIs(fitted, dag)
        self.assertEqual(fitted.nodes["task_1"].backend, "patch")

    def test_int_source_budget_applies_to_every_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "big.py"), "w", encoding="utf-8") as handle:
                handle.write("".join(f"line_{i} = {i}\n" for i in range(1300)))
            dag = TaskDAG(nodes={"task_1": DAGNode(
                node_id="task_1", instruction="Rename the helper",
                target_files=("big.py",))})
            fitted = chunk_oversized_nodes(dag, root=tmp, source_tokens=1000)
        self.assertGreater(len(fitted.nodes), 1)


class SliceMarkerTests(unittest.TestCase):
    def test_longest_marker_reserves_the_last_slice(self):
        marker = _slice_marker(3, [(1, 10), (11, 20), (21, 30)], "a.py")
        self.assertIn("pass 3/3", marker)
        self.assertIn("apply ONLY a.py lines 21-30 of 30", marker)

    def test_instruction_only_marker_names_no_range(self):
        self.assertEqual(_slice_marker(2, [], None, index=1),
                         "\n\n[pass 1/2]")


if __name__ == "__main__":
    unittest.main()
