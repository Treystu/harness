"""Issue #471: escalation attempts carry start rung, attempted rung, realized pass.

The Champion brief for Jev-directed escalation rung mapping could not execute
because no escalation history existed: the driver recorded the model it called
but never the rung it chose, the rung it attempted, or whether that attempt's
verify gate passed. Those three facts are now written per attempt through the
shared trace writer (`DecisionTrace` over the hash-chained `AutonomyLedger`),
so the mapping can be replayed from the record rather than re-derived from a
summary.
"""
import os
import tempfile
from types import SimpleNamespace
from unittest import mock, TestCase

from harness.apply_state import RunState
from harness.decision_trace import DecisionTrace, read_trace_events
from harness.escalation import ATTEMPT_EVENT, EscalationDriver
from harness.ledger import AutonomyLedger
from harness.router import Router


class FakeGov:
    def __init__(self):
        self.spent = 0.0
        self.max_cost = 1.0

    def preflight(self, prompt, calls):
        pass

    def record_actual(self, cost, model):
        self.spent += float(cost or 0)

    def record_byok(self, model):
        pass

    def check_byok(self, model):
        pass

    def is_free(self, model):
        return str(model).endswith(":free")


def _chat(content_for, byok=()):
    def fake_chat(transport, api_key, model, messages, max_tokens, effort,
                  budget, governor):
        status, content = content_for(model)
        if status != 200:
            return status, {"error": {"message": f"HTTP {status}", "cost": 0.0}}
        return 200, {
            "choices": [{"message": {"content": content},
                         "finish_reason": "stop"}],
            "usage": {"cost": 0.0, "is_byok": model in byok},
        }

    return fake_chat


class AttemptTraceTests(TestCase):
    def _run(self, *, pool=("r0", "r1"), finish_model="r1", trace=True,
             content_for=None, state_kwargs=None, allow_escalation=True,
             task_max_cost=None, start_spent=None, byok=()):
        router = Router(panel=["a"], judge="j", apply_model="a",
                        allow_escalation=allow_escalation,
                        escalation_pool=list(pool))
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        ledger = AutonomyLedger(os.path.join(directory.name, "ledger.jsonl"))
        # Every task-scoped row the ledger accepts needs a prior offer.
        ledger.append("offer", task_id="task-471")
        driver = EscalationDriver(
            router, transport=None, api_key="k", governor=FakeGov(),
            ledger=ledger, task_id="task-471",
            trace=DecisionTrace(ledger) if trace else None,
            task_max_cost=task_max_cost, task_start_spent=start_spent)
        state = RunState(rounds=[], history=[], current_content="x")
        for key, value in (state_kwargs or {}).items():
            setattr(state, key, value)
        req = SimpleNamespace(allow_escalation=None, model="primary")

        def finish_fn(model, content, cost):
            return {"status": "ok", "model": model} if model == finish_model else None

        reader = content_for or (lambda model: (200, f"content-{model}"))
        with mock.patch("harness.escalation.chat_routed",
                        side_effect=_chat(reader, byok)):
            result = driver.run_with_escalation(
                req, state, lambda st, ctx: "prompt", finish_fn)
        rows = read_trace_events(ledger, kinds=[ATTEMPT_EVENT])
        return result, rows, ledger, state

    def test_every_attempted_rung_carries_the_three_facts(self):
        result, rows, _ledger, _state = self._run()
        self.assertEqual(result["status"], "ok")
        self.assertEqual([row["rung"] for row in rows], [0, 1])
        self.assertEqual([row["start_rung"] for row in rows], [0, 0])
        self.assertEqual([row["realized_pass"] for row in rows], [False, True])
        self.assertEqual([row["status"] for row in rows], ["ok", "ok"])
        self.assertEqual([row["attempt_id"] for row in rows],
                         ["rung-0", "rung-1"])
        for row in rows:
            self.assertEqual(row["subject_id"], "task-471")
            self.assertEqual(row["spec_ref"], "escalation.run_with_escalation")
            self.assertEqual(row["ladder_size"], 2)

    def test_start_rung_is_the_walk_start_not_the_primary(self):
        _result, rows, _ledger, _state = self._run(
            state_kwargs={"de_escalation_target_rung": 1,
                          "escalation_condensed_context": "judge says start high"})
        self.assertEqual([row["rung"] for row in rows], [1])
        self.assertEqual(rows[0]["start_rung"], 1)

    def test_an_api_error_is_recorded_before_the_rotation(self):
        def content_for(model):
            return (429, "") if model == "r0" else (200, "content")

        _result, rows, _ledger, _state = self._run(content_for=content_for)
        self.assertEqual([row["status"] for row in rows], ["api_error", "ok"])
        self.assertFalse(rows[0]["realized_pass"])
        self.assertTrue(rows[1]["realized_pass"])
        self.assertIn("HTTP 429", rows[0]["reason"])

    def test_unusable_content_is_recorded_without_a_pass(self):
        def content_for(model):
            return (200, "") if model == "r0" else (200, "content")

        _result, rows, _ledger, _state = self._run(content_for=content_for)
        self.assertEqual([row["status"] for row in rows], ["unusable", "ok"])
        self.assertFalse(rows[0]["realized_pass"])

    def test_a_paid_byok_route_is_recorded_and_rotated(self):
        _result, rows, _ledger, _state = self._run(byok=("r0",))
        self.assertEqual([row["status"] for row in rows],
                         ["byok_error", "ok"])
        self.assertFalse(rows[0]["realized_pass"])
        self.assertTrue(rows[1]["realized_pass"])

    def test_a_failed_gate_is_a_recorded_non_pass(self):
        _result, rows, _ledger, _state = self._run(finish_model="never")
        self.assertEqual([row["rung"] for row in rows], [0, 1])
        self.assertEqual([row["realized_pass"] for row in rows], [False, False])

    def test_refusals_write_nothing(self):
        cases = {
            "escalation disabled": dict(allow_escalation=False),
            "empty pool": dict(pool=()),
            "budget exhausted": dict(task_max_cost=0.0, start_spent=0.0),
            "abstain directive": dict(state_kwargs={
                "pending_jev_directive": {"kind": "abstain",
                                          "confidence": 0.2}}),
        }
        for label, kwargs in cases.items():
            with self.subTest(label):
                result, rows, ledger, _state = self._run(**kwargs)
                self.assertIsNone(result)
                self.assertEqual(rows, [])
                events = [entry.get("event") for entry in ledger.tail(50)]
                self.assertNotIn(ATTEMPT_EVENT, events)

    def test_without_a_trace_the_driver_writes_no_attempt_rows(self):
        _result, rows, ledger, state = self._run(trace=False)
        self.assertEqual(rows, [])
        events = [entry["event"] for entry in ledger.tail(50)]
        self.assertNotIn(ATTEMPT_EVENT, events)
        self.assertEqual([round_["status"] for round_ in state.rounds],
                         ["ok", "ok"])

    def test_a_reader_re_derives_ordering_and_promotion(self):
        _result, rows, ledger, _state = self._run()
        recorded = read_trace_events(ledger, kinds=[ATTEMPT_EVENT])
        order = [row["rung"] for row in recorded]
        self.assertEqual(order, sorted(order))
        passes = [row["rung"] for row in recorded if row["realized_pass"]]
        self.assertEqual(passes, [max(order)])
        self.assertEqual({row["start_rung"] for row in recorded}, {0})

    def test_chain_still_verifies_after_the_write(self):
        _result, _rows, ledger, _state = self._run()
        ok, detail = ledger.verify()
        self.assertTrue(ok, detail)
