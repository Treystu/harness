"""#683 finding 7: an explicit Fireworks budget of zero is a prohibition.

``SpendGovernor.assert_fireworks_budget`` reads zero as "refuse every
Fireworks call", and zero is also the settings default. ``governor_for`` used
to replace a zero with the whole run budget whenever a Fireworks key was
present, so an operator who wrote ``HARNESS_FIREWORKS_BUDGET_USD=0`` silently
got a cap of ``max_cost``. These tests pin the distinction between "unset"
and "explicitly zero".
"""
import unittest
from types import SimpleNamespace
from unittest import mock

from harness import session


class _RecordingGovernor:
    """Stands in for SpendGovernor: records the kwargs, never dispatches."""

    instances = []

    def __init__(self, transport, key, label, max_cost, **kwargs):
        self.key = key
        self.max_cost = max_cost
        self.kwargs = kwargs
        type(self).instances.append(self)

    def verify_key(self):
        return True


def _settings(explicit, budget=0.0):
    return SimpleNamespace(
        use_meta=False,
        use_fireworks=False,
        fireworks_key="fw-key",
        fireworks_budget_usd=budget,
        fireworks_budget_explicit=explicit,
        max_cost=0.15,
        expect_key_label=None,
    )


class ExplicitFireworksBudgetTests(unittest.TestCase):
    def setUp(self):
        _RecordingGovernor.instances = []
        patches = [
            mock.patch.object(session, "SpendGovernor", _RecordingGovernor),
            mock.patch.object(session, "HttpTransport", lambda *a, **k: object()),
            mock.patch.object(session, "resolve_api_key", lambda: "or-key"),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_an_explicit_zero_is_honored_not_replaced_by_the_run_budget(self):
        session.governor_for(_settings(explicit=True))
        (gov,) = _RecordingGovernor.instances
        self.assertEqual(gov.kwargs["fireworks_budget_usd"], 0.0)

    def test_an_unset_budget_still_takes_the_run_budget(self):
        session.governor_for(_settings(explicit=False))
        (gov,) = _RecordingGovernor.instances
        self.assertEqual(gov.kwargs["fireworks_budget_usd"], 0.15)

    def test_a_positive_budget_is_never_replaced(self):
        session.governor_for(_settings(explicit=True, budget=0.02))
        (gov,) = _RecordingGovernor.instances
        self.assertEqual(gov.kwargs["fireworks_budget_usd"], 0.02)


if __name__ == "__main__":
    unittest.main()
