"""Structural pins for the #310 split, slice 1 (vocabulary + typed plan).

``harness/provision.py`` owned seven concerns across different trust
boundaries. The first slice moved the two with no side effects at all into
``harness/provision_plan.py``: the constants, ``Step``, ``Plan``, the dict
coercions and ``render_plan``. ``provision`` imports and re-exports them, so
call sites and tests keep one import name.

These tests pin the seam, not the implementation: the dependency direction
(``provision_plan`` must never import ``provision``), the identity of every
re-exported name, and a handful of behaviors that must survive the move.
"""
import ast
import hashlib
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import provision as pv
from harness import provision_plan as pp

_PLAN_MODULE = os.path.join(os.path.dirname(pp.__file__), "provision_plan.py")


def _read_plan_module() -> str:
    with open(_PLAN_MODULE, encoding="utf-8") as handle:
        return handle.read()


class SeamDirectionTests(unittest.TestCase):
    """The pure module must not depend on the module it was carved out of."""

    def test_provision_plan_does_not_import_provision(self):
        source = _read_plan_module()
        for forbidden in ("from .provision import", "from harness.provision import",
                          "import harness.provision\n", " import provision as"):
            self.assertNotIn(forbidden, source)

    def test_provision_plan_runs_no_processes_and_touches_no_temp_files(self):
        # Read the executable structure, not the prose: the module docstring
        # legitimately says it runs no subprocess.
        tree = ast.parse(_read_plan_module())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.update(alias.name for alias in node.names)
                if node.module:
                    imported.add(node.module.split(".")[0])
        for forbidden in ("subprocess", "tempfile", "shutil", "multiprocessing"):
            self.assertNotIn(forbidden, imported)
        calls = [node for node in ast.walk(tree)
                 if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute)
                 and getattr(node.func.value, "id", None) == "osal"]
        self.assertEqual([c.func.attr for c in calls], [])

    def test_provision_plan_is_importable_on_its_own(self):
        # A fresh interpreter proves the module does not lean on provision's
        # import-time state (circular imports would raise here).
        import subprocess
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        done = subprocess.run(
            [sys.executable, "-c",
             "import harness.provision_plan as p; print(p.READ, p.IRREVERSIBLE)"],
            cwd=root, capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "read_only irreversible")


class OwnerImportTests(unittest.TestCase):
    """One import path per name: the plan types live only in the owner.

    ``tests/test_architecture.py`` forbids re-export facades, so this pins the
    consequence - a caller renders a plan through ``provision_plan``, and
    ``provision`` has no second copy of the name to drift from.
    """

    def test_the_plan_module_owns_the_names(self):
        for name in ("Step", "Plan", "ProvisionError", "step_from_dict",
                     "plan_from_dict", "render_plan", "_safe_text", "_canon",
                     "_sha256"):
            self.assertTrue(hasattr(pp, name), name)

    def test_provision_does_not_re_export_the_unused_names(self):
        for name in ("render_plan", "plan_from_dict", "step_from_dict",
                     "PROVISION_EVENTS", "_safe_text", "_canon"):
            self.assertFalse(hasattr(pv, name), name)

    def test_vocabulary_is_single_sourced(self):
        for name in ("READ", "MUTATING", "IRREVERSIBLE", "CLASSES", "APPROVE",
                     "DECLINE", "DEFER", "DECISIONS", "COMPLETED", "FAILED",
                     "DRY_RUN", "DECLINED", "DEFERRED", "AWAITING_APPROVAL",
                     "SKIPPED", "AUDIT_FAILED", "ALREADY_DONE",
                     "DEFAULT_STEP_TIMEOUT_S",
                     "DEFAULT_MAX_STEPS", "RECIPE_VENV_PIP", "RECIPE_NPM_PREFIX",
                     "RECIPE_SYSTEM_PM", "RECIPE_INVENTORY"):
            self.assertEqual(getattr(pv, name), getattr(pp, name), name)


class PlanBehaviorTests(unittest.TestCase):
    """The moved plan still behaves exactly as the provisioning core expects."""

    def _plan(self):
        return pv.Plan(
            "install numpy", (pv.Step("venv", "create venv",
                                       ["python", "-m", "venv", "v"],
                                       pv.MUTATING, "a virtualenv"),),
            "/tmp/root", pv.RECIPE_VENV_PIP, "code", False)

    def test_digest_is_the_canonical_sha256_of_the_content(self):
        plan = self._plan()
        expected = hashlib.sha256(
            json.dumps({"goal": plan.goal, "root": plan.root,
                        "review_required": plan.review_required,
                        "steps": [step.to_dict() for step in plan.steps]},
                       sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self.assertEqual(plan.digest, expected)

    def test_round_trip_through_dict_preserves_the_digest(self):
        plan = self._plan()
        again = pp.plan_from_dict(json.loads(json.dumps(plan.to_dict())))
        self.assertEqual(again.digest, plan.digest)

    def test_a_shell_string_still_cannot_be_a_step(self):
        with self.assertRaises(pv.ProvisionError):
            pv.Step("x", "d", "python -m pip install x", pv.MUTATING, "e")

    def test_review_required_is_part_of_the_digest(self):
        plan = self._plan()
        flagged = pv.Plan(plan.goal, plan.steps, plan.root, plan.recipe,
                          plan.source, plan.is_fallback, (), {}, True)
        self.assertNotEqual(flagged.digest, plan.digest)

    def test_render_plan_escapes_and_shows_argv_as_a_list(self):
        plan = self._plan()
        rendered = pp.render_plan(plan)
        self.assertIn('argv: ["python", "-m", "venv", "v"]', rendered)
        self.assertIn(plan.digest, rendered)


if __name__ == "__main__":
    unittest.main()
