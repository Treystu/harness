"""Ownership split of the plan lane (#308).

The waist used to own decomposition, consensus/confirmation, context intake and
stage budgeting in one 3.5k-line module. #308 assigns each concern a single
owner module. These tests pin the boundary so a later edit cannot quietly move
the concern back into the waist or duplicate it behind a second definition.
"""
import ast
import importlib
import unittest

OWNERS = {
    "harness.plan_decompose": (
        "build_decomposition_prompt",
        "parse_decomposition_response",
        "heuristic_decompose_goal",
        "decompose_via_llm",
    ),
    "harness.plan_consensus": (
        "build_consensus_prompt",
        "parse_plan_consensus",
        "plan_consensus",
        "confirm_plan",
        "plan_task",
        "parse_waist_verdict",
    ),
    "harness.plan_context": (
        "compose_arguments",
        "intake_brief",
        "recondense_decision",
        "resolve_stages",
    ),
    "harness.plan_stages": (
        "compose_stages",
        "stage_budget",
        "stage_states",
        "composition_envelope",
        "plan_outcome",
        "planning_ladder",
    ),
    "harness.plan_contracts": (
        "STAGE_CONTEXT",
        "STAGE_PLANNING",
        "STAGE_EXECUTION",
        "STAGE_VERIFICATION",
        "OUTCOME_DEFER",
        "PLAN_OUTCOMES",
    ),
}

# The waist keeps orchestration only: the one compose entry point, the planning
# loop, the tier-0 chunker and per-node routing kwargs.
WAIST_ORCHESTRATION = (
    "compose_plan",
    "run_planning",
    "chunk_oversized_nodes",
    "node_apply_kwargs",
    "PlanningOutcome",
)

MISSING = unittest.SkipTest


def _source_of(module) -> str:
    with open(module.__file__, encoding="utf-8") as handle:
        return handle.read()


def _defined_names(module) -> set:
    tree = ast.parse(_source_of(module))
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


class OwnerModuleTests(unittest.TestCase):
    def test_each_owner_defines_its_concern(self):
        for module_name, expected in OWNERS.items():
            with self.subTest(module=module_name):
                module = importlib.import_module(module_name)
                defined = _defined_names(module)
                for name in expected:
                    self.assertIn(name, defined, f"{module_name} no longer defines {name}")

    def test_waist_keeps_orchestration_only(self):
        from harness import waist

        defined = _defined_names(waist)
        for name in WAIST_ORCHESTRATION:
            self.assertIn(name, defined, f"waist no longer defines {name}")

    def test_waist_does_not_redefine_an_owned_concern(self):
        from harness import waist

        defined = _defined_names(waist)
        for module_name, expected in OWNERS.items():
            with self.subTest(module=module_name):
                duplicated = sorted(set(expected) & defined)
                self.assertEqual(
                    duplicated, [],
                    f"{module_name}'s concern is defined again in waist: {duplicated}",
                )

    def test_owner_modules_import_without_the_waist(self):
        """A concern must not need the waist to load: that is what removes the cycle."""
        for module_name in OWNERS:
            with self.subTest(module=module_name):
                module = importlib.import_module(module_name)
                self.assertIsNotNone(module)

    def test_compat_surface_still_resolves(self):
        """Callers outside the plan lane import these from harness.waist (see _COMPAT_308)."""
        from harness import waist

        compat = (
            "STAGE_EXECUTION", "STAGE_ORDER", "STAGE_VERIFICATION", "STAGE_STATES",
            "STATE_PENDING", "MIN_ROUND_TOKENS", "MIN_STAGE_INPUT_TOKENS",
            "HOURGLASS_DEFAULT_STAGES", "OUTCOME_DEFER", "PLAN_OUTCOMES",
            "compose_arguments", "intake_brief", "recondense_decision", "resolve_stages",
            "build_decomposition_prompt", "parse_decomposition_response",
            "heuristic_decompose_goal", "build_waist_prompt", "parse_waist_verdict",
            "plan_task_id", "read_window", "stage_budget",
        )
        missing = [name for name in compat if not hasattr(waist, name)]
        self.assertEqual(missing, [], f"compatibility surface broken: {missing}")
        self.assertTrue(waist._COMPAT_308, "the compatibility declaration is empty")

    def test_no_concern_module_imports_the_waist_at_module_scope(self):
        for module_name in OWNERS:
            module = importlib.import_module(module_name)
            tree = ast.parse(_source_of(module))
            offenders = []
            for node in tree.body:
                if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("waist"):
                    offenders.append(node.lineno)
            self.assertEqual(offenders, [], f"{module_name} imports the waist at module scope")


if __name__ == "__main__":
    unittest.main()
