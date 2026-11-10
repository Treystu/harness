"""Hermetic tests for harness/nl_planner.py (#271 acceptance).

The LLM is always a stub ``chat_fn``: no test may call a live model. The
timeout test uses a hanging stub with an overridden short bound so it stays
fast.
"""
import time
import unittest

from driver_core.actions import DEFAULT_VOCABULARY
from harness import nl_planner
from harness.errors import HarnessError


def _stub(text):
    return lambda prompt: text


class BuildPromptTests(unittest.TestCase):

    def test_prompt_names_the_declared_vocabulary(self):
        prompt = nl_planner.build_nl_plan_prompt("open notepad")
        self.assertIn("ONLY", prompt)
        for name in DEFAULT_VOCABULARY.names():
            self.assertIn(name, prompt)

    def test_prompt_carries_the_request(self):
        prompt = nl_planner.build_nl_plan_prompt("open notepad")
        self.assertIn("open notepad", prompt)


class PlanAcceptanceTests(unittest.TestCase):

    def test_valid_plan_for_open_notepad(self):
        text = ('[{"action": "launch_app", '
                '"params": {"app_name": "notepad"}}]')
        self.assertEqual(
            nl_planner.plan("open notepad", _stub(text)),
            [{"action": "launch_app", "params": {"app_name": "notepad"}}])

    def test_multi_step_plan_preserves_order(self):
        text = ('[{"action": "launch_app", "params": {"app_name": "notepad"}}, '
                '{"action": "type_text", "params": {"text": "hello"}}]')
        self.assertEqual(
            [step["action"] for step in nl_planner.plan("do it", _stub(text))],
            ["launch_app", "type_text"])

    def test_rejects_invented_action(self):
        text = '[{"action": "open_program", "params": {}}]'
        with self.assertRaisesRegex(HarnessError, "undeclared action"):
            nl_planner.plan("open notepad", _stub(text))

    def test_rejects_undeclared_param(self):
        text = ('[{"action": "launch_app", '
                '"params": {"app_name": "notepad", "path": "c:/x"}}]')
        with self.assertRaisesRegex(HarnessError, "undeclared params"):
            nl_planner.plan("open notepad", _stub(text))

    def test_empty_input_is_refused(self):
        for blank in ("", "   "):
            with self.assertRaisesRegex(HarnessError, "non-empty"):
                nl_planner.plan(blank, _stub("[]"))

    def test_empty_llm_response_is_refused(self):
        for blank in ("", "   "):
            with self.assertRaisesRegex(HarnessError, "empty response"):
                nl_planner.plan("open notepad", _stub(blank))

    def test_malformed_json_is_refused(self):
        with self.assertRaisesRegex(HarnessError, "did not return JSON"):
            nl_planner.plan("open notepad", _stub("not json ["))

    def test_non_array_is_refused(self):
        with self.assertRaisesRegex(HarnessError, "must return a JSON array"):
            nl_planner.plan("open notepad", _stub('{"action": "x"}'))

    def test_empty_plan_is_refused(self):
        with self.assertRaisesRegex(HarnessError, "no steps"):
            nl_planner.plan("open notepad", _stub("[]"))

    def test_non_object_step_is_refused(self):
        with self.assertRaisesRegex(HarnessError, "not an object"):
            nl_planner.plan("open notepad", _stub('["launch_app"]'))

    def test_missing_action_name_is_refused(self):
        with self.assertRaisesRegex(HarnessError, "no action name"):
            nl_planner.plan("open notepad", _stub('[{}]'))

    def test_non_object_params_are_refused(self):
        text = '[{"action": "launch_app", "params": "notepad"}]'
        with self.assertRaisesRegex(HarnessError, "must be an object"):
            nl_planner.plan("open notepad", _stub(text))

    def test_failing_llm_call_is_refused(self):
        def boom(prompt):
            raise RuntimeError("down")
        with self.assertRaisesRegex(HarnessError, "failed before returning"):
            nl_planner.plan("open notepad", boom)

    def test_late_llm_call_is_refused(self):
        def hang(prompt):
            time.sleep(30)
        started = time.monotonic()
        with self.assertRaisesRegex(HarnessError, "exceeded"):
            nl_planner.plan("open notepad", hang, timeout=0.2)
        self.assertLess(time.monotonic() - started, 10)

    def test_missing_params_defaults_to_empty(self):
        text = '[{"action": "observe"}]'
        self.assertEqual(
            nl_planner.plan("look", _stub(text)),
            [{"action": "observe", "params": {}}])


if __name__ == "__main__":
    unittest.main()
