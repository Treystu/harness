"""#568: the answer lifecycle holds a delivered plotting script to its claims.

The filed defect: an answer delivered a runnable Matplotlib script with two
linear panels, the right one titled "Log10 scale", ticks at powers of ten over
bars positioned at exponents, and prose placing labels underneath bars the code
anchored inside. The decision record's regression is this file: call the normal
answer lifecycle with a fake generation transport, a stub ledger and the real
checker, and pin the revision and withhold behavior.
"""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from harness.agent import AutonomousAgent
from harness.errors import HarnessError
from harness.answer_plot_consistency import (
    PlotFinding,
    analyse_script,
    check_answer_plot_consistency,
    extract_scripts,
    promises_scale_comparison,
    withhold_script,
)
from harness.config import load_settings
from harness.spend import SpendGovernor  # noqa: F401  (import parity with lane)

PROMPT = ("make me a python script to create the visual please - use log scale "
          "and linear scale toggle to demonstrate variance in scale.")

#: The delivered defect, reduced to the structure the issue quoted: one flag
#: drives both panels, the right panel's title claims log while its default
#: branch sets a linear axis, and the ticks are powers of ten over bars placed
#: at raw positions.
DEFECT = '''Here is the script.

```python
import argparse
import matplotlib.pyplot as plt

ap = argparse.ArgumentParser()
ap.add_argument("--log", dest="log_mode", action="store_true")
args = ap.parse_args()
log_mode = args.log


def make_panel(ax, *, log_mode, title):
    ax.set_title(title)
    if not log_mode:
        ax.set_xscale("linear")
        ax.set_xticks([10 ** k for k in range(0, 121, 10)])
        ax.bar(xs, heights)
    else:
        ax.set_xscale("log")
        ax.set_xticks([10 ** k for k in range(0, 121, 10)])
        ax.bar(xs, heights)


xs = [entry[1] for entry in ENTRIES]
fig, (ax_left, ax_right) = plt.subplots(1, 2, figsize=(14, 5), sharey=True)
make_panel(ax_left, log_mode=False, title="Linear scale")
make_panel(ax_right, log_mode=log_mode, title="Log10 scale (exponent view)")
plt.show()
```

The left plot is linear and the right one is log10.'''


#: A candidate that keeps the promise: one linear panel, one log panel, no
#: bars under power-of-ten ticks, and prose that matches.
CORRECT = '''Here is the script.

```python
import argparse
import matplotlib.pyplot as plt

ap = argparse.ArgumentParser()
ap.add_argument("--log", dest="log_mode", action="store_true")
args = ap.parse_args()

fig, (ax_left, ax_right) = plt.subplots(1, 2, figsize=(14, 5))
ax_left.set_title("Linear scale")
ax_left.set_xscale("linear")
ax_right.set_title("Log10 scale")
ax_right.set_xscale("log")
plt.show()
```

The left plot is linear; the right one is logarithmic.'''


