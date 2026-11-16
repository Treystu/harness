"""#285: selection and chaining scored as a pass rate, with the negative control.

The layer exists to answer one question with a number: given a task, does the
agent pick the right tool and chain the right calls? The tests pin the scoring
rules (order matters in chain mode, extras are mistakes, a prefix is allowed
where declared), the aggregate and threshold behaviour, the two modes -- a
recorded transcript in CI, a live run that must name its model and cost -- and
the negative control: a deliberately wrong expectation has to FAIL its case, or
the runner is not measuring anything.
"""
import json
import os
import tempfile
import unittest

from harness import agent_eval as ev

# Resolved through the module, so the paths are right in the repo tree and in
# the composed overlay tree alike (a test that hard-codes its own directory fails
# the moment it is placed beside the other suites).
PATHS = ev.default_paths()
PACK = PATHS["eval_set"]
RECORDED = PATHS["transcript"]


def case(case_id="c1", expected=("ask",), mode="chain", allow_extra=False):
    return {"id": case_id, "prompt": "p", "expected": list(expected),
            "mode": mode, "allow_extra": allow_extra}


class DeclaredSetTests(unittest.TestCase):
    def test_the_shipped_set_loads(self):
        cases = ev.load_eval_set(PACK)
        self.assertEqual(len(cases), 12)
        self.assertEqual(len({c["id"] for c in cases}), 12)

    def test_every_case_declares_a_prompt_and_a_chain(self):
        for entry in ev.load_eval_set(PACK):
            self.assertTrue(entry["prompt"])
            self.assertTrue(entry["expected"])
            self.assertIn(entry["mode"], ev.MATCH_MODES)

    def test_the_newest_tool_surface_is_represented(self):
        names = {tool for entry in ev.load_eval_set(PACK) for tool in entry["expected"]}
        for tool in ("ask", "panel_verify", "apply_edit", "driver_step",
                     "mission_status", "route_query"):
            self.assertIn(tool, names)

    def test_a_set_without_cases_is_refused(self):
        path = os.path.join(tempfile.mkdtemp(prefix="eval-empty-"), "e.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"cases": []}, handle)
        with self.assertRaises(ev.EvalError):
            ev.load_eval_set(path)

    def test_a_duplicate_case_id_is_refused(self):
        path = os.path.join(tempfile.mkdtemp(prefix="eval-dup-"), "e.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"cases": [{"id": "a", "prompt": "p",
                                  "expect": {"tools": ["ask"]}},
                                 {"id": "a", "prompt": "q",
                                  "expect": {"tools": ["ask"]}}]}, handle)
        with self.assertRaises(ev.EvalError):
            ev.load_eval_set(path)

    def test_an_unknown_mode_is_refused(self):
        path = os.path.join(tempfile.mkdtemp(prefix="eval-mode-"), "e.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"cases": [{"id": "a", "prompt": "p",
                                  "expect": {"tools": ["ask"], "mode": "fuzzy"}}]},
                      handle)
        with self.assertRaises(ev.EvalError):
            ev.load_eval_set(path)


class ScoringTests(unittest.TestCase):
    def test_an_exact_chain_passes(self):
        row = ev.score_case(case(expected=("ledger_status", "participation_report")),
                            ["ledger_status", "participation_report"])
        self.assertTrue(row["pass"])

    def test_a_reordered_chain_fails(self):
        row = ev.score_case(case(expected=("a", "b")), ["b", "a"])
        self.assertFalse(row["pass"])
        self.assertIn("expected chain", row["reason"])

    def test_an_extra_call_fails_unless_allowed(self):
        self.assertFalse(ev.score_case(case(expected=("apply_edit",)),
                                       ["apply_edit", "ledger_status"])["pass"])
        self.assertTrue(ev.score_case(case(expected=("apply_edit",), allow_extra=True),
                                      ["apply_edit", "ledger_status"])["pass"])

    def test_set_mode_ignores_order(self):
        row = ev.score_case(case(expected=("a", "b"), mode="set"), ["b", "a"])
        self.assertTrue(row["pass"])

    def test_set_mode_refuses_a_missing_tool(self):
        row = ev.score_case(case(expected=("a", "b"), mode="set"), ["a"])
        self.assertFalse(row["pass"])

    def test_prefix_mode_accepts_a_longer_plan(self):
        row = ev.score_case(case(expected=("plan_and_execute",), mode="prefix"),
                            ["plan_and_execute", "apply_edit"])
        self.assertTrue(row["pass"])

    def test_prefix_mode_rejects_a_wrong_start(self):
        row = ev.score_case(case(expected=("plan_and_execute",), mode="prefix"),
                            ["ask"])
        self.assertFalse(row["pass"])

    def test_no_calls_fails_the_case(self):
        self.assertFalse(ev.score_case(case(), [])["pass"])


