"""#286: the additive-only versioning policy is enforced, not just written down.

The policy says a schema may gain optional fields, while removing, renaming or
retyping a field -- or making an optional field required -- needs a new tool
name. These tests hold that line: every breaking shape change must be refused
with the tool and field named, additive changes must pass and be reported, and
prose must stay free. The shipped snapshot must describe the shipped catalog,
so the check is a live gate rather than a stale file.
"""
import json
import os
import tempfile
import unittest

from harness import mcp_surface as ms
from harness.mcp_schemas import TOOL_SCHEMAS


def tool(name="t1", props=None, required=None):
    return {
        "name": name,
        "title": name,
        "description": "When: x. In: y. Out: z.",
        "inputSchema": {
            "type": "object",
            "properties": props if props is not None else {"alpha": {"type": "string"}},
            "required": required or [],
        },
    }


def pinned_from(schemas):
    return ms.snapshot(schemas)


def violations_of(pinned, schemas):
    return ms.check(pinned, schemas)["violations"]


class SnapshotTests(unittest.TestCase):
    def test_the_shipped_snapshot_pins_the_shipped_catalog(self):
        path = ms.default_snapshot_path()
        self.assertTrue(os.path.exists(path))
        pinned = ms.load_snapshot(path)
        self.assertEqual(len(pinned["tools"]), len(TOOL_SCHEMAS))
        self.assertEqual(ms.check(pinned, TOOL_SCHEMAS)["violations"], [])

    def test_the_shipped_snapshot_is_self_consistent(self):
        live = ms.surface(TOOL_SCHEMAS)
        self.assertEqual(len(live), 33)
        self.assertEqual(sum(1 for entry in live.values() if entry["required"]), 18)

    def test_a_snapshot_without_a_schema_tag_is_refused(self):
        path = os.path.join(tempfile.mkdtemp(prefix="surf-tag-"), "s.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"tools": {"a": {"properties": {}, "required": []}}}, handle)
        with self.assertRaises(ms.SurfaceError):
            ms.load_snapshot(path)

    def test_a_snapshot_pinning_no_tools_is_refused(self):
        path = os.path.join(tempfile.mkdtemp(prefix="surf-empty-"), "s.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"schema": ms.SNAPSHOT_SCHEMA, "tools": {}}, handle)
        with self.assertRaises(ms.SurfaceError):
            ms.load_snapshot(path)

    def test_a_duplicate_tool_name_is_refused(self):
        with self.assertRaises(ms.SurfaceError):
            ms.surface([tool("dup"), tool("dup")])

    def test_a_required_field_that_is_not_declared_is_refused(self):
        broken = tool(props={"alpha": {"type": "string"}}, required=["beta"])
        with self.assertRaises(ms.SurfaceError):
            ms.surface([broken])

    def test_an_untyped_property_is_pinned_as_untyped(self):
        pinned = ms.snapshot([tool(props={"alpha": {}})])
        self.assertEqual(pinned["tools"]["t1"]["properties"]["alpha"], "untyped")

    def test_a_union_type_is_pinned_deterministically(self):
        pinned = ms.snapshot([tool(props={"alpha": {"type": ["string", "null"]}})])
        self.assertEqual(pinned["tools"]["t1"]["properties"]["alpha"], "null|string")


class AdditiveChangeTests(unittest.TestCase):
    def test_an_optional_property_may_be_added(self):
        pinned = pinned_from([tool()])
        grown = [tool(props={"alpha": {"type": "string"},
                             "beta": {"type": "integer"}})]
        result = ms.check(pinned, grown)
        self.assertEqual(result["violations"], [])
        self.assertEqual([a["kind"] for a in result["additions"]], ["property_added"])

    def test_a_new_tool_may_be_added(self):
        pinned = pinned_from([tool()])
        result = ms.check(pinned, [tool(), tool("t2")])
        self.assertEqual(result["violations"], [])
        self.assertEqual(result["additions"][0]["kind"], "tool_added")

    def test_a_description_or_title_change_is_free(self):
        pinned = pinned_from([tool()])
        edited = [tool()]
        edited[0]["description"] = "When: new prose. In: alpha. Out: z."
        edited[0]["title"] = "Renamed in prose only"
        self.assertEqual(ms.check(pinned, edited)["violations"], [])

    def test_a_new_required_field_on_top_of_the_old_ones_is_a_violation(self):
        pinned = pinned_from([tool(required=["alpha"])])
        grown = [tool(props={"alpha": {"type": "string"},
                             "beta": {"type": "integer"}},
                      required=["alpha", "beta"])]
        kinds = [v["kind"] for v in ms.check(pinned, grown)["violations"]]
        self.assertIn("property_newly_required", kinds)


class BreakingChangeTests(unittest.TestCase):
    def test_a_removed_property_is_refused(self):
        pinned = pinned_from([tool(props={"alpha": {"type": "string"},
                                          "beta": {"type": "integer"}})])
        violations = violations_of(pinned, [tool(props={"alpha": {"type": "string"}})])
        self.assertEqual([v["kind"] for v in violations], ["property_removed"])
        self.assertIn("beta", violations[0]["detail"])

    def test_a_rename_reads_as_removal_and_refuses(self):
        pinned = pinned_from([tool(props={"alpha": {"type": "string"}})])
        violations = violations_of(pinned, [tool(props={"a1": {"type": "string"}})])
        self.assertEqual([v["kind"] for v in violations], ["property_removed"])

    def test_a_retyped_property_is_refused(self):
        pinned = pinned_from([tool(props={"alpha": {"type": "string"}})])
        violations = violations_of(pinned, [tool(props={"alpha": {"type": "integer"}})])
        self.assertEqual([v["kind"] for v in violations], ["property_retyped"])
        self.assertIn("string", violations[0]["detail"])

    def test_making_an_optional_field_required_is_refused(self):
        pinned = pinned_from([tool(props={"alpha": {"type": "string"}})])
        violations = violations_of(
            pinned, [tool(props={"alpha": {"type": "string"}}, required=["alpha"])])
        self.assertEqual([v["kind"] for v in violations], ["property_newly_required"])

    def test_a_removed_tool_is_refused(self):
        pinned = pinned_from([tool(), tool("t2")])
        violations = violations_of(pinned, [tool()])
        self.assertEqual([v["kind"] for v in violations], ["tool_removed"])
        self.assertEqual(violations[0]["tool"], "t2")

    def test_a_break_is_not_hidden_by_an_addition(self):
        pinned = pinned_from([tool(props={"alpha": {"type": "string"}})])
        result = ms.check(pinned, [tool(props={"beta": {"type": "integer"}})])
        self.assertTrue(result["violations"])
        self.assertTrue(result["additions"])

    def test_assert_additive_names_the_tool_and_policy(self):
        directory = tempfile.mkdtemp(prefix="surf-assert-")
        path = os.path.join(directory, "s.json")
        ms.write_snapshot(path, [tool(props={"alpha": {"type": "string"}})])
        with self.assertRaises(ms.SurfaceError) as held:
            ms.assert_additive(path, [tool(props={})])
        message = str(held.exception)
        self.assertIn("not additive-only", message)
        self.assertIn("property_removed", message)
        self.assertIn("new tool name", message)

    def test_assert_additive_returns_the_allowed_count(self):
        directory = tempfile.mkdtemp(prefix="surf-count-")
        path = os.path.join(directory, "s.json")
        ms.write_snapshot(path, [tool()])
        grown = [tool(props={"alpha": {"type": "string"}, "beta": {"type": "integer"}})]
        self.assertEqual(ms.assert_additive(path, grown), 1)


class CommandLineTests(unittest.TestCase):
    def test_check_passes_on_the_real_catalog(self):
        self.assertEqual(ms.main(["--check", "--quiet"]), 0)

    def test_check_fails_loudly_on_a_break(self):
        directory = tempfile.mkdtemp(prefix="surf-cli-")
        path = os.path.join(directory, "s.json")
        ms.write_snapshot(path, [tool(props={"alpha": {"type": "string"}})])
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as handle:
            json.dump([tool(props={})], handle)
        import harness.mcp_schemas as schemas
        real = schemas.TOOL_SCHEMAS
        try:
            schemas.TOOL_SCHEMAS = [tool(props={})]
            self.assertEqual(ms.main(["--check", "--snapshot", path]), 1)
        finally:
            schemas.TOOL_SCHEMAS = real

    def test_write_then_check_round_trips(self):
        directory = tempfile.mkdtemp(prefix="surf-write-")
        path = os.path.join(directory, "nested", "s.json")
        self.assertEqual(ms.write_snapshot(path, TOOL_SCHEMAS), 33)
        self.assertEqual(ms.assert_additive(path, TOOL_SCHEMAS), 0)

    def test_both_or_neither_flag_is_refused(self):
        with self.assertRaises(SystemExit):
            ms.main([])
        with self.assertRaises(SystemExit):
            ms.main(["--check", "--write"])

    def test_surface_and_snapshot_validation_branches(self):
        self.assertEqual(ms._type_of("not-a-dict"), "untyped")
        for bad_catalog in ([], ["not-a-dict"], [{"name": "   "}]):
            with self.assertRaises(ms.SurfaceError):
                ms.surface(bad_catalog)
        with tempfile.TemporaryDirectory(prefix="surf-val-") as directory:
            p = os.path.join(directory, "bad.json")
            for raw in (
                "{bad json",
                json.dumps({"schema": ms.SNAPSHOT_SCHEMA, "tools": {"t": "not-dict"}}),
                json.dumps({"schema": ms.SNAPSHOT_SCHEMA, "tools": {"t": {"properties": "bad"}}}),
                json.dumps({"schema": ms.SNAPSHOT_SCHEMA, "tools": {"t": {"properties": {}, "required": "bad"}}}),
            ):
                with open(p, "w", encoding="utf-8") as h:
                    h.write(raw)
                with self.assertRaises(ms.SurfaceError):
                    ms.load_snapshot(p)
            snap_p = os.path.join(directory, "ok.json")
            self.assertEqual(ms.main(["--write", "--snapshot", snap_p]), 0)
            self.assertEqual(ms.main(["--check", "--snapshot", snap_p]), 0)


class AnnotationPolicyTests(unittest.TestCase):
    def _annotated(self, name="t1", *, read_only=True, destructive=False,
                   idempotent=None, open_world=False, title=None,
                   desc="When: x. In: y. Out: z.", props=None):
        ann = {
            "readOnlyHint": read_only,
            "destructiveHint": destructive,
            "openWorldHint": open_world,
        }
        if idempotent is not None:
            ann["idempotentHint"] = idempotent
        entry = tool(name=name, props=props)
        entry["title"] = title if title is not None else name
        entry["description"] = desc
        entry["annotations"] = ann
        return entry

    def test_all_33_catalog_tools_carry_accurate_annotations(self):
        from unittest import mock
        from harness import mcp as mcp_mod
        from harness.mcp import McpServer
        from harness.mcp_lanes import MUTATION_LANE

        self.assertEqual(ms.lint_tool_annotations(TOOL_SCHEMAS), 33)
        served = McpServer._tools(object())
        by_name = {entry["name"]: entry for entry in served}
        self.assertEqual(len(by_name), 33)

        expected_readonly = {
            "ask", "site_check", "panel_verify", "ledger_status",
            "participation_report", "spend_status", "trust_status",
            "issue_sort", "route_query", "log_judgment", "lucas_gate_v2",
            "jev_phase", "generate_brief", "driver_health",
            "driver_vocabulary", "driver_verify", "host_provision_probe",
            "host_provision_plan", "jev_calibration", "economics_report",
        }
        expected_destructive = {
            "apply_edit", "plan_and_execute", "continue_work",
            "script_run", "dogfood", "driver_step",
        }
        expected_non_destructive_mutating = {
            "offer_work", "defer_work", "source_audit",
            "mission_status", "jev_freeze", "repo_cards", "flush_run",
        }
        expected_idempotent_mutating = {"mission_status", "jev_freeze", "repo_cards"}
        expected_open_world = {
            "ask", "site_check", "panel_verify", "apply_edit", "offer_work",
            "spend_status", "plan_and_execute", "issue_sort", "source_audit",
            "route_query", "continue_work", "script_run", "log_judgment",
            "dogfood", "host_provision_plan", "flush_run",
            # #683 finding 9: a keyed driver service sends captured state to
            # external model services, so the tool is open-world.
            "driver_step",
        }

        self.assertEqual(
            expected_readonly | expected_destructive | expected_non_destructive_mutating,
            set(by_name),
        )
        for name, entry in by_name.items():
            ann = entry["annotations"]
            self.assertEqual(ann["readOnlyHint"], name in expected_readonly, name)
            self.assertEqual(ann["destructiveHint"], name in expected_destructive, name)
            self.assertEqual(ann["openWorldHint"], name in expected_open_world, name)
            if name in expected_readonly:
                self.assertNotIn("idempotentHint", ann, name)
            else:
                self.assertEqual(ann["idempotentHint"], name in expected_idempotent_mutating, name)
            if name in MUTATION_LANE:
                self.assertFalse(ann["readOnlyHint"], name)

        # Runtime guard refuses stale claims and verifies live catalog parity.
        self.assertNotIn("14-action", by_name["driver_vocabulary"]["description"])
        self.assertNotIn("read-only", by_name["mission_status"]["title"].lower())

        broken = [self._annotated("ask", read_only=True, destructive=True)]
        with mock.patch.object(mcp_mod, "TOOL_SCHEMAS", broken):
            with self.assertRaises(ms.SurfaceError):
                McpServer._tools(object())

    def test_lint_tool_annotations_refuses_all_inconsistent_contracts(self):
        from harness.mcp_lanes import MUTATION_LANE

        mut_name = sorted(MUTATION_LANE)[0]
        cases = [
            (["not-a-dict"], "mapping"),
            ([tool("missing")], "missing annotations"),
            ([{**self._annotated("x"), "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False, "extraHint": True}}], "unknown annotation key"),
            ([{**self._annotated("badbool"), "annotations": {"readOnlyHint": "yes", "destructiveHint": False, "openWorldHint": False}}], "must be a bool"),
            ([self._annotated("mut_no_idem", read_only=False, destructive=False, idempotent=None)], "idempotentHint"),
            ([self._annotated("ro_destr", read_only=True, destructive=True)], "cannot pair"),
            ([self._annotated(mut_name, read_only=True, destructive=False)], "MUTATION_LANE"),
            ([self._annotated("wgated", read_only=True, destructive=False, props={"allow_write": {"type": "boolean"}})], "write/exec-gated"),
            ([self._annotated("stale_ro", read_only=False, destructive=False, idempotent=True, title="Status (read-only)")], "read-only"),
            ([self._annotated("stale_destr", read_only=False, destructive=True, idempotent=False, desc="When: x. In: y. Out: never mutates files.")], "never mutates"),
            ([self._annotated("ro_claims_write", read_only=True, destructive=False, desc="When: x. In: y. Out: writes the operator config.")], "claims mutation"),
        ]
        for bad, expected_msg in cases:
            with self.subTest(expected_msg=expected_msg):
                with self.assertRaises(ms.SurfaceError) as held:
                    ms.lint_tool_annotations(bad)
                self.assertIn(expected_msg, str(held.exception))


if __name__ == "__main__":
    unittest.main()
