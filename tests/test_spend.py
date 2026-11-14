"""Spend-governor policy: per-token math, ceilings, key trust, payload guards."""
import unittest
from types import SimpleNamespace
from unittest import mock

from harness.errors import HarnessError, ToolCancelled
from harness.provider_errors import ProviderSpendLimitError
from harness.panel import panel_judge
from harness.tokens import estimate_prompt_tokens
from tests._fake import FakeTransport, m, comp, _gov, P1, P2, JUDGE


class CostMathTests(unittest.TestCase):
    def test_key_verification_preserves_cancellation(self):
        class CancelledTransport:
            def get(self, *args, **kwargs):
                raise ToolCancelled()

        gov = _gov(CancelledTransport())
        with self.assertRaises(ToolCancelled):
            gov.verify_key()

    def test_model_refresh_preserves_cancellation_even_with_cache(self):
        class CancelledTransport:
            def get(self, *args, **kwargs):
                raise ToolCancelled()

        gov = _gov(CancelledTransport())
        gov._models = [{"id": "cached/model"}]
        with self.assertRaises(ToolCancelled):
            gov.fetch_models(refresh=True)

    def test_snapshot_reports_public_spend_state(self):
        gov = _gov(FakeTransport(models=[m(P1)]), max_cost=0.05)
        token = gov.reserve(0.00234567, "task_1")
        gov.reconcile(token, 0.00123456)
        self.assertEqual(gov.snapshot(), {
            "spent": 0.001235,
            "outstanding": 0.0,
            "ceiling": 0.05,
        })

    def test_supports_reasoning_edge_cases(self):
        gov = _gov(FakeTransport())
        self.assertTrue(gov.supports_reasoning(""))
        self.assertTrue(gov.supports_reasoning(None))
        self.assertFalse(gov.supports_reasoning("openrouter/free"))
        self.assertFalse(gov.supports_reasoning("openrouter/auto"))
        gov._models = [
            {"id": "m/with-reasoning", "supported_parameters": ["reasoning", "tools"]},
            {"id": "m/no-reasoning", "supported_parameters": ["tools"]},
            {"id": "m/none-params", "supported_parameters": None},
        ]
        self.assertTrue(gov.supports_reasoning("m/with-reasoning"))
        self.assertFalse(gov.supports_reasoning("m/no-reasoning"))
        self.assertTrue(gov.supports_reasoning("m/none-params"))
        self.assertTrue(gov.supports_reasoning("m/unknown"))

    def test_pricing_is_per_token_not_per_million(self):
        """Regression: OpenRouter pricing fields are per-token dollars. An
        earlier SCMessenger version divided by 1e6 a second time and
        undercounted worst-case cost ~1,000,000x. Costs here must land in the
        ~1e-5..1e-4 range, not ~1e-10."""
        fake = FakeTransport(models=[m(P1), m(P2), m(JUDGE)])
        gov = _gov(fake)
        prompt = " ".join(["word"] * 200)  # ~350 estimated tokens
        calls = [(P1, P1, 300, 0), (P2, P2, 300, 0), ("judge", JUDGE, 350, 700)]
        total, breakdown = gov.preflight(prompt, calls)
        pt = estimate_prompt_tokens(prompt)
        expected = (pt * 1e-8 + 300 * 2e-8) * 2 + (pt + 700) * 1e-8 + 350 * 2e-8
        self.assertAlmostEqual(total, expected, places=12)
        for _, _model, cost in breakdown:
            self.assertGreater(cost, 1e-9, "cost is mis-scaled by orders of magnitude")
        self.assertEqual(gov.spent, 0.0, "preflight must not spend anything")

    def test_preflight_refuses_when_over_ceiling(self):
        fake = FakeTransport(models=[m(P1, "0.0001", "0.0002")])
        gov = _gov(fake, max_cost=0.01)
        with self.assertRaises(HarnessError):
            gov.preflight(" ".join(["word"] * 5000), [(P1, P1, 300, 0)])

    def test_unknown_model_refused(self):
        fake = FakeTransport(models=[m(P1)])
        gov = _gov(fake)
        with self.assertRaises(HarnessError):
            gov.preflight("hi", [("x", "nope/model", 10, 0)])

    def test_key_must_have_finite_limit(self):
        fake = FakeTransport(key={"label": "sk-test", "limit": None})
        gov = _gov(fake)
        with self.assertRaises(HarnessError):
            gov.verify_key()

    def test_session_preflight_stops_on_exhausted_provider_allowance(self):
        from harness import session

        fake = FakeTransport(key={"label": "sk-test", "limit": 1.0,
                                  "limit_remaining": 0.0})
        settings = SimpleNamespace(max_cost=0.05, expect_key_label=None)
        with mock.patch.object(session, "HttpTransport", return_value=fake), \
             mock.patch.object(session, "resolve_api_key", return_value="sk-test"), \
             self.assertRaises(ProviderSpendLimitError) as ctx:
            session.governor_for(settings)
        self.assertEqual(ctx.exception.kind, "provider_spend_limit")
        self.assertIn("operation was stopped", str(ctx.exception))
        self.assertEqual(fake.chat_posts(), [])

    def test_key_with_unknown_remaining_is_not_called_exhausted(self):
        fake = FakeTransport(key={"label": "sk-test", "limit": 1.0,
                                  "limit_remaining": None})
        info = _gov(fake).verify_key()
        self.assertIsNone(info["remaining"])

    def test_verify_key_propagates_provider_spend_limit(self):
        fake = FakeTransport()
        err = ProviderSpendLimitError("key check 402")
        with mock.patch.object(fake, "get", side_effect=err):
            gov = _gov(fake)
            with self.assertRaises(ProviderSpendLimitError) as ctx:
                gov.verify_key()
            self.assertEqual(ctx.exception, err)

    def test_fetch_models_propagates_provider_spend_limit(self):
        fake = FakeTransport()
        err = ProviderSpendLimitError("catalog check 402")
        with mock.patch.object(fake, "get", side_effect=err):
            gov = _gov(fake)
            with self.assertRaises(ProviderSpendLimitError) as ctx:
                gov.fetch_models(refresh=True)
            self.assertEqual(ctx.exception, err)

    def test_expect_key_label_mismatch(self):
        fake = FakeTransport(key={"label": "sk-or-v1-aaaa", "limit": 1.0})
        gov = _gov(fake, expect_key_label="bbbb")
        with self.assertRaises(HarnessError):
            gov.verify_key()

    def test_expect_key_label_match(self):
        """Audit #9b: label expectation is an EXACT match now (substring let a
        similarly-named key through), and the error never echoes labels."""
        fake = FakeTransport(key={"label": "sk-or-v1-aaaa", "limit": 1.0,
                                  "limit_remaining": 0.5})
        gov = _gov(fake, expect_key_label="sk-or-v1-aaaa")
        info = gov.verify_key()
        self.assertEqual(info["label"], "sk-or-v1-aaaa")
        wrong = _gov(FakeTransport(key={"label": "sk-or-v1-bbbb", "limit": 1.0,
                                        "limit_remaining": 0.5}),
                     expect_key_label="sk-or-v1-aaaa")
        with self.assertRaises(HarnessError) as ctx:
            wrong.verify_key()
        self.assertNotIn("bbbb", str(ctx.exception))
        self.assertNotIn("aaaa", str(ctx.exception))


