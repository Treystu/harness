"""#707: an edit turn's scope comes from the current prompt first.

The live defect: in an execution directive the edit lane adopted the prior
plan's ``target_files`` before it triaged the prompt, so a path the operator
pasted in the current prompt never won -- every iteration edited the previous
plan's file. A past plan is a fallback for a directive that names no target,
not an override.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from harness.agent import AutonomousAgent
from harness.config import load_settings
from harness.history import save_chat_turn


def setUpModule():
    # Hermetic: the edit lane's governor is replaced at its own seam, so no
    # key verification and no provider call can happen from these tests.
    global _GOVERNOR_PATCHES
    _GOVERNOR_PATCHES = [
        patch("harness.edit_lifecycle.governor_for",
              return_value=(None, MagicMock())),
        patch("harness.request_router.governor_for",
              return_value=(None, MagicMock())),
        # Any governor reached by another seam still must not verify a key
        # over the network: these tests are about scope ordering only.
        patch("harness.spend.SpendGovernor.verify_key", return_value=None),
    ]
    for seam in _GOVERNOR_PATCHES:
        seam.start()


def tearDownModule():
    for seam in _GOVERNOR_PATCHES:
        seam.stop()


def _agent(tmp):
    settings = load_settings()
    settings.jev_api_key = None
    return AutonomousAgent(settings=settings, root_dir=Path(tmp),
                           history_dir=Path(tmp))


def _refused():
    return {"status": "refused", "confirmation": {"reason": "hold for review"},
            "dag": {"nodes": []}, "nodes": []}


class EditScopeOrderTests(unittest.TestCase):
    def _capture(self, agent):
        seen = {}

        def fake(goal, files, gov, **kwargs):
            seen["goal"], seen["files"] = goal, list(files)
            return _refused()
        return seen, patch.object(agent, "_plan_round", side_effect=fake)

    def _prior_plan(self, root, session, files, prompt="Refactor orders.py"):
        save_chat_turn(session, {
            "prompt": prompt, "target_files": list(files),
            "dag": {"nodes": [{"name": "n1"}]}}, root)

    def test_pasted_path_beats_a_stale_prior_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent = _agent(tmp)
            self._prior_plan(root, "s1", ["orders_of_magnitude.py"],
                             prompt="Refactor orders_of_magnitude.py")
            pasted = str(Path(tmp) / "script" / "magnitude_infographic.py")
            seen, seam = self._capture(agent)
            with seam, patch.object(agent, "_triage_scope",
                                    return_value=[pasted]):
                agent._handle_edit(
                    "execute the plan for " + pasted, "s1", False)

        self.assertEqual(seen["files"], [pasted])
        # A differently scoped turn does not inherit the stale plan's goal.
        self.assertNotIn("Refactor orders_of_magnitude.py", seen["goal"])
        self.assertIn("magnitude_infographic.py", seen["goal"])

    def test_scope_is_triaged_from_the_current_prompt_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent = _agent(tmp)
            (root / "orders.py").write_text("x = 1\n", encoding="utf-8")
            (root / "infographic.py").write_text("y = 2\n", encoding="utf-8")
            self._prior_plan(root, "s2", ["orders.py"])
            seen, seam = self._capture(agent)
            with seam:
                agent._handle_edit(
                    "execute the plan for infographic.py", "s2", False)

        self.assertEqual(seen["files"], ["infographic.py"])

    def test_a_directive_with_no_target_still_resumes_the_prior_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent = _agent(tmp)
            (root / "orders.py").write_text("x = 1\n", encoding="utf-8")
            self._prior_plan(root, "s3", ["orders.py"])
            seen, seam = self._capture(agent)
            with seam, patch.object(agent, "_triage_scope", return_value=[]):
                agent._handle_edit("execute the plan", "s3", False)

        self.assertEqual(seen["files"], ["orders.py"])
        self.assertTrue(seen["goal"].startswith("Refactor orders.py"))
        self.assertIn("[EXECUTION DIRECTIVE]: execute the plan", seen["goal"])


if __name__ == "__main__":
    unittest.main()
