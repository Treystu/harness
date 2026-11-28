"""#683 batch 10: the canary lifecycle, over-budget attempts, overrun outcomes.

Rows 39, 58, 70 and 71 were still present on `main` at `8fc28a0e`:

* row 39 -- the canary due predicate had no production caller, so startup,
  daily and staleness triggers never ran a probe;
* row 58 -- a paid escalation rung whose cost crossed ``--task-max-cost``
  raised before writing an attempt row, losing the overrun from replay;
* row 70 -- a billed response the ceiling rejects was recorded with
  ``outcome="refused"``, which means the call never ran;
* row 71 -- a task-scope refusal recorded only the global envelope, so the
  rejecting allowance and its balances were missing.

These tests drive the real ledger, the real trace family and the real
governor; nothing restates the implementation with a double.
"""
import os
import tempfile
from types import SimpleNamespace
from unittest import TestCase, mock

from harness import ledger_canary, ledger_sweep, server
from harness.apply_state import RunState
from harness.decision_trace import DecisionTrace, read_trace_events
from harness.errors import HarnessError
from harness.escalation import ATTEMPT_EVENT, EscalationDriver
from harness.ledger import AutonomyLedger
from harness.router import Router
from harness.spend import REFUSAL_EVENT, SpendGovernor


def _ledger():
    directory = tempfile.TemporaryDirectory()
    ledger = AutonomyLedger(os.path.join(directory.name, "ledger.jsonl"))
    return directory, ledger


def _canary_rows(ledger):
    return [row for row in ledger.entries()
            if row.get("event") == ledger_canary.CANARY_EVENT]


class CanaryLifecycleTests(TestCase):
    def test_startup_runs_the_probes_and_records_each_one(self):
        directory, ledger = _ledger()
        self.addCleanup(directory.cleanup)

        result = ledger_canary.maybe_run_canaries(ledger, startup=True)

        self.assertTrue(result["ran"])
        self.assertIn("startup", result["reasons"])
        self.assertTrue(_canary_rows(ledger))
        self.assertTrue(all(row.get("canary") is True
                            for row in _canary_rows(ledger)))
        self.assertTrue(all("startup" in str(row.get("trigger") or "")
                            for row in _canary_rows(ledger)))

    def test_a_fresh_run_is_not_due_again_in_the_same_window(self):
        directory, ledger = _ledger()
        self.addCleanup(directory.cleanup)
        moment = 1_800_000_000.0

        ledger_canary.maybe_run_canaries(ledger, now=moment)
        again = ledger_canary.maybe_run_canaries(ledger, now=moment + 60)

        self.assertFalse(again["ran"])
        self.assertEqual(again["outcomes"], [])

    def test_the_periodic_sweep_runs_due_canaries(self):
        directory, ledger = _ledger()
        self.addCleanup(directory.cleanup)
        state_file = os.path.join(directory.name, "sweep-state")

        result = ledger_sweep.run_daily_sweep(
            ledger, now=1_800_000_000.0, state_file=state_file, force=True)

        self.assertTrue(result["canaries"]["ran"])
        self.assertTrue(_canary_rows(ledger))

    def test_the_five_minute_timer_carries_the_canary_check(self):
        directory, ledger = _ledger()
        self.addCleanup(directory.cleanup)
        sweeper = ledger_sweep.LedgerSweeper(lambda: ledger,
                                             clock=lambda: 1_800_000_000.0)

        result = sweeper.tick(force=True)

        self.assertEqual(result["canaries"]["ran"], True)
        self.assertTrue(_canary_rows(ledger))

    def test_serve_startup_probes_the_ledger_and_starts_the_timer(self):
        directory, _ledger_unused = _ledger()
        self.addCleanup(directory.cleanup)
        path = os.path.join(directory.name, "serve-ledger.jsonl")
        settings = SimpleNamespace(ledger_path=path)

        with mock.patch.object(server, "load_settings", return_value=settings):
            sweeper = server._start_ledger_health()
        self.assertIsNotNone(sweeper)
        try:
            rows = [row for row in AutonomyLedger(path).entries()
                    if row.get("event") == ledger_canary.CANARY_EVENT]
            self.assertTrue(rows)
        finally:
            sweeper.stop()

    def test_a_machine_without_a_ledger_has_nothing_to_probe(self):
        with mock.patch.object(server, "load_settings",
                               side_effect=HarnessError("no config")):
            self.assertIsNone(server._start_ledger_health())


