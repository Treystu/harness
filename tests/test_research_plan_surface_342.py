"""#342: the CLI and MCP ask surfaces can request bounded retrieval.

The GUI already forwarded a `web` request field (`harness/server.py`), but the
CLI `ask` command and the MCP `ask` tool called `run_prompt` with no way to
request retrieval at all. That left the native accepted/declined ResearchPlan
lifecycle unreachable through those two surfaces, which is the evidence line
#342 still owes.

These tests pin the seam only: the surfaces forward the capability, and the
shared plan owner (`harness.research_plan.decide_research_plan`) still owns
approval -- `web=True` grants no search or fetch by itself.
"""
import unittest
from types import SimpleNamespace
from unittest import mock

from harness import cli
from harness import mcp as mcp_module
from harness.mcp_schemas import TOOL_SCHEMAS


def _schema(name):
    for entry in TOOL_SCHEMAS:
        if entry["name"] == name:
            return entry
    raise AssertionError(f"{name} tool is missing")


class CliAskWebFlagTests(unittest.TestCase):
    def _run(self, argv):
        expected = {"status": "ok", "response": "done"}
        with mock.patch.object(cli, "load_settings",
                               return_value=SimpleNamespace()), \
             mock.patch("harness.agent.AutonomousAgent.run_prompt",
                        return_value=expected) as run_prompt, \
             mock.patch.object(cli, "_emit"):
            cli.main(argv)
        return run_prompt

    def test_the_parser_accepts_web_and_forwards_it(self):
        run_prompt = self._run(["ask", "--web", "what", "changed", "today"])
        self.assertTrue(run_prompt.call_args.kwargs["web"])

    def test_the_default_asks_for_no_retrieval(self):
        run_prompt = self._run(["ask", "what", "changed", "today"])
        self.assertFalse(run_prompt.call_args.kwargs["web"])


class McpAskWebArgumentTests(unittest.TestCase):
    def _invoke(self, args):
        server = mcp_module.McpServer(
            transport=object(), api_key="k", governor=object(),
            ledger=object(), router=object(), engine=object(),
            settings=SimpleNamespace())
        expected = {"status": "ok", "response": "done"}
        with mock.patch("harness.agent.AutonomousAgent.run_prompt",
                        return_value=expected) as run_prompt:
            result = server._invoke("ask", args, cancel_check=lambda: False)
        self.assertEqual(result, expected)
        return run_prompt

    def test_a_true_web_argument_reaches_the_lifecycle(self):
        run_prompt = self._invoke({"prompt": "What changed today?",
                                   "web": True})
        self.assertTrue(run_prompt.call_args.kwargs["web"])

    def test_an_absent_web_argument_asks_for_no_retrieval(self):
        run_prompt = self._invoke({"prompt": "What changed today?"})
        self.assertFalse(run_prompt.call_args.kwargs["web"])

    def test_a_non_boolean_web_argument_is_refused(self):
        from harness.errors import HarnessError
        with self.assertRaises(HarnessError):
            self._invoke({"prompt": "What changed today?", "web": "yes"})


class CatalogStatesTheWebInputTests(unittest.TestCase):
    def test_the_ask_schema_declares_web_as_a_boolean(self):
        prop = _schema("ask")["inputSchema"]["properties"]["web"]
        self.assertEqual(prop["type"], "boolean")

    def test_the_ask_description_names_the_web_input(self):
        text = " ".join(str(_schema("ask")["description"]).split())
        start, end = text.find("In:"), text.find("Out:")
        self.assertIn("web", text[start:end].lower())
