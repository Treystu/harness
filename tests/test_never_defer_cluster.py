"""Hermetic contracts for the never-defer cluster (#541, #542, #543, #544).

One file per cluster because the four cures share the same acceptance shape:
the run continues (repair, build path, completed Response, generation path)
instead of stopping early for a reason that does not apply.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness.chat_policy import is_artifact_request, research_detour_blocked
from harness.config import load_settings
from harness.errors import HarnessError
from harness.waist import (
    _salvage_decomposition,
    compose_plan,
    decomposition_repair_record,
)
from harness.web import gather_web_context
from harness.workspace import WORKSPACE_GATE_MESSAGE
from tests._fake import FakeTransport, _gov


MALFORMED = (
    'nodes: [{"node_id": "n1", "instruction": "Create the windows script"}'
    " — trailing commentary the parser cannot accept")
UNPARSEABLE = "I could not produce a plan, sorry."


def _compose(**overrides):
    gov = _gov(FakeTransport(), max_cost=0.05)
    kwargs = dict(
        transport=FakeTransport(), api_key="k", governor=gov, ledger=None,
        opts_goal="Create a Windows script", candidate_files=[],
        decompose_llm=True, confirm=False, execute=True,
        use_free=False, frontier_model="m/front")
    kwargs.update(overrides)
    return compose_plan(**kwargs)


class DecompositionRepairTests(unittest.TestCase):
    def test_salvage_recovers_a_node_from_a_malformed_body(self):
        dag = _salvage_decomposition(MALFORMED)
        self.assertIsNotNone(dag)
        self.assertIn("n1", dag.nodes)
        self.assertEqual(dag.nodes["n1"].instruction,
                         "Create the windows script")

    def test_salvage_refuses_a_body_with_no_structure(self):
        self.assertIsNone(_salvage_decomposition(UNPARSEABLE))

    def test_malformed_decomposition_is_salvaged_without_a_second_call(self):
        calls = []

        def chat(prompt):
            calls.append(prompt)
            return MALFORMED

        plan = _compose(chat_fn=chat)
        self.assertTrue(plan["decomposition"].startswith("llm-salvage"))
        self.assertEqual(len(calls), 2,
                         "one attempt plus the strict retry, no third call")
        repair = plan["decomposition_repair"]
        self.assertEqual(repair["outcome"], "salvaged")
        self.assertEqual(repair["cost"], 0.0)
        self.assertEqual(repair["raw_output"], MALFORMED)
        self.assertIn("parse_error", repair)

    def test_repair_cost_is_strictly_less_than_a_full_second_call(self):
        # The repair is deterministic: it spends nothing. A second full
        # decomposition call is a paid call, so $0 is strictly less.
        record = decomposition_repair_record(HarnessError("bad json"), MALFORMED)
        self.assertEqual(record["cost"], 0.0)
        self.assertEqual(record["path"], "deterministic_salvage")

    def test_unparseable_decomposition_falls_back_loudly_with_evidence(self):
        plan = _compose(chat_fn=lambda prompt: UNPARSEABLE)
        self.assertEqual(plan["decomposition"], "heuristic")
        self.assertTrue(plan["degraded"])
        self.assertEqual(plan["degrade_reason"], "decomposition_unparseable")
        repair = plan["decomposition_repair"]
        self.assertEqual(repair["outcome"], "heuristic")
        self.assertEqual(repair["raw_output"], UNPARSEABLE)
        self.assertTrue(repair["raw_output_sha256"])

    def test_fail_closed_preview_still_carries_the_raw_output(self):
        with self.assertRaises(HarnessError) as ctx:
            _compose(chat_fn=lambda prompt: UNPARSEABLE, execute=False,
                     allow_heuristic_preview=False)
        self.assertEqual(ctx.exception.raw_output, UNPARSEABLE)


class ArtifactRoutingTests(unittest.TestCase):
    def test_the_2026_11_14_artifact_request_is_not_a_research_request(self):
        prompt = "make a script that runs in windows to generate the image"
        self.assertTrue(is_artifact_request(prompt))
        self.assertTrue(research_detour_blocked(prompt))

    def test_a_genuine_lookup_still_researches(self):
        for prompt in (
            "What is the latest news about Python releases?",
            "Find recent research on battery chemistry.",
            "Audit https://example.com and tell me what it does.",
        ):
            with self.subTest(prompt=prompt):
                self.assertFalse(research_detour_blocked(prompt))

    def test_an_artifact_request_that_asks_for_research_keeps_research(self):
        prompt = ("write a script, and search the latest papers on "
                  "transformer scaling")
        self.assertTrue(is_artifact_request(prompt))
        self.assertFalse(research_detour_blocked(prompt))

    def test_zero_char_named_source_aborts_the_detour_before_searching(self):
        searched = []

        def fetch(url, allowed_hosts=None, allow_any_public=False):
            return {"url": url, "title": "Empty", "text": ""}

        def search(query):
            searched.append(query)
            return [{"url": "https://example.com/x", "title": "t",
                     "snippet": "should not be used"}]

        sources = gather_web_context(
            "look at https://example.com/page and summarize it",
            allowed_hosts=("example.com",), named_hosts=("example.com",),
            fetch_url_fn=fetch, search_web_fn=search,
            find_urls_fn=lambda p: ["https://example.com/page"],
            extract_query_fn=lambda p: p)
        self.assertEqual(searched, [],
                         "a 0-char named fetch must not trigger a search")
        notes = [s for s in sources if s.get("kind") == "detour"]
        self.assertEqual(len(notes), 1)
        self.assertIn("0 chars", notes[0]["note"])


class OutcomeClassificationTests(unittest.TestCase):
    """#543: Deferred is reserved for requests that did not complete."""

    def _reason(self, text):
        from harness.agent import AutonomousAgent

        return AutonomousAgent._refusal_reason(text)

    # The "completed answer carrying a capability caveat" shape is owned by
    # the merged #543 cure in tests/test_agent.py
    # (test_completed_answer_with_a_capability_caveat_stays_ok), which pins the
    # shipped rule: the caveat is a deferral only below
    # _REFUSAL_SUBSTANCE_WORDS of body around it. Asserting a second, different
    # floor here would make the bundle the second owner of one classification
    # rule, which is the drift #543 already closed.

    def test_genuine_non_completion_still_defers(self):
        self.assertIsNotNone(self._reason(
            "I can't help with that request."))

    def test_bare_caveat_without_a_body_still_defers(self):
        self.assertIsNotNone(self._reason(
            "I can't generate an actual image."))


