"""Hermetic JEV-P1 spend and ledger contracts."""
import os
import tempfile
import unittest

from harness.config import load_settings
from harness.jev_policy import policy_for
from harness.ledger import AutonomyLedger
from harness.spend import SpendGovernor
from tests._fake import FakeTransport, m


class JevLedgerSpendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _ledger(self):
        return AutonomyLedger(os.path.join(self.tmp.name, "ledger.jsonl"))

    @staticmethod
    def _diff():
        return ("--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n"
                "-x = 1\n+x = 2\n")

    def test_live_policy_spends_exactly_once_and_ledgers_once(self):
        jev_transport = FakeTransport(posts=[{
            "model": "jev-test",
            "answers": {"instruction_matches": {
                "type": "noul", "noul": 0.95}},
            "usage": {"input_tokens": 120, "output_tokens": 4},
        }])
        spend_transport = FakeTransport(models=[m("jev-test", prompt="0",
                                                  completion="0")])
        governor = SpendGovernor(spend_transport, "sk-test", max_cost=0.10)
        ledger = self._ledger()
        ledger.ensure_offered_task_id("task-1", source="test_setup")
        settings = load_settings({"jev_api_key": "jev-key"})
        policy = policy_for(settings, transport=jev_transport,
                            governor=governor, ledger=ledger)

        result, envelope = policy.evaluate_diff(
            self._diff(), "change x", "x.py", site="agent-apply",
            task_id="task-1", node_id="node-1")

        expected = 120 * 0.042 / 1_000_000
        self.assertEqual(result.cost, expected)
        self.assertEqual(governor.spent, expected)
        events = [entry for entry in ledger.entries()
                  if entry["event"] == "jev_eval"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["input_tokens"], 120)
        self.assertEqual(events[0]["cost"], expected)
        self.assertEqual(envelope["site"], "agent-apply")

    def test_unkeyed_fallback_never_spends_or_bills(self):
        settings = load_settings()
        settings.jev_api_key = None
        governor = SpendGovernor(FakeTransport(), "sk-test", max_cost=0.10)
        ledger = self._ledger()
        result, envelope = policy_for(
            settings, governor=governor, ledger=ledger).evaluate_diff(
                self._diff(), "change x", "x.py", site="apply")
        self.assertTrue(result.is_fallback)
        self.assertEqual(result.cost, 0.0)
        self.assertEqual(governor.spent, 0.0)
        self.assertEqual([e for e in ledger.entries()
                          if e["event"] == "jev_eval"][0]["cost"], 0.0)
        self.assertTrue(envelope["is_fallback"])

    def test_preflight_reservation_is_released_on_transport_failure(self):
        class FailingTransport(FakeTransport):
            def post(self, *args, **kwargs):
                raise RuntimeError("provider unavailable")

        settings = load_settings({"jev_api_key": "jev-key"})
        governor = SpendGovernor(FakeTransport(models=[m("jev-test")]),
                                 "sk-test", max_cost=0.10)
        policy = policy_for(settings, transport=FailingTransport(),
                            governor=governor, ledger=self._ledger())
        result, _ = policy.evaluate_diff(
            self._diff(), "change x", "x.py", site="apply")
        self.assertTrue(result.is_fallback)
        self.assertEqual(governor.spent, 0.0)
        self.assertEqual(governor.outstanding, 0.0)

    def test_apply_task_max_cost_preflight_folds_jev_worst_case(self):
        from harness.apply import ApplyEngine
        from harness.errors import HarnessError
        from harness.router import Router
        from tests._fake import comp

        settings = load_settings({"jev_api_key": "jev-key"})
        spend_transport = FakeTransport(
            models=[m("apply/model", prompt="0", completion="0"),
                    m("jev-test", prompt="0", completion="0")],
            posts=[comp("def x(): pass\n"), comp("def x(): pass\n")])
        governor = SpendGovernor(spend_transport, "sk-test", max_cost=1.0)
        ledger = self._ledger()
        policy = policy_for(settings, transport=FakeTransport(posts=[{
            "model": "jev-test",
            "answers": {"instruction_matches": {"type": "noul", "noul": 0.95}},
            "usage": {"input_tokens": 100, "output_tokens": 2},
        }, {
            "model": "jev-test",
            "answers": {"instruction_matches": {"type": "noul", "noul": 0.95}},
            "usage": {"input_tokens": 100, "output_tokens": 2},
        }]), governor=governor, ledger=ledger)

        target = os.path.join(self.tmp.name, "target.py")
        with open(target, "w", encoding="utf-8") as f:
            f.write("x = 1\n")

        router = Router(["apply/model"], "apply/model", "apply/model")
        engine = ApplyEngine(spend_transport, "k", governor, ledger, router,
                             jev_policy=policy, default_require_consent=False,
                             default_renew_consent=False)

        # A task ceiling below the Jev worst-case excludes every candidate.
        # #805 spend-allowance ruling: the named terminal state is
        # SPEND-BLOCKED (an impossibility with evidence), never a bare
        # refusal of the task on the first candidate that did not fit.
        with self.assertRaises(HarnessError) as ctx:
            engine.apply_edit(file_path=target, instruction="edit x",
                              task_max_cost=0.000001, require_consent=False,
                              renew_consent=False)
        self.assertIn("SPEND-BLOCKED", str(ctx.exception))
        excluded = [e for e in ledger.entries()
                    if e["event"] == "model_result"
                    and e.get("status") == "excluded"]
        self.assertEqual(len(excluded), 1)
        self.assertEqual(excluded[0]["reason"], "spend_preflight")
        self.assertEqual(excluded[0]["model"], "apply/model")
        self.assertEqual(excluded[0]["cost"], 0.0)
        self.assertGreater(excluded[0]["jev_component"], 0.0)
        self.assertGreater(excluded[0]["worst_case"],
                           excluded[0]["task_max_cost"])

        # With sufficient budget and governor having preflight_jev, line 315 executes
        from unittest import mock
        with mock.patch.object(governor, "preflight_jev", wraps=governor.preflight_jev) as mock_preflight:
            engine.apply_edit(file_path=target, instruction="edit x",
                              verify_cmd="python -c pass",
                              task_max_cost=0.10, require_consent=False,
                              renew_consent=False)
            self.assertTrue(any(call.kwargs.get("label") == "apply_candidate"
                                for call in mock_preflight.call_args_list))

    def test_apply_escalation_folds_jev_worst_case_and_preflights(self):
        from unittest import mock
        from harness.apply import ApplyEngine
        from harness.errors import HarnessError
        from harness.router import Router
        from tests._fake import comp

        settings = load_settings({"jev_api_key": "jev-key"})
        spend_transport = FakeTransport(
            models=[m("apply/model", prompt="0", completion="0"),
                    m("esc/model", prompt="0", completion="0"),
                    m("jev-test", prompt="0", completion="0")],
            posts=[comp("x = 2\n"), comp("x = 3\n")])
        governor = SpendGovernor(spend_transport, "sk-test", max_cost=1.0)
        ledger = self._ledger()
        policy = policy_for(settings, transport=FakeTransport(posts=[{
            "model": "jev-test",
            "answers": {"instruction_matches": {"type": "noul", "noul": 0.95}},
            "usage": {"input_tokens": 100, "output_tokens": 2},
        }, {
            "model": "jev-test",
            "answers": {"instruction_matches": {"type": "noul", "noul": 0.95}},
            "usage": {"input_tokens": 100, "output_tokens": 2},
        }]), governor=governor, ledger=ledger)

        target = os.path.join(self.tmp.name, "target_esc.py")
        with open(target, "w", encoding="utf-8") as f:
            f.write("x = 1\n")

        router = Router(["apply/model"], "apply/model", "apply/model",
                        allow_escalation=True, escalation_model="esc/model")
        engine = ApplyEngine(spend_transport, "k", governor, ledger, router,
                             jev_policy=policy, default_require_consent=False,
                             default_renew_consent=False)

        # 1. A task ceiling below the Jev reserve excludes the candidate
        # before its first call (#805 spend-allowance ruling): the task is
        # SPEND-BLOCKED with the rejected estimate on the record.
        with self.assertRaises(HarnessError) as ctx:
            engine.apply_edit(file_path=target, instruction="edit x",
                              verify_cmd="python -c exit(1)", max_rounds=1,
                              task_max_cost=0.000001, require_consent=False,
                              renew_consent=False)
        self.assertIn("SPEND-BLOCKED", str(ctx.exception))
        self.assertIn("apply/model", str(ctx.exception))

        # 2. When task_max_cost is sufficient (0.060), lines 623-625, 631-632 execute
        spend_transport2 = FakeTransport(
            models=[m("apply/model", prompt="0", completion="0"),
                    m("esc/model", prompt="0", completion="0"),
                    m("jev-test", prompt="0", completion="0")],
            posts=[comp("def x(): pass\n"), comp("def x(): pass\n")])
        governor2 = SpendGovernor(spend_transport2, "sk-test", max_cost=1.0)
        policy2 = policy_for(settings, transport=FakeTransport(posts=[{
            "model": "jev-test",
            "answers": {"instruction_matches": {"type": "noul", "noul": 0.95}},
            "usage": {"input_tokens": 100, "output_tokens": 2},
        }, {
            "model": "jev-test",
            "answers": {"instruction_matches": {"type": "noul", "noul": 0.95}},
            "usage": {"input_tokens": 100, "output_tokens": 2},
        }]), governor=governor2, ledger=ledger)
        engine2 = ApplyEngine(spend_transport2, "k", governor2, ledger, router,
                              jev_policy=policy2, default_require_consent=False,
                              default_renew_consent=False)

        with mock.patch.object(governor2, "preflight_jev", wraps=governor2.preflight_jev) as mock_preflight:
            engine2.apply_edit(file_path=target, instruction="edit x",
                               verify_cmd="python -c exit(1)", max_rounds=1,
                               task_max_cost=0.060, require_consent=False,
                               renew_consent=False)
            self.assertTrue(any(call.kwargs.get("label") == "apply_escalation"
                                for call in mock_preflight.call_args_list))

    def test_compute_spend_summary_with_jev_tokens(self):
        ledger = self._ledger()
        ledger.append("jev_eval", model="jev-test", input_tokens=1000, output_tokens=50, is_fallback=False, cost=0.000042)
        ledger.append("jev_eval", model="jev-test", input_tokens=500, output_tokens=10, is_fallback=True, cost=0.0)
        report = ledger.cost_report()
        self.assertIn("jev", report)
        self.assertEqual(report["jev"]["calls"], 1)
        self.assertEqual(report["jev"]["input_tokens"], 1000)
        self.assertEqual(report["jev"]["output_tokens"], 50)

    def test_legacy_per_mtok_cost_in_old_entries_is_normalized(self):
        # Entries written when the client priced input at $42/Mtok carry a
        # cost 1000x too high. The report recomputes Jev cost from the
        # recorded input tokens at the verified $0.042/Mtok rate rather than
        # trusting the stored figure, so old ledgers read correctly.
        ledger = self._ledger()
        ledger.append("jev_eval", model="jev-1.13.0", input_tokens=1000,
                      output_tokens=0, is_fallback=False, cost=0.042)
        report = ledger.cost_report()
        self.assertAlmostEqual(report["total_cost"], 0.000042, places=9)
        self.assertAlmostEqual(report["jev"]["cost"], 0.000042, places=9)
        self.assertEqual(report["jev"]["calls"], 1)
        self.assertEqual(report["jev"]["input_tokens"], 1000)
        self.assertAlmostEqual(report["jev"]["price_per_million_input"], 0.042)
        self.assertAlmostEqual(report["jev"]["monthly_credit"], 5.0)
        self.assertAlmostEqual(report["jev"]["remaining_credit"],
                               5.0 - 0.000042, places=6)

    def test_jev_fallback_and_tokenless_entries_cost_nothing(self):
        ledger = self._ledger()
        ledger.append("jev_eval", model="jev-1.13.0", input_tokens=900,
                      is_fallback=True, cost=0.5)
        ledger.append("jev_eval", model="jev-1.13.0", input_tokens=0,
                      is_fallback=False, cost=0.5)
        report = ledger.cost_report()
        self.assertEqual(report["total_cost"], 0.0)
        self.assertEqual(report["jev"]["calls"], 0)
        self.assertEqual(report["jev"]["cost"], 0.0)
        self.assertEqual(report["jev"]["used_percent"], 0.0)

    def test_jev_cost_normalizes_legacy_rate_entries(self):
        # Legacy entries were stored at $42/Mtok (1000x the real $0.042/Mtok);
        # the report recomputes from input tokens, never trusts stored cost.
        ledger = self._ledger()
        ledger.append("jev_eval", model="jev-test", input_tokens=1_000_000,
                      output_tokens=10, is_fallback=False, cost=42.0)
        jev = ledger.cost_report()["jev"]
        self.assertEqual(jev["calls"], 1)
        self.assertAlmostEqual(jev["cost"], 0.042, places=6)
        self.assertAlmostEqual(jev["remaining_credit"], 5.0 - 0.042, places=6)
        self.assertAlmostEqual(ledger.cost_report()["total_cost"], 0.042, places=6)

    def test_jev_credit_counts_only_current_utc_month(self):
        from datetime import datetime, timezone
        ledger = self._ledger()
        ledger.append("jev_eval", model="jev-test", input_tokens=1000,
                      is_fallback=False, ts="2026-09-30T23:59:59+00:00")
        ledger.append("jev_eval", model="jev-test", input_tokens=2000,
                      is_fallback=False, ts="2026-10-01T00:00:00+00:00")
        ledger.append("jev_eval", model="jev-test", input_tokens=4000,
                      is_fallback=False, ts="2026-10-15T12:00:00+00:00")
        ledger.append("jev_eval", model="jev-test", input_tokens=8000,
                      is_fallback=False, ts="not-a-timestamp")
        jev = ledger.cost_report(
            now=datetime(2026, 10, 20, tzinfo=timezone.utc))["jev"]
        self.assertEqual(jev["month"], "2026-10")
        self.assertEqual(jev["calls"], 2)
        self.assertEqual(jev["input_tokens"], 6000)
        self.assertAlmostEqual(jev["cost"], 6000 * 0.042 / 1_000_000, places=9)
        sept = ledger.cost_report(
            now=datetime(2026, 9, 30, tzinfo=timezone.utc))["jev"]
        self.assertEqual(sept["input_tokens"], 1000)

    def test_jev_block_reads_rotated_segments_and_other_writers(self):
        from datetime import datetime, timezone
        from unittest import mock
        path = os.path.join(self.tmp.name, "ledger.jsonl")
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        writer = AutonomyLedger(path)
        # Force a rotation after every append so the early jev events end up
        # in rotated segments, not in the active file.
        with mock.patch("harness.ledger.LEDGER_MAX_BYTES", 1):
            for _ in range(2):
                writer.append("jev_eval", model="jev-test", input_tokens=1000,
                              is_fallback=False, ts=stamp)
        self.assertTrue(writer._rotated_paths())
        reader = AutonomyLedger(path)
        # A second process appends after the reader loaded; the reader's
        # in-memory _tail is now stale.
        writer.append("jev_eval", model="jev-test", input_tokens=500,
                      is_fallback=False, ts=stamp)
        self.assertEqual(len(reader._tail) + 1, len(writer._tail))
        jev = reader.cost_report()["jev"]
        self.assertEqual(jev["calls"], 3)
        self.assertEqual(jev["input_tokens"], 2500)

    def test_jev_block_ignores_torn_lines_and_keeps_unflushed_entries(self):
        ledger = self._ledger()
        ledger.append("jev_eval", model="jev-test", input_tokens=100,
                      is_fallback=False)
        with open(ledger.path, "a", encoding="utf-8") as f:
            f.write("{torn line\n[1, 2]\n")
        # An in-memory-only entry (no seq) must still be counted.
        ledger._tail.append({"event": "jev_eval", "model": "jev-test",
                             "input_tokens": 50, "is_fallback": False,
                             "ts": ledger._tail[-1]["ts"]})
        self.assertEqual(ledger.cost_report()["jev"]["input_tokens"], 150)

    def test_jev_block_tolerates_naive_clocks_junk_tokens_and_unlistable_dir(self):
        from datetime import datetime
        from unittest import mock
        ledger = self._ledger()
        naive_now = datetime.now()  # tz-naive "now" is read as UTC
        stamp = naive_now.isoformat(timespec="seconds")  # naive ts likewise
        ledger.append("jev_eval", model="jev-test", input_tokens=100,
                      output_tokens="junk", is_fallback=False, ts=stamp)
        ledger.append("jev_eval", model="jev-test", input_tokens="junk",
                      is_fallback=False, ts=stamp)
        ledger.append("jev_eval", model="jev-test", input_tokens=900,
                      is_fallback=True, ts=stamp)
        jev = ledger.cost_report(now=naive_now)["jev"]
        self.assertEqual((jev["calls"], jev["input_tokens"],
                          jev["output_tokens"]), (1, 100, 0))
        # An unlistable ledger directory degrades to the in-memory entries.
        with mock.patch.object(type(ledger), "_ledger_paths",
                               side_effect=OSError("no dir")):
            self.assertEqual(ledger._all_entries(), ledger.entries())

    def test_completion_state_text_variants(self):
        from harness.jev_policy import JevPolicy
        self.assertEqual(JevPolicy._completion_state_text("plain string"), "plain string")
        self.assertEqual(JevPolicy._completion_state_text(12345), "12345")


