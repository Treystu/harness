"""Tests for #453 S3a: panel_judge under jev_primary_mode.

Under the mode, the Jev claim-support path is the primary judgment route:
it runs whenever a policy is wired (the separate jev_claim_support flag no
longer gates it), and every verdict envelope names its route —
"jev_primary" only when the Jev path actually ran, otherwise
"llm_fallback" with a reason. With the mode off, behavior is unchanged:
no route keys, claim support only under its own flag.
"""
import unittest

from harness.panel import panel_judge
from tests._fake import FakeTransport, m, comp, _gov, P1, P2, JUDGE


class StubPolicy:
    def __init__(self, *, error=None):
        self.calls = []
        self.error = error

    def evaluate_claim_support(self, texts, evidence, **kwargs):
        self.calls.append((texts, evidence, kwargs))
        if self.error is not None:
            raise self.error
        return object(), {"claim_flags": [], "supported": True}


def _run(**kwargs):
    fake = FakeTransport(models=[m(P1), m(P2), m(JUDGE)],
                         posts=[comp("take one"), comp("take two"),
                                comp("verdict: agree")])
    gov = _gov(fake)
    return panel_judge(transport=fake, api_key="k", governor=gov,
                       prompt="Q?", panel=[P1, P2], judge=JUDGE, **kwargs)


class JevPrimaryModePanelTests(unittest.TestCase):
    def test_mode_off_no_route_keys_and_no_jev_call(self):
        policy = StubPolicy()
        result = _run(jev_policy=policy)
        self.assertEqual(policy.calls, [])
        self.assertNotIn("judgment_route", result)
        self.assertNotIn("claim_support", result)

    def test_mode_off_claim_support_stays_opt_in(self):
        policy = StubPolicy()
        result = _run(jev_policy=policy, jev_claim_support=True)
        self.assertEqual(len(policy.calls), 1)
        self.assertIn("claim_support", result)
        self.assertNotIn("judgment_route", result)

    def test_mode_on_runs_jev_without_the_opt_in_flag(self):
        policy = StubPolicy()
        result = _run(jev_policy=policy, jev_primary_mode=True)
        self.assertEqual(len(policy.calls), 1)
        self.assertEqual(result["judgment_route"], "jev_primary")
        self.assertNotIn("judgment_route_reason", result)
        self.assertIn("claim_support", result)

    def test_mode_on_without_policy_names_the_fallback(self):
        result = _run(jev_primary_mode=True)
        self.assertEqual(result["judgment_route"], "llm_fallback")
        self.assertEqual(result["judgment_route_reason"],
                         "jev_policy_absent")

    def test_mode_on_skipped_without_claims_names_no_claims(self):
        class SkippingPolicy(StubPolicy):
            def evaluate_claim_support(self, texts, evidence, **kwargs):
                self.calls.append((texts, evidence, kwargs))
                return object(), {
                    "claim_flags": [], "skipped": True,
                    "is_fallback": True, "fallback_reason": "missing_key",
                }

        policy = SkippingPolicy()
        result = _run(jev_policy=policy, jev_primary_mode=True)
        self.assertEqual(result["judgment_route"], "llm_fallback")
        self.assertEqual(result["judgment_route_reason"], "jev_no_claims")

    def test_mode_on_non_skipped_jev_fallback_names_its_reason(self):
        class FallbackPolicy(StubPolicy):
            def evaluate_claim_support(self, texts, evidence, **kwargs):
                self.calls.append((texts, evidence, kwargs))
                return object(), {
                    "claim_flags": [], "is_fallback": True,
                    "fallback_reason": "transport_failure",
                }

        policy = FallbackPolicy()
        result = _run(
            jev_policy=policy, jev_primary_mode=True,
            claim_texts=[{"id": "c1", "text": "the gateway retries"}],
        )
        self.assertEqual(result["judgment_route"], "llm_fallback")
        self.assertEqual(result["judgment_route_reason"],
                         "jev_fallback: transport_failure")
        self.assertTrue(result["claim_support"]["is_fallback"])

    def test_mode_on_without_a_claim_support_record_names_jev_not_run(self):
        """A policy that returns no record is a named fallback, not silence.

        The Jev path ran, the claims were non-empty, and nothing reported an
        error or a skip -- so the only honest reading is that the Jev
        judgment did not happen. Naming that ``jev_not_run`` is the
        difference between a measured fallback and an LLM verdict that looks
        like the mode's judgment because no key was set.
        """

        class EmptyPolicy(StubPolicy):
            def evaluate_claim_support(self, texts, evidence, **kwargs):
                self.calls.append((texts, evidence, kwargs))
                return object(), None

        policy = EmptyPolicy()
        result = _run(jev_policy=policy, jev_primary_mode=True,
                      claim_texts=[{"id": "c1",
                                    "text": "the gateway retries"}])
        self.assertEqual(len(policy.calls), 1)
        self.assertEqual(result["judgment_route"], "llm_fallback")
        self.assertEqual(result["judgment_route_reason"], "jev_not_run")

    def test_mode_on_jev_error_names_the_fallback(self):
        policy = StubPolicy(error=RuntimeError("jev down"))
        result = _run(jev_policy=policy, jev_primary_mode=True)
        self.assertEqual(result["judgment_route"], "llm_fallback")
        self.assertTrue(
            result["judgment_route_reason"].startswith("jev_error:"))
        self.assertIn("jev down", result["judgment_route_reason"])


if __name__ == "__main__":
    unittest.main()