class WorkspaceGateTimingTests(unittest.TestCase):
    """#544: the gate fires at the operation, not at task start."""

    def setUp(self):
        from harness.agent import AutonomousAgent

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        settings = load_settings({
            "panel_pool": "m", "ledger_path": str(self.root / "l.jsonl"),
            "max_cost": 0.01,
        })
        self.agent = AutonomousAgent(settings=settings, root_dir=None,
                                     history_dir=self.root, transport=None)

    def test_desktop_intake_no_longer_errors_on_a_missing_workspace(self):
        from harness.server import validate_dispatch

        args = validate_dispatch("chat", {
            "prompt": "make a script that runs in windows to generate the image",
            "auto_apply": True,
        })
        self.assertNotIn("root_dir", args)

    def test_no_file_scope_request_answers_without_a_workspace(self):
        with patch.object(self.agent, "run_simple_request",
                          return_value={"status": "ok", "response": "done"}), \
             patch("harness.edit_lifecycle.emit") as emit_mock:
            result = self.agent._handle_edit(
                "make a script that prints hello", "s1", False, None)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(any(
            call.args and call.args[0] == "workspace_gate_deferred"
            for call in emit_mock.call_args_list))

    def test_file_write_without_a_workspace_stops_at_the_operation(self):
        with patch.object(self.agent, "_triage_scope",
                          return_value=["script.py"]):
            with self.assertRaisesRegex(HarnessError,
                                        WORKSPACE_GATE_MESSAGE):
                self.agent._handle_edit(
                    "rewrite script.py to print hello", "s2", True, None)


class PreviewHelperTests(unittest.TestCase):
    def test_preview_gate_message_is_unchanged(self):
        self.assertEqual(
            WORKSPACE_GATE_MESSAGE,
            "Select a workspace folder before requesting file or provisioning work")


if __name__ == "__main__":
    unittest.main()