class SpendAdmissionTests(unittest.TestCase):
    """#805 spend-allowance ruling: worst-case admission EXCLUDES a candidate
    before its first call instead of refusing the task; the task is
    SPEND-BLOCKED only once every affordable candidate is excluded, and a
    narrower completion keeps the exclusion on the record."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _ledger(self):
        return AutonomyLedger(os.path.join(self.tmp.name, "ledger.jsonl"))

    @staticmethod
    def _jev_reply():
        return {"model": "jev-test",
                "answers": {"instruction_matches": {"type": "noul", "noul": 0.95}},
                "usage": {"input_tokens": 100, "output_tokens": 2}}

    def _engine(self, models, router, ledger, posts):
        from harness.apply import ApplyEngine

        settings = load_settings({"jev_api_key": "jev-key"})
        transport = FakeTransport(models=models, posts=posts)
        governor = SpendGovernor(transport, "sk-test", max_cost=1.0)
        policy = policy_for(
            settings,
            transport=FakeTransport(posts=[self._jev_reply() for _ in range(6)]),
            governor=governor, ledger=ledger)
        engine = ApplyEngine(transport, "k", governor, ledger, router,
                             jev_policy=policy, default_require_consent=False,
                             default_renew_consent=False)
        return engine, transport, governor

    @staticmethod
    def _target(tmp, name="target.py"):
        path = os.path.join(tmp.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write("x = 1\n")
        return path

    def _excluded(self, ledger):
        return [e for e in ledger.entries()
                if e["event"] == "model_result"
                and e.get("status") == "excluded"]

    def test_an_over_budget_candidate_is_excluded_and_a_cheaper_one_completes(self):
        from harness.router import Router
        from tests._fake import comp

        ledger = self._ledger()
        models = [m("expensive/model", prompt="0.001", completion="0.001"),
                  m("cheap/model", prompt="0", completion="0"),
                  m("jev-test", prompt="0", completion="0")]
        # apply_pool keeps the primary first, then the cheaper candidate.
        router = Router(["cheap/model"], "jev-test", "expensive/model")
        engine, transport, governor = self._engine(
            models, router, ledger, [comp("def x(): pass\n")])

        cap = 0.001
        result = engine.apply_edit(file_path=self._target(self.tmp),
                                   instruction="edit x",
                                   verify_cmd="python -c pass",
                                   task_max_cost=cap, require_consent=False,
                                   renew_consent=False)

        self.assertIn(result["status"], ("ok", "preview"))
        excluded = self._excluded(ledger)
        self.assertEqual([e["model"] for e in excluded], ["expensive/model"])
        self.assertEqual(excluded[0]["reason"], "spend_preflight")
        self.assertEqual(excluded[0]["cost"], 0.0)
        self.assertGreater(excluded[0]["estimate"], 0.0)
        self.assertGreater(excluded[0]["worst_case"], cap)
        # The narrower candidate ran, and the exclusion did not spend anything.
        served = [e for e in ledger.entries()
                  if e["event"] == "model_result"
                  and e.get("model") == "cheap/model"]
        self.assertTrue(served)
        self.assertNotIn("excluded", [e.get("status") for e in served])
        self.assertLess(governor.spent, cap)
        # No chat call was ever made for the excluded candidate.
        called = [call[2].get("model") for call in transport.calls
                  if call[0] == "POST"]
        self.assertNotIn("expensive/model", called)

    def test_the_excluded_candidate_is_not_retried_in_a_later_round(self):
        from harness.router import Router
        from tests._fake import comp

        ledger = self._ledger()
        models = [m("expensive/model", prompt="0.001", completion="0.001"),
                  m("cheap/model", prompt="0", completion="0"),
                  m("jev-test", prompt="0", completion="0")]
        router = Router(["cheap/model"], "jev-test", "expensive/model")
        engine, transport, governor = self._engine(
            models, router, ledger, [comp("x = 2\n"), comp("x = 3\n")])

        cap = 0.001
        engine.apply_edit(file_path=self._target(self.tmp, "rounds.py"),
                          instruction="edit x",
                          verify_cmd="python -c exit(1)", max_rounds=2,
                          task_max_cost=cap, require_consent=False,
                          renew_consent=False)

        # Excluded once, never re-admitted: the set carries across rounds.
        self.assertEqual([e["model"] for e in self._excluded(ledger)],
                         ["expensive/model"])
        called = [call[2].get("model") for call in transport.calls
                  if call[0] == "POST"]
        self.assertNotIn("expensive/model", called)

    def test_an_unaffordable_escalation_rung_is_excluded_not_refused(self):
        from harness.jev import jev_cost
        from harness.jev_policy import JEV_MAX_INPUT_TOKENS
        from harness.router import Router
        from tests._fake import comp

        ledger = self._ledger()
        models = [m("apply/model", prompt="0", completion="0"),
                  m("esc/model", prompt="0", completion="0"),
                  m("jev-test", prompt="0", completion="0")]
        router = Router(["apply/model"], "jev-test", "apply/model",
                        allow_escalation=True, escalation_model="esc/model")
        engine, _transport, _governor = self._engine(
            models, router, ledger, [comp("def x(): pass\n")])

        cap = jev_cost(JEV_MAX_INPUT_TOKENS)
        result = engine.apply_edit(file_path=self._target(self.tmp, "esc.py"),
                                   instruction="edit x",
                                   verify_cmd="python -c exit(1)", max_rounds=1,
                                   task_max_cost=cap, require_consent=False,
                                   renew_consent=False)

        # The run narrows to the rung it already reached rather than refusing
        # the task, and the exclusion is on the record.
        self.assertNotEqual(result["status"], "ok")
        excluded = self._excluded(ledger)
        self.assertEqual([e["model"] for e in excluded], ["esc/model"])
        self.assertEqual(excluded[0]["reason"], "spend_preflight")
        self.assertEqual(excluded[0]["cost"], 0.0)


if __name__ == "__main__":
    unittest.main()