class PlotCheckTests(unittest.TestCase):
    def test_the_filed_defect_is_caught_as_a_title_and_a_missing_contrast(self):
        report = check_answer_plot_consistency(PROMPT, DEFECT)
        self.assertTrue(report.script_found)
        self.assertTrue(report.promise_found)
        self.assertFalse(report.ok)
        checks = {finding.check for finding in report.findings}
        self.assertIn("panel-title", checks)
        self.assertIn("promised-comparison", checks)
        title = next(f for f in report.findings if f.check == "panel-title")
        self.assertIn("Log10 scale", title.detail)
        self.assertIn("ax_right", title.detail)
        self.assertIn("linear", title.detail)

    def test_a_candidate_that_keeps_the_promise_passes(self):
        report = check_answer_plot_consistency(PROMPT, CORRECT)
        self.assertTrue(report.script_found)
        self.assertTrue(report.ok, report.findings)

    def test_an_answer_without_a_plotting_script_is_not_checked(self):
        report = check_answer_plot_consistency(
            "Explain log versus linear axes.", "Log axes compress large ranges.")
        self.assertFalse(report.script_found)
        self.assertTrue(report.ok)
        self.assertEqual(extract_scripts("no code here"), [])

    def test_tick_units_against_bar_positions_are_compared(self):
        findings = analyse_script(DEFECT.split("```python")[1].split("```")[0],
                                  promise=True)
        self.assertIn("tick-units", {finding.check for finding in findings})

    def test_label_placement_against_the_prose_is_compared(self):
        script = '''
import matplotlib.pyplot as plt
fig, ax = plt.subplots()
ax.text(x + 0.5, 0.5, "label", ha="center")
'''
        findings = analyse_script(
            script, promise=False,
            prose="The labels underneath each bar give you the reference")
        self.assertIn("label-placement", {finding.check for finding in findings})

    def test_a_script_that_does_not_parse_is_reported_not_executed(self):
        findings = analyse_script("import matplotlib.pyplot\nthis is not python(",
                                  first_line=7)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].check, "script-parse")
        self.assertGreaterEqual(findings[0].line or 0, 7)

    def test_a_renamed_parameter_still_carries_the_flag_state(self):
        script = """
import argparse
import matplotlib.pyplot as plt

ap = argparse.ArgumentParser()
ap.add_argument("--log", dest="log_mode", action="store_true")
args = ap.parse_args()


def panel(ax, mode):
    if not mode:
        ax.set_xscale("linear")
    else:
        ax.set_xscale("log")


fig, (left, right) = plt.subplots(1, 2)
panel(left, False)
panel(right, log_mode)
"""
        self.assertEqual(analyse_script(script, promise=True), [])

    def test_the_unroller_stops_after_forty_expansions(self):
        lines = ['import matplotlib.pyplot as plt',
                 'fig, (left, right) = plt.subplots(1, 2)',
                 'def panel(ax, mode):',
                 '    ax.set_xscale("linear")']
        lines.extend(['panel(left, False)'] * 41)
        self.assertEqual(analyse_script(chr(10).join(lines)), [])

    def test_the_promise_predicate_needs_both_scales(self):
        self.assertTrue(promises_scale_comparison("log scale and linear scale"))
        self.assertFalse(promises_scale_comparison("only a log plot"))

    def test_withholding_removes_the_script_and_names_the_claim(self):
        kept = withhold_script(DEFECT, [PlotFinding("panel-title", "ax_right says log")])
        self.assertNotIn("```", kept)
        self.assertNotIn("import matplotlib", kept)
        self.assertIn("withheld", kept)
        self.assertIn("ax_right says log", kept)


    def test_loops_try_and_with_blocks_are_walked_without_crashing(self):
        script = '''
import matplotlib.pyplot as plt
fig, (left, right) = plt.subplots(1, 2)
with open("data.json") as handle:
    rows = handle.read()
for row in rows:
    try:
        left.set_yscale("linear")
    except ValueError:
        pass
'''
        self.assertEqual(analyse_script(script), [])

    def test_plain_calls_and_nonconstant_arguments_are_left_alone(self):
        script = '''
import matplotlib.pyplot as plt
fig, ax = plt.subplots()
print("drawing")
ax.set_title(name)
ax.set_xscale(scale)
ax.set_xticks(range(3))
ax.bar(positions, heights)
ax.text(x, y, label)
'''
        self.assertEqual(analyse_script(script), [])
        self.assertEqual(analyse_script("x = 1"), [])

    def test_a_store_false_flag_with_a_short_option_is_read(self):
        script = '''
import argparse
import matplotlib.pyplot as plt
ap = argparse.ArgumentParser()
ap.add_argument("-n", "--normalise", action="store_false")
opts = ap.parse_args()
fig, (left, right) = plt.subplots(1, 2)
'''
        # The figure name is not an axes: only the nested pair is measured.
        self.assertEqual(analyse_script(script), [])

    def test_the_prose_can_carry_the_promise_when_the_request_does_not(self):
        report = check_answer_plot_consistency(
            "make me a script to show variance in scale", DEFECT)
        self.assertTrue(report.promise_found)
        self.assertIn("promised-comparison",
                      {finding.check for finding in report.findings})

    def test_a_prose_override_replaces_the_answer_prose(self):
        report = check_answer_plot_consistency(
            PROMPT, DEFECT, prose_override="Two panels, one comparison.")
        self.assertGreaterEqual(len(report.findings), 1)

    def test_a_top_aligned_label_is_not_flagged(self):
        findings = analyse_script('''
import matplotlib.pyplot as plt
fig, ax = plt.subplots()
ax.text(0.5, 0.5, "label", va="top")
''', prose="the labels underneath the bars")
        self.assertEqual(findings, [])

    def test_withholding_a_script_only_answer_still_explains(self):
        fenced = "```python" + chr(10) + "import matplotlib.pyplot as plt" + chr(10) + "```"
        kept = withhold_script(fenced,
                               [PlotFinding("panel-title", "no title")])
        self.assertNotIn("```", kept)
        self.assertTrue(kept.startswith("I withheld"))


