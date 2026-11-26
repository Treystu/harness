"""Issue #472: a routed call records its candidate pool and its attempt order.

The Champion brief for capability-pool ordering could not execute because the
router recorded which model ran but never which models it could have run, in
what order, or which of them it actually tried. Both are now written through
the one trace writer (`DecisionTrace` over the hash-chained `AutonomyLedger`):
one `routing.candidates` row per routed call carrying the pool as it stood
before ordering, the caller's configured pool, and the ranked order the engine
will use; then one `routing.attempt` row per attempt it actually made, in the
order it happened. A reader re-derives the sequence from those rows.
"""
from harness.decision_trace import DecisionTrace, read_trace_events
from harness.apply_policy import ATTEMPT_EVENT, CANDIDATES_EVENT
from unittest import mock

from tests._applyfixture import (APPLY, CHANGED, CODER_A, ApplyFixture,
                                 scripted_run)
from tests._fake import comp


class RoutingTraceTests(ApplyFixture):
    DEFAULT_OFFER_TASK_IDS = ("t1",)

    def _env(self, trace=True, posts=None, run=None):
        fake, gov, ledger, engine = self.make_env(
            posts=posts or [comp(CHANGED)], run=run or scripted_run([(0, "")]),
            router_kw={"apply_pool": [CODER_A]})
        if trace:
            engine.trace = DecisionTrace(ledger)
        return fake, gov, ledger, engine

    def _apply(self, engine, path, **kw):
        return engine.apply_edit(task_id="t1", file_path=path,
                                 instruction="add +0", require_consent=False,
                                 verify_cmd="python -m py_compile math.py", **kw)

    def test_the_pool_is_recorded_as_it_stood_before_the_call(self):
        path = self.make_file()
        _fake, _gov, ledger, engine = self._env()
        self._apply(engine, path)
        rows = read_trace_events(ledger, kinds=[CANDIDATES_EVENT])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["subject_id"], "t1")
        self.assertEqual(row["call_id"], "apply.rotation")
        self.assertEqual(row["lane"], "apply")
        self.assertEqual(row["primary"], APPLY)
        self.assertEqual(row["configured_pool"], [CODER_A])
        self.assertEqual([item["model"] for item in row["pool"]],
                         [APPLY, CODER_A])
        self.assertEqual([item["rank"] for item in row["pool"]], [1, 2])

    def test_each_attempt_is_recorded_in_the_order_it_happened(self):
        path = self.make_file()
        _fake, _gov, ledger, engine = self._env(
            posts=[(429, {"error": {"message": "rate limited", "cost": 0.0}}),
                   comp(CHANGED)])
        self._apply(engine, path)
        attempts = read_trace_events(ledger, kinds=[ATTEMPT_EVENT])
        self.assertEqual([row["model"] for row in attempts], [APPLY, CODER_A])
        # The attempt rows carry the billable record's own status vocabulary.
        self.assertEqual([row["status"] for row in attempts],
                         ["error", "unverified"])
        self.assertEqual([row["rank"] for row in attempts], [1, 2])
        self.assertEqual(attempts[0]["http_status"], 429)

    def test_a_reader_re_derives_the_order_from_the_rows(self):
        path = self.make_file()
        _fake, _gov, ledger, engine = self._env(
            posts=[(429, {"error": {"message": "rate limited", "cost": 0.0}}),
                   comp(CHANGED)])
        self._apply(engine, path)
        pool = read_trace_events(ledger, kinds=[CANDIDATES_EVENT])[0]
        attempts = read_trace_events(ledger, kinds=[ATTEMPT_EVENT])
        intended = [item["model"] for item in sorted(pool["pool"],
                                                     key=lambda i: i["rank"])]
        attempted = [row["model"] for row in attempts]
        self.assertEqual(attempted, intended)
        # The rank recorded on each attempt is the pool's own rank, not a
        # counter this run invented after the fact.
        by_model = {item["model"]: item["rank"] for item in pool["pool"]}
        for row in attempts:
            self.assertEqual(row["rank"], by_model[row["model"]])

    def test_without_a_trace_the_ledger_rows_are_unchanged(self):
        path = self.make_file()
        _fake, _gov, ledger, engine = self._env(trace=False)
        self._apply(engine, path)
        events = [entry["event"] for entry in ledger.entries()]
        self.assertEqual(events, ["offer", "dispatch_start", "model_result",
                                  "verify_round", "complete"])
        self.assertNotIn(CANDIDATES_EVENT, events)
        self.assertNotIn(ATTEMPT_EVENT, events)

    def test_a_refused_call_writes_nothing(self):
        path = self.make_file()
        _fake, _gov, ledger, engine = self._env()
        entry_count = len(ledger.entries())
        try:
            engine.apply_edit(task_id="never-offered", file_path=path,
                              instruction="x", require_consent=False)
        except Exception:
            pass
        self.assertEqual(len(ledger.entries()), entry_count)
        self.assertEqual(read_trace_events(ledger, kinds=[CANDIDATES_EVENT]), [])
        self.assertEqual(read_trace_events(ledger, kinds=[ATTEMPT_EVENT]), [])

    def test_the_chain_verifies_after_the_writes(self):
        path = self.make_file()
        _fake, _gov, ledger, engine = self._env()
        self._apply(engine, path)
        ok, detail = ledger.verify()
        self.assertTrue(ok, detail)

    def test_configured_pool_precedes_capability_ordering(self):
        path = self.make_file()
        _fake, _gov, ledger, engine = self.make_env(
            posts=[comp(CHANGED)], run=scripted_run([(0, "")]),
            router_kw={"apply_pool": [CODER_A, "stale/not-in-catalog"]})
        engine.trace = DecisionTrace(ledger)
        # Capability ordering ranks the pool and drops the stale id; the row
        # must still carry what the request configured so ``dropped`` is the
        # denominator ordering removed, not a truncated echo.
        with mock.patch("harness.apply.ordered_pool",
                        return_value=([CODER_A], {"x": {}})):
            self._apply(engine, path)
        row = read_trace_events(ledger, kinds=[CANDIDATES_EVENT])[0]
        self.assertEqual(row["configured_pool"],
                         [CODER_A, "stale/not-in-catalog"])
        self.assertEqual(row["dropped"], ["stale/not-in-catalog"])

    def test_a_paid_byok_attempt_is_recorded_before_rotation(self):
        path = self.make_file()
        byok = {"choices": [{"message": {"content": CHANGED},
                             "finish_reason": "stop"}],
                "usage": {"cost": 0.0002, "is_byok": True}}
        _fake, _gov, ledger, engine = self._env(
            posts=[byok, comp(CHANGED)])
        self._apply(engine, path)
        attempts = read_trace_events(ledger, kinds=[ATTEMPT_EVENT])
        self.assertEqual([row["model"] for row in attempts], [APPLY, CODER_A])
        self.assertEqual(attempts[0]["status"], "error")
        self.assertEqual(attempts[0]["reason"], "paid BYOK route")
        self.assertEqual(attempts[0]["rank"], 1)