class _FakeGov:
    def __init__(self):
        self.spent = 0.0

    def preflight(self, prompt, calls):
        pass

    def record_actual(self, cost, model):
        self.spent += float(cost or 0.0)

    def record_byok(self, model):
        pass

    def check_byok(self, model):
        pass

    def is_free(self, model):
        return False


def _chat_billed(cost):
    def fake_chat(transport, api_key, model, messages, max_tokens, effort,
                  budget, governor):
        return 200, {
            "choices": [{"message": {"content": "content"},
                         "finish_reason": "stop"}],
            "usage": {"cost": cost, "is_byok": False},
        }

    return fake_chat


class OverBudgetAttemptTests(TestCase):
    def test_a_rung_that_runs_past_the_task_budget_is_recorded(self):
        router = Router(panel=["a"], judge="j", apply_model="a",
                        allow_escalation=True, escalation_pool=["r0"])
        directory, ledger = _ledger()
        self.addCleanup(directory.cleanup)
        ledger.append("offer", task_id="task-58")
        driver = EscalationDriver(
            router, transport=None, api_key="k", governor=_FakeGov(),
            ledger=ledger, task_id="task-58", trace=DecisionTrace(ledger),
            task_max_cost=0.10, task_start_spent=0.0)
        state = RunState(rounds=[], history=[], current_content="x")
        req = SimpleNamespace(allow_escalation=None, model="primary")

        with mock.patch("harness.escalation.chat_routed",
                        side_effect=_chat_billed(0.20)):
            with self.assertRaises(HarnessError):
                driver.run_with_escalation(
                    req, state, lambda st, ctx: "prompt",
                    lambda model, content, cost: {"status": "ok"})

        rows = read_trace_events(ledger, kinds=[ATTEMPT_EVENT])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "over_budget")
        self.assertFalse(rows[0]["realized_pass"])
        self.assertAlmostEqual(rows[0]["cost"], 0.20, places=6)
        self.assertIn("task-max-cost", rows[0]["reason"])


class RefusalOutcomeTests(TestCase):
    def _governor(self, ledger, **kwargs):
        return SpendGovernor(
            transport=None, api_key="k", trace=DecisionTrace(ledger),
            **kwargs)

    def _rows(self, ledger):
        return read_trace_events(ledger, kinds=[REFUSAL_EVENT])

    def test_a_billed_response_the_ceiling_rejects_is_not_called_refused(self):
        directory, ledger = _ledger()
        self.addCleanup(directory.cleanup)
        governor = self._governor(ledger, max_cost=0.01)

        with self.assertRaises(HarnessError):
            governor.record_actual(0.02, "billed-call")

        row = self._rows(ledger)[-1]
        self.assertEqual(row["site"], "record_actual")
        self.assertEqual(row["outcome"], "failed")

    def test_a_pre_dispatch_refusal_still_says_the_call_did_not_run(self):
        directory, ledger = _ledger()
        self.addCleanup(directory.cleanup)
        governor = self._governor(ledger, max_cost=0.01)

        with self.assertRaises(HarnessError):
            governor.reserve(0.02, "apply_candidate")

        self.assertEqual(self._rows(ledger)[-1]["outcome"], "refused")

    def test_a_scope_refusal_carries_the_rejecting_scope_budget(self):
        directory, ledger = _ledger()
        self.addCleanup(directory.cleanup)
        governor = self._governor(ledger, max_cost=1.0)

        with governor.task_scope(0.01, label="tiny"):
            with self.assertRaises(HarnessError):
                governor.reserve(0.02, "work")

        row = self._rows(ledger)[-1]
        self.assertEqual(row["site"], "task_scope")
        self.assertEqual(row["scope"], "tiny")
        self.assertEqual(row["outcome"], "refused")
        self.assertEqual(row["scope_envelope"]["allowance"], 0.01)
        self.assertEqual(row["scope_envelope"]["spent"], 0.0)
        self.assertEqual(row["scope_envelope"]["outstanding"], 0.0)
        self.assertAlmostEqual(row["scope_envelope"]["remaining"], 0.01)

    def test_a_scope_overrun_on_a_billed_call_is_an_overrun(self):
        directory, ledger = _ledger()
        self.addCleanup(directory.cleanup)
        governor = self._governor(ledger, max_cost=1.0)

        with governor.task_scope(0.01, label="tiny"):
            with self.assertRaises(HarnessError):
                governor.record_actual(0.02, "billed-call")

        row = self._rows(ledger)[-1]
        self.assertEqual(row["site"], "task_scope")
        self.assertEqual(row["outcome"], "failed")
        self.assertEqual(row["scope_envelope"]["allowance"], 0.01)
        self.assertAlmostEqual(row["scope_envelope"]["remaining"], 0.01)