def _settings(root: Path):
    return load_settings({
        "panel_pool": "cheap-test-model",
        "ledger_path": str(root / "ledger.jsonl"),
        "jev_api_key": "jev-test",
        "max_cost": 0.01,
    })


def _pre(*, native=True, strategy="direct_answer"):
    return SimpleNamespace(is_fallback=not native), {
        "native": native, "strategy": strategy,
        "probabilities": ({strategy: 1.0} if native else None),
        "concentration": (1.0 if native else None),
        "cost": 0.000001,
    }


def _post(*, native=True, sufficient=0.95):
    return SimpleNamespace(is_fallback=not native), {
        "native": native, "verdict": "pass" if native else "fail",
        "answer_sufficient": sufficient,
        "iteration_required": False, "plan_required": False,
        "cost": 0.000001,
    }


class ResolvedSettingTests(unittest.TestCase):
    """#683 findings 28-30: resolve values before calling them contradictions."""

    def _checks(self, script, *, promise=False, prose=""):
        return {finding.check
                for finding in analyse_script(script, promise=promise,
                                              prose=prose)}

    def test_power_positions_under_power_ticks_are_not_a_mismatch(self):
        script = '''
import matplotlib.pyplot as plt
fig, ax = plt.subplots()
xs = [10 ** k for k in range(3)]
ax.set_xticks([10 ** k for k in range(3)])
ax.bar(xs, [1, 2, 3])
'''
        self.assertNotIn("tick-units", self._checks(script))

    def test_plain_positions_under_power_ticks_still_are(self):
        script = '''
import matplotlib.pyplot as plt
fig, ax = plt.subplots()
xs = [row[1] for row in ROWS]
ax.set_xticks([10 ** k for k in range(3)])
ax.bar(xs, [1, 2, 3])
'''
        self.assertIn("tick-units", self._checks(script))

    def test_an_argparse_attribute_toggle_does_not_contradict_itself(self):
        # `if args.log:` used to leave both branches unresolved, so the linear
        # branch's title and the log branch's scaler were compared.
        script = '''
import argparse
import matplotlib.pyplot as plt

ap = argparse.ArgumentParser()
ap.add_argument("--log", dest="log_mode", action="store_true")
args = ap.parse_args()
fig, ax = plt.subplots()
if args.log_mode:
    ax.set_title("Log scale")
    ax.set_xscale("log")
else:
    ax.set_title("Linear scale")
    ax.set_xscale("linear")
'''
        self.assertNotIn("panel-title", self._checks(script))

    def test_a_later_scale_override_is_the_effective_one(self):
        script = '''
import matplotlib.pyplot as plt
fig, ax = plt.subplots()
ax.set_title("Log scale")
ax.set_xscale("linear")
ax.set_xscale("log")
'''
        self.assertNotIn("panel-title", self._checks(script))

    def test_a_title_that_disagrees_with_the_final_scales_is_still_reported(self):
        script = '''
import matplotlib.pyplot as plt
fig, ax = plt.subplots()
ax.set_title("Log scale")
ax.set_xscale("log")
ax.set_xscale("linear")
'''
        findings = [finding for finding in analyse_script(script)
                    if finding.check == "panel-title"]
        self.assertEqual(len(findings), 1)
        self.assertIn("x=linear", findings[0].detail)