class GuardTests(unittest.TestCase):
    def test_no_tools_key_ever(self):
        fake = FakeTransport(models=[m(P1), m(P2), m(JUDGE)],
                             posts=[comp("a"), comp("b"), comp("verdict")])
        gov = _gov(fake)
        panel_judge(transport=fake, api_key="k", governor=gov, prompt="Q?",
                    panel=[P1, P2], judge=JUDGE)
        for payload in fake.payloads():
            self.assertNotIn("tools", payload)

    def test_byok_denied_before_any_post(self):
        fake = FakeTransport(models=[m(P1), m("anthropic/claude-3.5-sonnet")])
        gov = _gov(fake)
        with self.assertRaises(HarnessError) as ctx:
            panel_judge(transport=fake, api_key="k", governor=gov, prompt="Q?",
                        panel=[P1, "anthropic/claude-3.5-sonnet"], judge=JUDGE)
        self.assertIn("BYOK", str(ctx.exception))
        self.assertEqual(fake.chat_posts(), [], "no chat call may go out")

    def test_mid_batch_fail_closed(self):
        # The vote lane always sends a reasoning disable, so each vote reserves
        # two slots (a disable may draw the mandatory-reasoning retry). The
        # preflight for that shape is ~0.0015, and the two votes bill 0.003:
        # both really post, then the batch fails closed instead of calling the
        # judge with no budget left.
        fake = FakeTransport(models=[m(P1), m(P2), m(JUDGE)],
                             posts=[comp("a", cost=0.0015), comp("b", cost=0.0015)])
        gov = _gov(fake, max_cost=0.002)
        with self.assertRaises(HarnessError):
            panel_judge(transport=fake, api_key="k", governor=gov, prompt="Q?",
                        panel=[P1, P2], judge=JUDGE)
        # judge must never have been called
        self.assertEqual(len(fake.chat_posts()), 2)


