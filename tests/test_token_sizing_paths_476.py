"""#476: the two run-sizing paths, pinned so their divergence cannot drift unseen.

`TokenBudget(...)` sizes a run from the flat defaults (200,000 in / 64,000 out,
overridable by settings). `TokenBudget.for_model(...)` instead derives its
allowance from a resolved model spec: context window x 0.75, clamped to
[64_000, 2_000_000], with output = min(spec max output, 35% of the input).

At `model_id=None` the dynamic path resolves `DEFAULT_MODEL_SPEC` and therefore
sizes a run at **96,000 in / 8,192 out** -- 2.08x less input and 7.81x less
output than the flat defaults. #476 asks which sizing policy each lane should
have; until that is decided (the item's ship rule is blocked on measured-spend
ground truth), the divergence must at least be *recorded and pinned* rather than
rediscovered: a change to the fallback spec, the safe ratio, or the clamps now
shows up as a red test instead of a silent resizing of every no-model run.

Measurement only: no production code is touched here, and no policy is chosen.
"""

import unittest

import harness.token_budget as tb
from harness.dynamic_allocation import (DEFAULT_MODEL_SPEC, dynamic_run_token_budget,
                                        resolve_model_spec)

#: The values measured on 2026-11-14 from this checkout (#476 census).
MEASURED_DYNAMIC_AT_NONE = (96_000, 8_192)
MEASURED_FLAT = (200_000, 64_000)


class FlatDefaultsTests(unittest.TestCase):
    def test_constructor_defaults_are_the_flat_run_budgets(self):
        self.assertEqual((tb.DEFAULT_RUN_INPUT_TOKENS, tb.DEFAULT_RUN_OUTPUT_TOKENS),
                         MEASURED_FLAT)

    def test_a_plain_budget_uses_the_flat_defaults(self):
        snap = tb.TokenBudget("run").snapshot()
        self.assertEqual((snap["max_input_tokens"], snap["max_output_tokens"]),
                         MEASURED_FLAT)


class DynamicPathTests(unittest.TestCase):
    def test_no_model_resolves_the_default_spec(self):
        self.assertEqual(resolve_model_spec(None), DEFAULT_MODEL_SPEC)

    def test_no_model_sizes_from_the_default_spec_not_the_flat_defaults(self):
        self.assertEqual(dynamic_run_token_budget(None), MEASURED_DYNAMIC_AT_NONE)
        snap = tb.TokenBudget.for_model(None).snapshot()
        self.assertEqual((snap["max_input_tokens"], snap["max_output_tokens"]),
                         MEASURED_DYNAMIC_AT_NONE)

    def test_the_divergence_is_the_recorded_factor(self):
        dynamic_in, dynamic_out = MEASURED_DYNAMIC_AT_NONE
        self.assertAlmostEqual(MEASURED_FLAT[0] / float(dynamic_in), 2.08, places=2)
        self.assertAlmostEqual(MEASURED_FLAT[1] / float(dynamic_out), 7.81, places=2)

    def test_the_derivation_rules_hold_for_a_known_model(self):
        model = "deepseek/deepseek-v4.1-flash"
        spec = resolve_model_spec(model)
        in_tokens, out_tokens = dynamic_run_token_budget(model)
        self.assertEqual(in_tokens,
                         max(64_000, min(int(spec.context_window * 0.75), 2_000_000)))
        self.assertEqual(out_tokens,
                         min(spec.max_output_tokens, int(in_tokens * 0.35)))

    def test_the_input_allowance_stays_inside_its_clamps(self):
        for model in (None, "accounts/fireworks/models/kimi-k3",
                      "nvidia/nemotron-3-ultra-nvfp4"):
            in_tokens, _ = dynamic_run_token_budget(model)
            self.assertGreaterEqual(in_tokens, 64_000, model)
            self.assertLessEqual(in_tokens, 2_000_000, model)


if __name__ == "__main__":
    unittest.main()