class AnswerPlotLifecycleTests(unittest.TestCase):
    """The lifecycle holds the candidate, revises once, then withholds."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.agent = AutonomousAgent(
            settings=_settings(self.root), root_dir=self.root,
            history_dir=self.root, transport=MagicMock())
        self.gov = MagicMock()
        self.ledger = MagicMock()

    def _run(self, answers):
        policy = MagicMock()
        policy.evaluate_simple_strategy.return_value = _pre()
        policy.evaluate_answer.return_value = _post()
        completions = [
            answer if not isinstance(answer, str) else
            {"content": answer, "model": "cheap-test-model",
             "cost": 0.000002, "input_tokens": 21, "output_tokens": 9,
             "cost_estimated": False}
            for answer in answers
        ]
        with (
            patch("harness.simple_answer_lifecycle.governor_for",
                  return_value=("key", self.gov)),
            patch("harness.simple_answer_lifecycle.policy_for",
                  return_value=policy),
            patch("harness.simple_answer_lifecycle.ledger_for",
                  return_value=self.ledger),
            patch("harness.simple_answer_lifecycle.governed_completion",
                  side_effect=completions) as generate,
            patch("harness.simple_answer_lifecycle.load_chat_history",
                  return_value=[]),
            # The routing boundary is not what this regression measures: the
            # subject is what the answer lifecycle releases once generation
            # has produced a plotting script.
            patch("harness.simple_answer_lifecycle.is_simple_answer_request",
                  return_value=True),
        ):
            result = self.agent.run_simple_request(PROMPT, session_id="plot-test")
        return result, generate

    def test_one_revision_names_the_branch_and_only_the_fix_is_delivered(self):
        result, generate = self._run([DEFECT, CORRECT])
        self.assertEqual(generate.call_count, 2)
        revision_prompt = generate.call_args_list[1].args[4]
        self.assertIn("panel-title", revision_prompt)
        self.assertIn("ax_right", revision_prompt)
        self.assertIn("Log10 scale (exponent view)", revision_prompt)
        self.assertEqual(result["response"], CORRECT)
        self.assertEqual(result["status"], "ok")
        review = result["simple_request"]["plot_consistency"]
        self.assertEqual(review["revisions"], 1)
        self.assertFalse(review["withheld"])
        self.assertEqual(review["findings"], [])

    def test_a_repeated_contradiction_withholds_the_script(self):
        result, generate = self._run([DEFECT, DEFECT])
        self.assertEqual(generate.call_count, 2)
        self.assertNotIn("import matplotlib", result["response"])
        self.assertIn("withheld", result["response"])
        self.assertIn("ax_right", result["response"])
        review = result["simple_request"]["plot_consistency"]
        self.assertEqual(review["revisions"], 1)
        self.assertTrue(review["withheld"])

    def test_a_failed_revision_withholds_rather_than_shipping_the_defect(self):
        # The revision call itself can fail; the defect must still not ship.
        result, generate = self._run([DEFECT, HarnessError("provider down")])
        self.assertEqual(generate.call_count, 2)
        self.assertNotIn("import matplotlib", result["response"])
        self.assertIn("ax_right", result["response"])
        review = result["simple_request"]["plot_consistency"]
        self.assertEqual(review["revisions"], 0)
        self.assertTrue(review["withheld"])

    def test_a_clean_candidate_is_delivered_without_a_revision(self):
        result, generate = self._run([CORRECT])
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(result["response"], CORRECT)
        review = result["simple_request"]["plot_consistency"]
        self.assertEqual(review["revisions"], 0)
        self.assertFalse(review["withheld"])

    def test_an_ordinary_answer_carries_no_plot_review_block(self):
        result, generate = self._run(["Spread peanut butter on the bread."])
        self.assertEqual(generate.call_count, 1)
        self.assertNotIn("plot_consistency", result["simple_request"])


if __name__ == "__main__":
    unittest.main()