class ReservationTests(unittest.TestCase):
    """MR-6 verdict pins: reservations are real liabilities; concurrent
    dispatch can never push spent + outstanding over the ceiling."""

    def setUp(self):
        self.fake = FakeTransport(models=[m("cheap/x")])
        self.gov = _gov(self.fake, max_cost=0.01)

    def test_reserve_and_reconcile(self):
        token = self.gov.reserve(0.004, "task_1")
        self.assertEqual(self.gov.outstanding, 0.004)
        self.gov.reconcile(token, 0.002)
        self.assertEqual(self.gov.outstanding, 0.0)
        self.assertEqual(self.gov.spent, 0.002)

    def test_reservation_refused_over_ceiling(self):
        with self.assertRaises(HarnessError):
            self.gov.reserve(0.02, "task_1")

    def test_reconcile_unknown_token_raises(self):
        with self.assertRaises(HarnessError):
            self.gov.reconcile(("ghost", 0.004), 0.0)

    def test_reconcile_invalid_actual_raises(self):
        token = self.gov.reserve(0.004, "task_1")
        with self.assertRaises(HarnessError):
            self.gov.reconcile(token, "not-a-number")

    def test_reconcile_over_ceiling_actual_raises_and_releases(self):
        token = self.gov.reserve(0.004, "task_1")
        with self.assertRaises(HarnessError):
            self.gov.reconcile(token, 0.02)
        # The liability is released even when the actual is refused.
        self.assertEqual(self.gov.outstanding, 0.0)
        self.assertEqual(self.gov.spent, 0.0)

    def test_reconcile_locked_recheck_raises_under_race(self):
        """The lock-guarded re-check is the last line of defense: another
        thread can land an actual between the unlocked check and the
        locked commit -- that interleaving must still fail closed."""
        gov = _gov(self.fake, max_cost=0.01)
        token = gov.reserve(0.004, "task_1")

        class RacyLock:
            enters = 0

            def __enter__(self):
                RacyLock.enters += 1
                if RacyLock.enters == 2:  # second entry: the commit block
                    gov.spent = 0.009     # a concurrent winner landed
            def __exit__(self, *exc):
                return False

        gov._spend_lock = RacyLock()
        with self.assertRaises(HarnessError):
            gov.reconcile(token, 0.005)
        # The racing actual was never committed.
        self.assertEqual(gov.spent, 0.009)

    def test_node_reserver_uses_route_tier_ceiling(self):
        from harness.dag import DAGNode
        from harness.spend import NodeReserver

        gov = _gov(self.fake, max_cost=0.01)
        routes = {"task_1": {"task_max_cost": 0.004}, "task_2": None}
        reserver = NodeReserver(gov, routes, 0.006,
                                route_kwargs_fn=lambda d: dict(d or {}))
        n1 = DAGNode(node_id="task_1", instruction="x")
        n2 = DAGNode(node_id="task_2", instruction="y")
        n3 = DAGNode(node_id="task_9", instruction="z")  # absent from routes
        t1 = reserver.reserve(n1)
        self.assertEqual(gov.outstanding, 0.004)
        t2 = reserver.reserve(n2)
        self.assertEqual(gov.outstanding, 0.010)
        with self.assertRaises(HarnessError):
            reserver.reserve(n3)  # default worst case would breach
        reserver.reconcile(t1, 0.001)
        self.assertEqual(gov.spent, 0.001)
        self.assertEqual(gov.outstanding, 0.006)
        reserver.reconcile(t2, 0.002)
        self.assertEqual(gov.spent, 0.003)

    def test_node_reserver_free_route_reserves_zero_under_small_ceiling(self):
        """The GUI-lane defect: a FREE node declares a $0.00 route ceiling,
        but ``node_apply_kwargs`` deliberately drops a $0 ceiling from the
        request (a zero task budget would refuse the escalation ladder), so
        the reserver used to read "no ceiling" and reserve the engine's
        nominal $0.10 default. Against the default $0.05 run ceiling that
        refused EVERY node before any work, so the lane completed nothing.
        """
        from harness.dag import DAGNode, plan_task
        from harness.spend import NodeReserver

        gov = _gov(self.fake, max_cost=0.05)
        plan = plan_task(goal="Add a module docstring",
                         candidate_files=["util.py"], use_free=True)
        routes = {n["node_id"]: n for n in plan["nodes"]}
        node_id = list(routes)[0]
        reserver = NodeReserver(gov, routes, 0.10, run_ceiling=0.05)
        self.assertEqual(float(routes[node_id]["route"]["cost_ceiling"]), 0.0)
        # The nominal default is an unrelated number: capped by the run's own
        # ceiling instead of trusted as a cost.
        self.assertEqual(reserver.default_amount, 0.05)
        token = reserver.reserve(DAGNode(node_id=node_id, instruction="x"))
        self.assertEqual(token[1], 0.0)
        self.assertEqual(gov.outstanding, 0.0)
        self.assertEqual(gov.remaining(), 0.05)

    def test_node_reserver_refuses_a_worst_case_that_cannot_fit(self):
        """Fail-closed is preserved: an amount larger than what the run can
        still afford refuses rather than being trimmed to fit (a trimmed
        reservation would let a call that may bill its full ceiling dispatch
        and only surface at reconcile time, after the money was spent)."""
        from harness.dag import DAGNode
        from harness.spend import NodeReserver

        gov = _gov(self.fake, max_cost=0.05)
        routes = {"task_1": {"route": {"ladder": ["m/p"],
                                       "cost_ceiling": 0.10}}}
        reserver = NodeReserver(gov, routes, 0.10, run_ceiling=0.05)
        with self.assertRaises(HarnessError) as ctx:
            reserver.reserve(DAGNode(node_id="task_1", instruction="x"))
        self.assertIn("does not fit", str(ctx.exception))
        self.assertEqual(gov.outstanding, 0.0)

    def test_node_reserver_defaults_its_ceiling_to_the_governor(self):
        """No explicit run ceiling: the governor's own max_cost IS the run
        ceiling, so the fallback bound still cannot exceed it."""
        from harness.dag import DAGNode
        from harness.spend import NodeReserver

        gov = _gov(self.fake, max_cost=0.02)
        reserver = NodeReserver(gov, {}, 0.10)
        self.assertEqual(reserver.run_ceiling, 0.02)
        self.assertEqual(reserver.default_amount, 0.02)
        reserver.reserve(DAGNode(node_id="unknown", instruction="x"))
        self.assertEqual(gov.outstanding, 0.02)

    def test_node_reserver_paid_ceiling_is_still_used_verbatim(self):
        """A real (nonzero) tier ceiling is the node's worst case: reserving
        it is what keeps W concurrent workers from overcommitting."""
        from harness.dag import DAGNode
        from harness.spend import NodeReserver

        gov = _gov(self.fake, max_cost=0.05)
        routes = {"task_1": {"route": {"ladder": ["m/p"],
                                       "cost_ceiling": 0.02}}}
        reserver = NodeReserver(gov, routes, 0.10, run_ceiling=0.05)
        token = reserver.reserve(DAGNode(node_id="task_1", instruction="x"))
        self.assertEqual(token[1], 0.02)
        self.assertEqual(gov.outstanding, 0.02)

    def test_remaining_counts_reservations_as_committed(self):
        """``remaining`` is the one accessor for "what this run can still
        commit": outstanding reservations are real liability, so they count
        exactly like recorded spend."""
        gov = _gov(self.fake, max_cost=0.01)
        self.assertEqual(gov.remaining(), 0.01)
        gov.reserve(0.004, "task_1")
        self.assertAlmostEqual(gov.remaining(), 0.006, places=12)
        gov.record_actual(0.002, "label")
        self.assertAlmostEqual(gov.remaining(), 0.004, places=12)

    def test_outstanding_blocks_preflight(self):
        self.gov.reserve(0.0095, "task_1")
        # Remaining headroom is 0.0005 minus the outstanding liability: a
        # preflight worst case above that must refuse even though raw spent
        # is still ~0.
        with self.assertRaises(HarnessError):
            self.gov.preflight("p", [("ask", "cheap/x", 40000, 0)])

    def test_concurrent_dispatch_cannot_overcommit_ceiling(self):
        """The MR-6 proof obligation: W barrier-synced workers reserving
        per-call worst cases never overspend; without reservations the
        same interleaving would bill 2x the ceiling."""
        import threading

        gov = _gov(self.fake, max_cost=0.01)
        barrier = threading.Barrier(2)
        overspends = []

        def worker():
            barrier.wait()
            try:
                token = gov.reserve(0.006, "w")
                gov.reconcile(token, 0.006)
            except HarnessError as exc:
                overspends.append(str(exc))

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # spent + outstanding <= ceiling at every point: the second worker's
        # reserve is refused (0.006 outstanding + 0.006 > 0.01), so the
        # billed total can never reach 0.012.
        self.assertEqual(len(overspends), 1)
        self.assertLessEqual(gov.spent + gov.outstanding, 0.01 + 1e-9)

    def test_unreserved_inflight_overspend_documented(self):
        """Documents WHY per-call preflight alone is insufficient (MR-6):
        two check-only preflights against the full remaining ceiling both
        pass before either records; only the SECOND actual trips the guard
        -- by then both calls are already dispatched and billed."""
        gov = _gov(self.fake, max_cost=0.01)
        gov.preflight("p", [("a", "cheap/x", 100, 0)])
        gov.preflight("p", [("b", "cheap/x", 100, 0)])   # also passes
        gov.record_actual(0.009, "a")                    # first actual fits
        with self.assertRaises(HarnessError):
            gov.record_actual(0.009, "b")                # too late: both ran
        self.assertLessEqual(gov.spent, 0.01)


