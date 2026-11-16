"""#284: a description must NAME its inputs, not defer to "the schema".

The shipped lint enforces the formula's shape -- When:, In:, Out:, in order,
non-empty. Measured against the live catalog on harness `2203782`, nine of the
33 served descriptions passed that shape check while their In: segment said
only "the fields declared by the schema": a model reading the description is
told there are inputs and not what to supply. This module pins the second rule
that closes it, and keeps the negative controls that make the rule real.
"""
import unittest
from unittest import mock

from driver_core.audit import (AuditError, lint_description_inputs,
                               lint_tool_descriptions)
from harness import mcp as mcp_module
from harness.mcp_schemas import TOOL_SCHEMAS


def schema(name, description, required=(), properties=None):
    return {"name": name, "description": description,
            "inputSchema": {"type": "object",
                            "required": list(required),
                            "properties": properties or {k: {} for k in required}}}


class CatalogConformanceTests(unittest.TestCase):
    def test_every_registered_tool_names_its_required_inputs(self):
        checked = lint_description_inputs(TOOL_SCHEMAS)
        self.assertGreaterEqual(checked, 18)  # measured on 2203782

    def test_the_catalog_still_passes_the_shape_lint(self):
        self.assertEqual(lint_tool_descriptions(TOOL_SCHEMAS), len(TOOL_SCHEMAS))

    def test_every_tool_that_requires_inputs_states_them(self):
        offenders = []
        for entry in TOOL_SCHEMAS:
            required = (entry.get("inputSchema") or {}).get("required") or []
            text = " ".join(str(entry.get("description") or "").split())
            start, end = text.find("In:"), text.find("Out:")
            segment = text[start + 3:end].lower() if 0 <= start < end else ""
            if any(field.lower() not in segment for field in required):
                offenders.append(entry["name"])
        self.assertEqual(offenders, [])


class RuleTests(unittest.TestCase):
    def test_a_description_deferring_to_the_schema_is_refused(self):
        broken = [schema("offer_work", "When: a work item needs a decision. "
                                       "In: the fields declared by the schema. "
                                       "Out: a choice.", required=["task"])]
        with self.assertRaises(AuditError) as ctx:
            lint_description_inputs(broken)
        self.assertIn("task", str(ctx.exception))

    def test_naming_every_required_input_passes(self):
        good = [schema("x", "When: needed. In: alpha plus beta. Out: a result.",
                       required=["alpha", "beta"])]
        self.assertEqual(lint_description_inputs(good), 1)

    def test_the_match_is_case_insensitive_and_whole_word(self):
        good = [schema("x", "When: needed. In: Task_ID. Out: a result.",
                       required=["task_id"])]
        self.assertEqual(lint_description_inputs(good), 1)
        partial = [schema("x", "When: needed. In: task. Out: a result.",
                          required=["task_id"])]
        with self.assertRaises(AuditError):
            lint_description_inputs(partial)

    def test_only_one_missing_input_is_named(self):
        broken = [schema("x", "When: needed. In: alpha. Out: a result.",
                         required=["alpha", "beta", "gamma"])]
        with self.assertRaises(AuditError) as ctx:
            lint_description_inputs(broken)
        message = str(ctx.exception)
        self.assertIn("beta", message)
        self.assertIn("gamma", message)

    def test_a_tool_with_no_required_inputs_is_not_counted(self):
        self.assertEqual(lint_description_inputs(
            [schema("x", "When: needed. In: nothing. Out: state.")]), 0)

    def test_a_non_mapping_schema_is_refused(self):
        with self.assertRaises(AuditError):
            lint_description_inputs(["not-a-schema"])

    def test_an_empty_catalog_passes_vacuously(self):
        self.assertEqual(lint_description_inputs([]), 0)


class ServingPathTests(unittest.TestCase):
    def test_the_served_catalog_runs_both_lints(self):
        broken = [schema("x", "When: needed. In: the schema. Out: a result.",
                         required=["field"])]
        with mock.patch.object(mcp_module, "TOOL_SCHEMAS", broken):
            server = mcp_module.McpServer.__new__(mcp_module.McpServer)
            with self.assertRaises(AuditError):
                server._tools()

    def test_the_real_catalog_serves(self):
        server = mcp_module.McpServer.__new__(mcp_module.McpServer)
        self.assertEqual(len(server._tools()), len(TOOL_SCHEMAS))


if __name__ == "__main__":
    unittest.main()
