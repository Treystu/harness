"""harness.orchestrator: the completion judge and the relevance first pass.

Hermetic: every model seam is the injected ``chat_fn`` (the same contract as
``dag.decompose_via_llm``). Pins the strict-JSON verdict schema, loud
degradation to None, hallucination-proof triage (picks validated against the
real listing), and the keyword fallback."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from harness import orchestrator as orch
from harness.errors import HarnessError
from harness.jev import JevEvaluationResult
from harness.jev_packs import validate_restart_request
from harness.restart_policy import (
    RestartStateStore,
    consume_restart_decision,
)


class ResultProbabilityTests(unittest.TestCase):
    def test_non_dict_answers_is_none(self):
        result = JevEvaluationResult("pass", 0.0, 1.0, None, [])
        self.assertIsNone(orch._result_probability(result, "goal_achieved"))

    def test_noul_wrapped_and_bare_values(self):
        wrapped = JevEvaluationResult(
            "pass", 0.0, 1.0, {"goal_achieved": {"noul": 0.75}}, [])
        self.assertAlmostEqual(
            orch._result_probability(wrapped, "goal_achieved"), 0.75)
        bare = JevEvaluationResult(
            "pass", 0.0, 1.0, {"goal_achieved": 0.4}, [])
        self.assertAlmostEqual(
            orch._result_probability(bare, "goal_achieved"), 0.4)

    def test_non_numeric_or_bool_value_is_none(self):
        boolean = JevEvaluationResult(
            "pass", 0.0, 1.0, {"goal_achieved": True}, [])
        self.assertIsNone(orch._result_probability(boolean, "goal_achieved"))
        stringy = JevEvaluationResult(
            "pass", 0.0, 1.0, {"goal_achieved": "yes"}, [])
        self.assertIsNone(orch._result_probability(stringy, "goal_achieved"))

    def test_value_is_clamped_to_unit_range(self):
        over = JevEvaluationResult(
            "pass", 0.0, 1.0, {"goal_achieved": 1.5}, [])
        self.assertEqual(orch._result_probability(over, "goal_achieved"), 1.0)


class AssessCompletionTests(unittest.TestCase):
    def test_complete_verdict_parsed(self):
        def chat_fn(prompt):
            self.assertIn("completion judge", prompt)
            return 'noise {"complete": true, "remaining": "", "reason": "gates green"} trailing'
        v = orch.assess_completion("the goal", "- subtask n1 status=ok", chat_fn)
        self.assertTrue(v["complete"])
        self.assertEqual(v["reason"], "gates green")

    def test_incomplete_verdict_carries_remaining_scope(self):
        def chat_fn(prompt):
            return '{"complete": false, "remaining": "the second half", "reason": "partial"}'
        v = orch.assess_completion("the goal", "state", chat_fn)
        self.assertFalse(v["complete"])
        self.assertEqual(v["remaining"], "the second half")

    def test_unusable_response_is_none_not_an_invention(self):
        for bad in (None, "", "no json here", "[1, 2]", '{"complete": "yes"}'):
            self.assertIsNone(orch.assess_completion("g", "s", lambda p: bad))

    def test_judge_model_failure_propagates_as_harness_error(self):
        def chat_fn(prompt):
            raise HarnessError("HTTP 429")
        with self.assertRaises(HarnessError):
            orch.assess_completion("g", "s", chat_fn)

    def test_thinking_tags_and_braces_in_strings(self):
        def chat_fn(prompt):
            return '<think>Thinking {draft: false}</think> {"complete": true, "remaining": "", "reason": "handled { braces } cleanly"}'
        v = orch.assess_completion("the goal", "state", chat_fn)
        self.assertIsNotNone(v)
        self.assertTrue(v["complete"])
        self.assertEqual(v["reason"], "handled { braces } cleanly")


class DriveTruthTests(unittest.TestCase):
    def test_failed_node_overrides_complete_judge(self):
        plan = {"total_nodes": 1, "total_cost_ceiling": 0.0,
                "nodes": [{"node_id": "n1", "instruction": "edit",
                            "target_files": ["a.py"]}],
                "dag": {"nodes": [{"node_id": "n1"}]}}
        driven = orch.drive(
            goal="edit a.py", target_files=[], initial_plan=plan,
            root_dir=".", plan_round=lambda goal: plan,
            execute_plan=lambda current: {"n1": {"status": "failed"}},
            completion_chat=lambda prompt: '{"complete": true}',
            emit=lambda *args, **kwargs: None)
        self.assertFalse(driven["final_all_ok"])
        self.assertIn("did not complete", driven["remaining_scope"])

    def test_jev_completion_threshold_requires_another_round(self):
        plan = {"total_nodes": 1, "total_cost_ceiling": 0.0,
                "nodes": [{"node_id": "n1", "instruction": "edit",
                            "target_files": ["a.py"]}],
                "dag": {"nodes": [{"node_id": "n1"}]}}

        class _FakeJevPolicy:
            def evaluate_completion_nouls(self, goal, state_summary, *,
                                          named_artifacts=None, root_dir=None,
                                          site="completion"):
                result = JevEvaluationResult(
                    "pass", 0.0, 0.5, {"goal_achieved": 0.5}, [],
                    is_fallback=False, model="jev-test")
                return result, {"cannot_complete": False,
                               "missing_artifacts": []}

        events = []
        driven = orch.drive(
            goal="edit a.py", target_files=[], initial_plan=plan,
            root_dir=".", plan_round=lambda goal: plan,
            execute_plan=lambda current: {"n1": {"status": "ok"}},
            completion_chat=lambda prompt: '{"complete": true}',
            emit=lambda *args, **kwargs: events.append((args, kwargs)),
            jev_policy=_FakeJevPolicy(), jev_completion_threshold=0.99,
            max_rounds=1)

        self.assertFalse(driven["final_all_ok"])
        self.assertIn("Jev completion support 0.500", driven["remaining_scope"])
        self.assertIn("below the required 0.990", driven["remaining_scope"])
        self.assertEqual(driven["rounds_history"][-1]["jev"],
                         {"native": True, "supported": 0.5,
                          "cannot_complete": False,
                          "reason": "completion nouls passed",
                          "fallback_reason": None})

    def test_round_metadata_preserves_completion_fallback_reason(self):
        plan = {"total_nodes": 1, "total_cost_ceiling": 0.0,
                "nodes": [{"node_id": "n1", "instruction": "edit",
                            "target_files": ["a.py"]}],
                "dag": {"nodes": [{"node_id": "n1"}]}}

        class _FakeJevPolicy:
            def evaluate_completion_nouls(self, goal, state_summary, *,
                                          named_artifacts=None, root_dir=None,
                                          site="completion"):
                result = JevEvaluationResult(
                    "fail", 0.0, 0.0, {}, ["key unavailable"],
                    is_fallback=True, model="jev-test",
                    fallback_reason="transport_failure")
                return result, {"cannot_complete": False,
                                "missing_artifacts": []}

        driven = orch.drive(
            goal="edit a.py", target_files=[], initial_plan=plan,
            root_dir=".", plan_round=lambda goal: plan,
            execute_plan=lambda current: {"n1": {"status": "ok"}},
            completion_chat=lambda prompt: '{"complete": true}',
            emit=lambda *args, **kwargs: None,
            jev_policy=_FakeJevPolicy(), max_rounds=1)
        self.assertEqual(driven["rounds_history"][-1]["jev"]["fallback_reason"],
                         "transport_failure")

    def test_jev_native_support_at_threshold_falls_through_to_judge(self):
        plan = {"total_nodes": 1, "total_cost_ceiling": 0.0,
                "nodes": [{"node_id": "n1", "instruction": "edit",
                            "target_files": ["a.py"]}],
                "dag": {"nodes": [{"node_id": "n1"}]}}

        class _FakeJevPolicy:
            def evaluate_completion_nouls(self, goal, state_summary, *,
                                          named_artifacts=None, root_dir=None,
                                          site="completion"):
                result = JevEvaluationResult(
                    "pass", 0.0, 0.995, {"goal_achieved": 0.995}, [],
                    is_fallback=False, model="jev-test")
                return result, {"cannot_complete": False,
                               "missing_artifacts": []}

        driven = orch.drive(
            goal="improve the widget", target_files=[], initial_plan=plan,
            root_dir=".", plan_round=lambda goal: plan,
            execute_plan=lambda current: {"n1": {"status": "ok"}},
            completion_chat=lambda prompt: '{"complete": true}',
            emit=lambda *args, **kwargs: None,
            jev_policy=_FakeJevPolicy(), jev_completion_threshold=0.99,
            max_rounds=1)

        self.assertTrue(driven["final_all_ok"])


class TriageFilesTests(unittest.TestCase):
    _FILES = ["harness/agent.py", "harness/dag.py", "harness/web.py",
              "tests/test_agent.py", "README.md"]

    def test_picks_validated_against_real_listing(self):
        def chat_fn(prompt):
            self.assertIn("harness/dag.py", prompt)
            return ('{"files": ["harness/dag.py", "harness/ghost.py", '
                    '"harness/agent.py", "harness/dag.py"]}')
        picked = orch.triage_files("fix the dag planner", self._FILES, chat_fn)
        # hallucinated ghost.py dropped, duplicate dag.py dropped, order kept
        self.assertEqual(picked, ["harness/dag.py", "harness/agent.py"])

    def test_model_failure_returns_empty_for_caller_fallback(self):
        def chat_fn(prompt):
            raise HarnessError("no model")
        self.assertEqual(orch.triage_files("g", self._FILES, chat_fn), [])

    def test_cap_enforced(self):
        files = [f"f{i}.py" for i in range(40)]
        blob = ", ".join(f'"f{i}.py"' for i in range(40))
        def chat_fn(prompt):
            return '{"files": [' + blob + "]}"
        picked = orch.triage_files("g", files, chat_fn)
        self.assertEqual(len(picked), orch.MAX_TRIAGE_FILES)

    def test_empty_listing_short_circuits(self):
        self.assertEqual(orch.triage_files("g", [], lambda p: '["x"]'), [])


class KeywordFallbackTests(unittest.TestCase):
    def test_keyword_overlap_ranks_and_caps(self):
        files = ["harness/spend.py", "harness/dag.py", "harness/spend_gov.py",
                 "README.md"]
        picked = orch.keyword_fallback("fix the spend governor ceiling",
                                       files, max_files=2)
        self.assertNotIn("harness/dag.py", picked)
        self.assertNotIn("README.md", picked)
        self.assertEqual(len(picked), 2)
        self.assertTrue(all("spend" in p for p in picked))

    def test_no_overlap_returns_empty(self):
        self.assertEqual(orch.keyword_fallback("quantum toaster repair",
                                               ["harness/dag.py"]), [])


class BuildStateSummaryTests(unittest.TestCase):
    def test_renders_node_statuses_and_notes_bounded(self):
        summary = orch.build_state_summary(
            [{"node_id": "n1", "file_path": "a.py",
                      "status": "verify_failed", "error": "boom"}] * 200,
            extra_notes=["round 1"])
        self.assertIn("n1", summary)
        self.assertIn("verify_failed", summary)
        self.assertIn("round 1", summary)
        self.assertLessEqual(len(summary), 8000)

    def test_navigation_only_label_and_content_render_bounded(self):
        summary = orch.build_state_summary(
            [{"node_id": "n1", "file_path": "a.py",
              "status": "ok", "error": ""}],
            extra_notes=["orchestrator round 1 of 3",
                         orch._SUMMARY_NAVIGATION_ONLY_NOTE,
                         "content: a.py (10 bytes on disk, 10 chars, "
                         "2 lines, complete):\nx = 1\n"])
        self.assertIn("navigation-only", summary)
        self.assertIn("content: a.py", summary)
        self.assertLessEqual(len(summary), 8000)


class DeliverableContentEvidenceTests(unittest.TestCase):
    def _tmp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        return td, Path(td.name)

    def test_included_file_declares_exact_counts(self):
        _, root = self._tmp()
        body = "a = 1\nb = 2\n"
        # Bytes, not write_text: the platform newline translation would
        # otherwise rewrite the counts this test pins.
        (root / "w.py").write_bytes(body.encode("utf-8"))
        ev = orch.deliverable_content_evidence(["w.py"], root)
        self.assertEqual(ev["unavailable"], [])
        (chunk,) = ev["chunks"]
        self.assertEqual(chunk["status"], "included")
        self.assertEqual(chunk["chars_total"], len(body))
        self.assertEqual(chunk["excerpt_start"], 0)
        self.assertEqual(chunk["excerpt_chars"], len(body))
        self.assertFalse(chunk["truncated"])
        self.assertIn("a = 1", ev["text"])
        self.assertIn("complete", ev["text"])
        self.assertIn(str(len(body)), ev["text"])

    def test_fair_share_splits_pool_and_declares_truncation(self):
        _, root = self._tmp()
        (root / "a.py").write_text("A" * 200, encoding="utf-8")
        (root / "b.md").write_text("B" * 200, encoding="utf-8")
        with mock.patch.object(orch, "_DELIVERABLE_CONTENT_TOTAL_CHARS", 100), \
                mock.patch.object(orch, "_DELIVERABLE_CONTENT_PER_FILE_CHARS",
                                  1000):
            ev = orch.deliverable_content_evidence(["a.py", "b.md"], root)
        self.assertEqual(len(ev["chunks"]), 2)
        for chunk in ev["chunks"]:
            self.assertEqual(chunk["status"], "included")
            self.assertTrue(chunk["truncated"])
            # Fair share of 100 across 2 files: 50 chars each.
            self.assertEqual(chunk["excerpt_chars"], 50)
        self.assertIn("TRUNCATED", ev["text"])
        self.assertIn("A" * 50, ev["text"])
        self.assertNotIn("A" * 51, ev["text"])
        self.assertIn("B" * 50, ev["text"])

    def test_traversal_duplicates_and_empty_are_skipped(self):
        _, root = self._tmp()
        (root / "a.py").write_text("x\n", encoding="utf-8")
        ev = orch.deliverable_content_evidence(
            ["../evil.py", "a.py", "a.py", ""], root)
        self.assertEqual([c["path"] for c in ev["chunks"]], ["a.py"])
        self.assertEqual(ev["unavailable"], [])

    def test_absolute_path_outside_root_is_unsafe(self):
        _, root = self._tmp()
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        secret = Path(outside.name) / "secret.py"
        secret.write_text("hidden = True\n", encoding="utf-8")
        ev = orch.deliverable_content_evidence([str(secret)], root)
        (chunk,) = ev["chunks"]
        self.assertEqual(chunk["status"], "unsafe")
        self.assertEqual(len(ev["unavailable"]), 1)
        self.assertIn("outside", ev["unavailable"][0]["reason"])
        self.assertIn("UNAVAILABLE", ev["text"])

    def test_symlink_escape_is_unsafe(self):
        _, root = self._tmp()
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        target = Path(outside.name) / "real.py"
        target.write_text("v = 1\n", encoding="utf-8")
        try:
            os.symlink(str(target), str(root / "link.py"))
        except OSError:
            self.skipTest("symlinks unavailable on this platform")
        ev = orch.deliverable_content_evidence(["link.py"], root)
        (chunk,) = ev["chunks"]
        self.assertEqual(chunk["status"], "unsafe")
        self.assertEqual(len(ev["unavailable"]), 1)

    def test_too_large_is_declared_unavailable(self):
        _, root = self._tmp()
        (root / "big.py").write_text("x" * 100, encoding="utf-8")
        with mock.patch.object(orch, "_DELIVERABLE_CONTENT_MAX_BYTES", 10):
            ev = orch.deliverable_content_evidence(["big.py"], root)
        (chunk,) = ev["chunks"]
        self.assertEqual(chunk["status"], "too-large")
        self.assertEqual(chunk["size_bytes"], 100)
        self.assertEqual(len(ev["unavailable"]), 1)
        self.assertIn("per-file bound", ev["unavailable"][0]["reason"])

    def test_changed_during_read_is_refused(self):
        # Genuine growth between the pre-read size check and the post-read
        # size check: the file really grows mid-call (no stat-call counting,
        # which breaks across interpreters - 3.11's Path.resolve() makes its
        # own stat calls through the same attribute and shifts the sequence).
        _, root = self._tmp()
        target = root / "w.py"
        target.write_text("x = 1\n", encoding="utf-8")
        real_open = open
        grew = {"done": False}

        def growing_open(file, mode="r", *args, **kwargs):
            if (not grew["done"] and "b" in str(mode)
                    and str(Path(file)) == str(target)):
                with real_open(file, "ab") as handle:
                    handle.write(b"#" * 64)
                grew["done"] = True
            return real_open(file, mode, *args, **kwargs)

        with mock.patch("builtins.open", growing_open):
            ev = orch.deliverable_content_evidence(["w.py"], root)
        self.assertTrue(grew["done"], "the read path must open the file")
        (chunk,) = ev["chunks"]
        self.assertEqual(chunk["status"], "changed-during-read")
        self.assertEqual(len(ev["unavailable"]), 1)
        self.assertIn("refusing excerpt", ev["unavailable"][0]["reason"])

    def test_empty_home_and_posix_absolute_names_are_unsafe(self):
        # Blank names never reach the reader (skipped in the names loop);
        # home/posix roots reach _safe_content_path and refuse there.
        _, root = self._tmp()
        ev = orch.deliverable_content_evidence(["", "~/x.py", "/abs/x.py"], root)
        self.assertEqual(
            [c["status"] for c in ev["chunks"]], ["unsafe", "unsafe"])
        self.assertEqual(len(ev["unavailable"]), 2)
        self.assertTrue(all("outside the deliverable root" in u["reason"]
                            for u in ev["unavailable"]))
        # Blank and traversal names refuse inside _safe_content_path itself.
        self.assertIsNone(orch._safe_content_path(root, ""))
        self.assertIsNone(orch._safe_content_path(root, ".."))
        self.assertIsNone(orch._safe_content_path(root, "../x.py"))

    def test_unresolvable_root_is_unsafe(self):
        # A root that cannot be resolved fails closed (D12: resolve OSError).
        _, root = self._tmp()
        (root / "ok.py").write_text("x = 1\n", encoding="utf-8")
        with mock.patch.object(Path, "resolve", side_effect=OSError("gone")):
            ev = orch.deliverable_content_evidence(["ok.py"], root)
        (chunk,) = ev["chunks"]
        self.assertEqual(chunk["status"], "unsafe")
        self.assertEqual(len(ev["unavailable"]), 1)

    def test_containment_failure_is_unsafe(self):
        # A name that resolves outside the deliverable root fails closed
        # (D12: relative_to ValueError; exercised without symlinks so the
        # guarantee holds on platforms without them).
        _, root = self._tmp()
        (root / "ok.py").write_text("x = 1\n", encoding="utf-8")
        real_relative_to = Path.relative_to

        def outside(self, *args):
            if str(self).endswith("ok.py"):
                raise ValueError("outside")
            return real_relative_to(self, *args)

        with mock.patch.object(Path, "relative_to", outside):
            ev = orch.deliverable_content_evidence(["ok.py"], root)
        (chunk,) = ev["chunks"]
        self.assertEqual(chunk["status"], "unsafe")
        self.assertEqual(len(ev["unavailable"]), 1)
        self.assertIn("outside the deliverable root",
                      ev["unavailable"][0]["reason"])

    def test_directory_is_not_supplied_as_text(self):
        # Directories are not regular files (D12: not-regular branch).
        _, root = self._tmp()
        (root / "pkg").mkdir()
        ev = orch.deliverable_content_evidence(["pkg"], root)
        (chunk,) = ev["chunks"]
        self.assertEqual(chunk["status"], "not-regular")
        self.assertEqual(len(ev["unavailable"]), 1)
        self.assertIn("not a regular file", ev["unavailable"][0]["reason"])

    def test_unreadable_file_is_declared_not_supplied(self):
        # An unreadable file is declared, not silently skipped (D12).
        _, root = self._tmp()
        target = root / "locked.py"
        target.write_text("x = 1\n", encoding="utf-8")
        real_open = open

        def failing_open(file, *args, **kwargs):
            if str(Path(file)) == str(target):
                raise OSError("denied")
            return real_open(file, *args, **kwargs)

        with mock.patch("builtins.open", failing_open):
            ev = orch.deliverable_content_evidence(["locked.py"], root)
        (chunk,) = ev["chunks"]
        self.assertEqual(chunk["status"], "unreadable")
        self.assertEqual(len(ev["unavailable"]), 1)
        self.assertIn("unreadable", ev["unavailable"][0]["reason"])

    def test_binary_is_not_supplied_as_text(self):
        _, root = self._tmp()
        (root / "img.py").write_bytes(b"\x89PNG\r\n\x00bindata")
        ev = orch.deliverable_content_evidence(["img.py"], root)
        (chunk,) = ev["chunks"]
        self.assertEqual(chunk["status"], "binary")
        self.assertEqual(len(ev["unavailable"]), 1)
        self.assertIn("binary", ev["unavailable"][0]["reason"])

    def test_missing_is_declared_not_unavailable(self):
        _, root = self._tmp()
        ev = orch.deliverable_content_evidence(["nope.py"], root)
        (chunk,) = ev["chunks"]
        self.assertEqual(chunk["status"], "missing")
        # Artifact truth owns missing files; the content reader stays silent.
        self.assertEqual(ev["unavailable"], [])
        self.assertIn("artifact truth owns missing files", ev["text"])


class DriveContentTruthTests(unittest.TestCase):
    def _drive(self, goal, target_files, root, execute_result, chat_fn,
               jev_policy=None, max_rounds=1):
        plan = {"total_nodes": 1, "total_cost_ceiling": 0.0,
                "nodes": [{"node_id": "n1", "instruction": "edit",
                            "target_files": target_files}],
                "dag": {"nodes": [{"node_id": "n1"}]}}
        events = []
        driven = orch.drive(
            goal=goal, target_files=target_files, initial_plan=plan,
            root_dir=root, plan_round=lambda goal: plan,
            execute_plan=lambda current: dict(execute_result),
            completion_chat=chat_fn,
            emit=lambda *args, **kwargs: events.append((args, kwargs)),
            jev_policy=jev_policy, max_rounds=max_rounds)
        return driven, events

    def test_content_defect_invisible_in_summary_flips_verdict(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        (root / "widget.py").write_text(
            "def run():\n    pass  # off-by-one: skips last item\n",
            encoding="utf-8")
        prompts = []

        def chat_fn(prompt):
            prompts.append(prompt)
            if "off-by-one" in prompt:
                return ('{"complete": false, "remaining": '
                        '"fix the off-by-one in widget.py", '
                        '"reason": "file content shows a defect"}')
            return '{"complete": true}'

        driven, _ = self._drive(
            "Fix widget.py", ["widget.py"], root,
            {"n1": {"status": "ok"}}, chat_fn)
        self.assertFalse(driven["final_all_ok"])
        self.assertIn("off-by-one", driven["remaining_scope"])
        # The defect reached the judge inside file content, and the summary
        # around it is labeled navigation-only.
        self.assertTrue(any("off-by-one" in p for p in prompts))
        self.assertTrue(all("navigation-only" in p for p in prompts))
        # The old evidence alone (status lines, no content) hides the defect,
        # so the same specimen would have passed before this change.
        old_summary = orch.build_state_summary(
            [{"node_id": "n1", "file_path": "widget.py", "status": "ok",
              "error": ""}],
            extra_notes=["orchestrator round 1 of 1"])
        self.assertNotIn("off-by-one", old_summary)

    def test_unavailable_content_overrides_complete_verdict(self):
        root_td = tempfile.TemporaryDirectory()
        self.addCleanup(root_td.cleanup)
        outside_td = tempfile.TemporaryDirectory()
        self.addCleanup(outside_td.cleanup)
        secret = Path(outside_td.name) / "secret.py"
        secret.write_text("present = True\n", encoding="utf-8")

        def chat_fn(prompt):
            return '{"complete": true}'

        driven, events = self._drive(
            "Ship the deliverable", [str(secret)], Path(root_td.name),
            {"n1": {"status": "ok"}}, chat_fn)
        self.assertFalse(driven["final_all_ok"])
        self.assertIn("outside the deliverable root",
                      driven["remaining_scope"])
        notes = [kw.get("note", "") for _, kw in events]
        self.assertTrue(any("overriding to incomplete" in n for n in notes))

    def test_content_unavailable_with_policy_skips_generative_judge(self):
        root_td = tempfile.TemporaryDirectory()
        self.addCleanup(root_td.cleanup)
        outside_td = tempfile.TemporaryDirectory()
        self.addCleanup(outside_td.cleanup)
        secret = Path(outside_td.name) / "secret.py"
        secret.write_text("present = True\n", encoding="utf-8")

        class _FakeJevPolicy:
            def evaluate_completion_nouls(self, goal, state_summary, *,
                                          named_artifacts=None, root_dir=None,
                                          site="completion"):
                result = JevEvaluationResult(
                    "pass", 0.0, 0.5, {"goal_achieved": 0.5}, [],
                    is_fallback=False, model="jev-test")
                return result, {"cannot_complete": False,
                                "missing_artifacts": []}

        judge_calls = []
        driven, _ = self._drive(
            "Ship the deliverable", [str(secret)], Path(root_td.name),
            {"n1": {"status": "ok"}},
            lambda prompt: (judge_calls.append(prompt)
                            or '{"complete": true}'),
            jev_policy=_FakeJevPolicy())
        self.assertFalse(driven["final_all_ok"])
        self.assertEqual(judge_calls, [])
        self.assertIn("deliverable content unavailable",
                      driven["remaining_scope"])
        self.assertFalse(
            driven["rounds_history"][-1]["jev"]["cannot_complete"])

    def test_final_gate_output_reaches_judge(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        (root / "a.py").write_text("x = 1\n", encoding="utf-8")
        prompts = []
        driven, _ = self._drive(
            "Write a.py", ["a.py"], root,
            {"n1": {"status": "ok"},
             "final_gate": {"status": "ok", "node_id": "final_gate",
                            "gate": "pytest -q", "returncode": 0,
                            "output": "3 passed, 0 failed", "cost": 0.0}},
            lambda prompt: (prompts.append(prompt)
                            or '{"complete": true}'))
        self.assertTrue(driven["final_all_ok"])
        self.assertTrue(any("3 passed, 0 failed" in p for p in prompts))
        self.assertTrue(any("verification final_gate" in p
                            for p in prompts))


class DriveRestartTransitionTests(unittest.TestCase):
    """Slice 2 (#459): the restart-target controller reads judgment["restart"].

    Hermetic: every restart decision below is built only through the real
    guard (``validate_restart_request``) and the real store
    (``RestartStateStore``); every drive seam (plan/execute/judge/emit plus
    the two transition hooks) is an injected fake. Pins: a paused round
    re-enters at the declared target with preserved evidence, re-preflighted
    budgets, and renewed consent; a refused or blocked restart keeps the
    pause; an absent decision keeps the slice-1 pause exactly.
    """

    def _root(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        (root / "a.py").write_text("x = 1\n", encoding="utf-8")
        return root

    def _plan_with_restart(self, decision):
        return {"total_nodes": 1, "total_cost_ceiling": 0.0,
                "nodes": [{"node_id": "n1", "instruction": "edit",
                           "target_files": ["a.py"]}],
                "dag": {"nodes": [{"node_id": "n1"}]},
                "stage_judgments": {"execution": {"restart": decision}}}

    def _terminal(self, **overrides):
        params = {"request_id": None,
                  "assignment": {"goal": "Write a.py",
                                 "completed_stages": []},
                  "current_stage": "execution",
                  "requested_target": "planning",
                  "completed_stages": [],
                  "consent_fresh": None,
                  "checkpoint": {},
                  "prior_results": {}}
        params.update(overrides)
        return RestartStateStore().decide_restart(**params)

    def _allowed_restart(self):
        decision = validate_restart_request(
            "execution", "planning", completed_stages=[])
        self.assertTrue(decision["allowed"])
        decision["recommendation_source"] = "derived"
        decision["terminal_state"] = self._terminal()
        self.assertFalse(decision["terminal_state"]["terminal"])
        return decision

    def _blocked_restart(self):
        decision = validate_restart_request(
            "execution", "planning", completed_stages=["planning"])
        self.assertFalse(decision["allowed"])
        decision["recommendation_source"] = "derived"
        decision["terminal_state"] = self._terminal(
            assignment={"goal": "Write a.py",
                        "completed_stages": ["planning"]},
            completed_stages=["planning"])
        self.assertTrue(decision["terminal_state"]["terminal"])
        return decision

    def _drive(self, plan, scripts, judge='{"complete": true}',
               max_rounds=2, preflight_budget=None, renew_consent=None):
        root = self._root()
        goals, events = [], []
        calls = {"plan": 0, "execute": 0}

        def plan_round(goal):
            calls["plan"] += 1
            goals.append(goal)
            return plan

        def execute_plan(current):
            index = min(calls["execute"], len(scripts) - 1)
            calls["execute"] += 1
            return dict(scripts[index])

        driven = orch.drive(
            goal="Write a.py", target_files=["a.py"], initial_plan=plan,
            root_dir=root, plan_round=plan_round,
            execute_plan=execute_plan,
            completion_chat=lambda prompt: judge,
            emit=lambda *args, **kwargs: events.append((args, kwargs)),
            max_rounds=max_rounds, preflight_budget=preflight_budget,
            renew_consent=renew_consent)
        return driven, goals, events, calls

    def _notes(self, events):
        return [kw.get("note", "") for _, kw in events]

    # -- the paused round re-enters -----------------------------------------
    def test_allowed_restart_reenters_with_evidence_preflight_and_renewal(self):
        preflights, renewals = [], []
        driven, goals, events, calls = self._drive(
            self._plan_with_restart(self._allowed_restart()),
            [{"n1": {"status": "ok"},
              "n2": {"status": "deferred",
                     "reason": "consent deferred at checkpoint"}},
             {"n1": {"status": "ok"}}],
            preflight_budget=lambda transition: preflights.append(
                transition),
            renew_consent=lambda transition: renewals.append(transition))
        self.assertTrue(driven["final_all_ok"])
        # One re-entry: the paused round re-planned once and executed twice.
        self.assertEqual(calls, {"plan": 1, "execute": 2})
        # The re-entered round carries the declared target and the preserved
        # evidence (round-qualified node ids are drive's own addressing).
        self.assertEqual(len(goals), 1)
        self.assertIn("planning", goals[0])
        self.assertIn("r1/n1", goals[0])
        # Budgets re-preflighted and consent renewed through the hooks.
        self.assertEqual(len(preflights), 1)
        self.assertEqual(preflights[0]["target"], "planning")
        self.assertEqual(len(renewals), 1)
        self.assertEqual(renewals[0]["staleness_reason"],
                         "restart_targeted")
        # Completed evidence is preserved structurally, not replayed.
        self.assertIn("r1/n1", driven["all_results"])
        self.assertIn("r2/n1", driven["all_results"])
        restart = driven["rounds_history"][0]["restart"]
        self.assertTrue(restart["reentered"])
        self.assertEqual(restart["target"], "planning")
        self.assertEqual(restart["preserved_nodes"], ["r1/n1"])
        self.assertEqual(restart["staleness_reason"], "restart_targeted")
        self.assertFalse(restart["consent_renewal_required"])
        notes = self._notes(events)
        self.assertTrue(any("re-entering" in note for note in notes))
        self.assertTrue(any("budgets re-preflighted" in note
                            for note in notes))

    def test_reentry_without_hooks_still_marks_the_assignment_stale(self):
        # The hooks are observability/wiring points, not the safety itself:
        # the re-entered assignment carries the restart target, so the
        # staleness owner forces downstream consent re-derivation.
        driven, goals, _, calls = self._drive(
            self._plan_with_restart(self._allowed_restart()),
            [{"n1": {"status": "deferred", "reason": "later"}},
             {"n1": {"status": "ok"}}])
        self.assertTrue(driven["final_all_ok"])
        self.assertEqual(calls, {"plan": 1, "execute": 2})
        self.assertEqual(
            driven["rounds_history"][0]["restart"]["staleness_reason"],
            "restart_targeted")

    # -- a refused or blocked restart keeps the pause -----------------------
    def test_blocked_restart_keeps_the_pause(self):
        preflights, renewals = [], []
        driven, goals, events, calls = self._drive(
            self._plan_with_restart(self._blocked_restart()),
            [{"n1": {"status": "ok"},
              "n2": {"status": "deferred", "reason": "nope"}}],
            preflight_budget=lambda transition: preflights.append(
                transition),
            renew_consent=lambda transition: renewals.append(transition))
        self.assertEqual(driven["status"], "deferred")
        self.assertIn("handoff", driven)
        self.assertEqual(calls, {"plan": 0, "execute": 1})
        self.assertEqual(preflights, [])
        self.assertEqual(renewals, [])
        restart = driven["rounds_history"][0]["restart"]
        self.assertFalse(restart["reentered"])
        self.assertEqual(restart["target"], "planning")
        self.assertTrue(any("keeping the pause" in note
                            for note in self._notes(events)))
        # The pause still preserves the completed evidence in its handoff.
        self.assertIn("r1/n1", driven["handoff"]["completed_results"])

    def test_absent_decision_keeps_the_slice1_pause_exactly(self):
        preflights, renewals = [], []
        plan = {"total_nodes": 1, "total_cost_ceiling": 0.0,
                "nodes": [{"node_id": "n1", "instruction": "edit",
                           "target_files": ["a.py"]}],
                "dag": {"nodes": [{"node_id": "n1"}]}}
        driven, _, events, calls = self._drive(
            plan,
            [{"n1": {"status": "deferred", "reason": "nope"}}],
            preflight_budget=lambda transition: preflights.append(
                transition),
            renew_consent=lambda transition: renewals.append(transition))
        self.assertEqual(driven["status"], "deferred")
        self.assertEqual(driven["remaining_scope"], "nope")
        self.assertEqual(calls, {"plan": 0, "execute": 1})
        self.assertEqual(preflights, [])
        self.assertEqual(renewals, [])
        self.assertNotIn("restart", driven["rounds_history"][0])
        self.assertFalse(any("restart" in note
                             for note in self._notes(events)))

    # -- the consumer directly ----------------------------------------------
    def test_consumer_refuses_without_a_decision(self):
        for decision in (None, "planning", 42):
            transition = consume_restart_decision(
                decision,
                completed_results={"r1/n1": {"status": "ok"}})
            self.assertFalse(transition["reenter"])
            self.assertEqual(transition["preserved_evidence"], {})

    def test_consumer_preserves_only_unpaused_results(self):
        transition = consume_restart_decision(
            self._allowed_restart(),
            completed_results={"r1/n1": {"status": "ok"},
                               "r1/n2": {"status": "deferred"},
                               "junk": "not-a-dict"})
        self.assertTrue(transition["reenter"])
        self.assertEqual(sorted(transition["preserved_evidence"]), ["r1/n1"])
        self.assertEqual(transition["staleness_reason"], "restart_targeted")

    def test_consumer_refuses_a_terminal_state(self):
        decision = self._allowed_restart()
        decision["terminal_state"] = self._terminal(consent_fresh=False)
        self.assertTrue(decision["terminal_state"]["terminal"])
        transition = consume_restart_decision(
            decision, completed_results={"r1/n1": {"status": "ok"}})
        self.assertFalse(transition["reenter"])
        self.assertEqual(transition["preserved_evidence"], {})


if __name__ == "__main__":
    unittest.main()