class PerRequestAttributionTests(unittest.TestCase):
    """Issue #345: each request's own actual/outstanding/unknown liability
    is enforced independently of unrelated concurrent session spending.

    Synthetic dollars only; no network, keys, or real spend. Each test
    builds its own governor, so there is no shared global state and no
    ordering dependence between tests.
    """

    def _gov(self, max_cost=1.00):
        return _gov(FakeTransport(models=[m("cheap/x")]), max_cost=max_cost)

    def test_case3_b_spend_keeps_a_allowance_while_shared_cap_refuses(self):
        """Case 3 verbatim: $1.00 session, A opens task_scope($0.10) at
        $0.00, independent worker B records $0.20, A spends nothing. A's
        own allowance must stay $0.10 while the shared session capacity
        drops to $0.80 -- and the shared cap must still refuse."""
        gov = self._gov()
        with gov.task_scope(0.50, label="B") as scope_b:
            with gov.task_scope(0.10, label="A"):
                self.assertAlmostEqual(gov.remaining(), 0.10, places=6)
                gov.record_actual(0.20, "b-model", scope=scope_b)
                # A spent nothing: its individual allowance is untouched.
                self.assertAlmostEqual(
                    gov.remaining(), 0.10, places=6,
                    msg="B's spend must not exhaust A's allowance")
                # ...while the shared session capacity absorbed B's spend.
                self.assertAlmostEqual(gov.spent, 0.20, places=6)
                self.assertAlmostEqual(scope_b.spent, 0.20, places=6)
        # Both scopes closed: only the shared session ceiling remains.
        self.assertAlmostEqual(gov.remaining(), 0.80, places=6)
        with self.assertRaises(HarnessError):
            gov.reserve(0.81, "over-shared-cap")
        token = gov.reserve(0.80, "fits-shared-cap")
        gov.reconcile(token, 0.80)
        self.assertAlmostEqual(gov.spent, 1.00, places=6)

    def test_concurrent_scope_spend_is_not_charged_to_sibling(self):
        """Overlapping scopes isolate: B's reserve/reconcile against its own
        scope token never lands on A's ledger, even while A is open."""
        gov = self._gov()
        with gov.task_scope(0.30, label="B") as scope_b:
            with gov.task_scope(0.10, label="A") as scope_a:
                token = gov.reserve(0.06, "b-work", scope=scope_b)
                self.assertAlmostEqual(scope_b.outstanding, 0.06, places=6)
                self.assertAlmostEqual(scope_a.outstanding, 0.0, places=6)
                gov.reconcile(token, 0.06, scope=scope_b)
                self.assertAlmostEqual(scope_b.spent, 0.06, places=6)
                self.assertAlmostEqual(scope_a.spent, 0.0, places=6)
                self.assertAlmostEqual(gov.spent, 0.06, places=6)
                # A's own allowance is intact; shared capacity dropped.
                self.assertAlmostEqual(gov.remaining(), 0.10, places=6)

    def test_nested_scopes_enforce_min_over_stack(self):
        """Default attribution settles on the innermost scope and every
        scope outside it, so each nested bound holds and remaining is the
        minimum over the stack."""
        gov = self._gov()
        with gov.task_scope(0.05, label="outer") as outer:
            with gov.task_scope(0.02, label="inner"):
                self.assertAlmostEqual(gov.remaining(), 0.02, places=6)
                token = gov.reserve(0.015, "work")
                gov.reconcile(token, 0.015)
                self.assertAlmostEqual(gov.remaining(), 0.005, places=6)
                # The inner bound refuses even though the outer has room.
                with self.assertRaises(HarnessError):
                    gov.reserve(0.01, "over-inner")
            # The outer ledger saw the inner spend: 0.015 + 0.04 > 0.05.
            with self.assertRaises(HarnessError):
                gov.reserve(0.04, "over-outer")
            token = gov.reserve(0.035, "fits-outer")
            gov.reconcile(token, 0.035)
            self.assertAlmostEqual(outer.spent, 0.05, places=6)
            self.assertAlmostEqual(gov.spent, 0.05, places=6)

    def test_settle_on_exit_keeps_one_governor_truth(self):
        """Spend settled inside a scope lands on the ONE governor; exiting
        releases the narrowing, keeps the scope's own counters, and a late
        token still settles against its scope."""
        gov = self._gov()
        with gov.task_scope(0.10, label="A") as scope_a:
            token = gov.reserve(0.04, "work")
            self.assertAlmostEqual(gov.remaining(), 0.06, places=6)
        # Exit with the reservation in flight: the narrowing is gone...
        self.assertAlmostEqual(gov.remaining(), 0.96, places=6)
        # ...but the late settlement still lands on both truths.
        gov.reconcile(token, 0.04)
        self.assertAlmostEqual(gov.spent, 0.04, places=6)
        self.assertAlmostEqual(gov.outstanding, 0.0, places=6)
        self.assertAlmostEqual(scope_a.spent, 0.04, places=6)
        self.assertAlmostEqual(scope_a.outstanding, 0.0, places=6)
        self.assertAlmostEqual(gov.remaining(), 0.96, places=6)

    def test_unknown_liability_attributes_to_own_scope(self):
        """retain_unknown charges the bound scope's own unknown ledger
        without touching a sibling scope; an inner scope's spend still
        settles on the scope enclosing it."""
        gov = self._gov()
        with gov.task_scope(0.30, label="B") as scope_b:
            with gov.task_scope(0.10, label="A") as scope_a:
                gov.retain_unknown(0.05, "b-model", scope=scope_b)
                self.assertAlmostEqual(scope_b.unknown, 0.05, places=6)
                self.assertAlmostEqual(scope_b.outstanding, 0.05, places=6)
                self.assertAlmostEqual(scope_a.unknown, 0.0, places=6)
                self.assertAlmostEqual(scope_a.outstanding, 0.0, places=6)
                token = gov.reserve(0.02, "a-work")
                gov.reconcile(token, 0.02)
                self.assertAlmostEqual(scope_a.spent, 0.02, places=6)
                self.assertAlmostEqual(scope_b.spent, 0.02, places=6)
                self.assertAlmostEqual(gov.spent, 0.02, places=6)

    def test_explicit_scope_must_be_a_task_scope(self):
        """A non-scope attribution token fails closed instead of
        attributing nowhere."""
        gov = self._gov()
        with self.assertRaises(HarnessError):
            gov.reserve(0.01, "work", scope="not-a-scope")
        with self.assertRaises(HarnessError):
            gov.record_actual(0.01, "work", scope="not-a-scope")
        token = gov.reserve(0.01, "work")
        with self.assertRaises(HarnessError):
            gov.reconcile(token, 0.0, scope="not-a-scope")


if __name__ == "__main__":
    unittest.main()