class RunTests(unittest.TestCase):
    def test_the_recorded_run_scores_ten_of_twelve(self):
        cases = ev.load_eval_set(PACK)
        transcript = ev.load_transcript(RECORDED)
        result = ev.run_eval(cases, transcript["calls"])
        self.assertEqual(result["mode"], "hermetic")
        self.assertEqual(result["aggregate"]["cases"], 12)
        self.assertEqual(result["aggregate"]["passed"], 10)
        self.assertEqual(result["aggregate"]["pass_rate"], 0.8333)
        self.assertTrue(result["aggregate"]["meets_threshold"])

    def test_the_negative_control_fails_its_case(self):
        cases = [c for c in ev.load_eval_set(PACK) if c["id"] == "mcp-negative-control"]
        transcript = ev.load_transcript(RECORDED)
        row = ev.run_eval(cases, transcript["calls"])["cases"][0]
        self.assertFalse(row["pass"])
        self.assertEqual(row["expected"], ["spend_status"])
        self.assertEqual(row["observed"], ["ledger_status"])

    def test_the_extra_call_case_fails_for_the_right_reason(self):
        cases = [c for c in ev.load_eval_set(PACK) if c["id"] == "mcp-apply-edit"]
        transcript = ev.load_transcript(RECORDED)
        row = ev.run_eval(cases, transcript["calls"])["cases"][0]
        self.assertFalse(row["pass"])
        self.assertEqual(row["observed"], ["apply_edit", "ledger_status"])

    def test_a_missing_transcript_entry_fails_rather_than_skips(self):
        result = ev.run_eval([case("absent")], {})
        self.assertFalse(result["cases"][0]["pass"])
        self.assertIn("no call", result["cases"][0]["reason"])

    def test_the_threshold_is_recorded_and_configurable(self):
        cases = ev.load_eval_set(PACK)
        calls = ev.load_transcript(RECORDED)["calls"]
        strict = ev.run_eval(cases, calls, threshold=0.95)
        self.assertEqual(strict["threshold"], 0.95)
        self.assertEqual(strict["aggregate"]["threshold"], 0.95)
        self.assertFalse(strict["aggregate"]["meets_threshold"])
        loose = ev.run_eval(cases, calls, threshold=0.5)
        self.assertTrue(loose["aggregate"]["meets_threshold"])

    def test_the_default_threshold_is_eighty_percent(self):
        self.assertEqual(ev.DEFAULT_THRESHOLD, 0.8)
        result = ev.run_eval([case()], {"c1": ["ask"]})
        self.assertEqual(result["threshold"], 0.8)

    def test_a_bad_threshold_is_refused(self):
        for bad in (-0.1, 1.5, "0.8", True):
            with self.assertRaises(ev.EvalError):
                ev.run_eval([case()], {"c1": ["ask"]}, threshold=bad)


class ModeTests(unittest.TestCase):
    def test_a_live_run_must_name_its_model(self):
        with self.assertRaises(ev.EvalError):
            ev.run_eval([case()], {"c1": ["ask"]}, mode="live", cost_usd=0.0)

    def test_a_live_run_must_report_its_cost(self):
        with self.assertRaises(ev.EvalError):
            ev.run_eval([case()], {"c1": ["ask"]}, mode="live", model="m")

    def test_a_live_run_records_model_and_cost(self):
        result = ev.run_eval([case()], {"c1": ["ask"]}, mode="live",
                             model="openrouter/free", cost_usd=0.0)
        self.assertEqual(result["model"], "openrouter/free")
        self.assertEqual(result["cost_usd"], 0.0)
        self.assertEqual(result["mode"], "live")

    def test_an_unknown_mode_is_refused(self):
        with self.assertRaises(ev.EvalError):
            ev.run_eval([case()], {"c1": ["ask"]}, mode="remote")

    def test_the_render_line_carries_the_rate_and_verdict(self):
        text = ev.render(ev.run_eval(ev.load_eval_set(PACK),
                                     ev.load_transcript(RECORDED)["calls"]))
        self.assertIn("pass_rate=0.8333", text)
        self.assertIn("MEETS", text)
        self.assertEqual(len(text.splitlines()), 12 + 2)  # header, cases, aggregate


if __name__ == "__main__":
    unittest.main()
