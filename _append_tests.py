from pathlib import Path

p = Path("tests/test_ledger_sweep_336.py")
s = p.read_text(encoding="utf-8").replace("\r\n", "\n")

if "test_capability_observed_reliability_ignores_canary_rows" in s:
    print("already present")
    raise SystemExit(0)

block = '''
    def test_capability_observed_reliability_ignores_canary_rows(self):
        self.seed()
        self.assertEqual(capability.observed_samples(self.ledger, "m2"), 0)
        self.assertIsNone(capability.observed_json_reliability(self.ledger, "m2"))
        self.assertEqual(capability.observed_samples(self.ledger, "m1"), 1)
        self.assertEqual(
            capability.observed_json_reliability(self.ledger, "m1"), 1.0)

    def test_seat_share_is_a_task_selection_view(self):
        self.seed()
        report = capability.seat_share_report(self.ledger)
        self.assertNotIn("m2", json.dumps(report))

    def test_refinement_outcomes_ignore_canary_rows(self):
        self.seed()
        self.assertIsNone(refine.get_task_outcome(self.ledger, "canary-0"))
        self.assertIsNotNone(refine.get_task_outcome(self.ledger, "real-1"))
        rows = refine.recent_outcomes(self.ledger, "fam")
        self.assertEqual([row.get("task_id") for row in rows], ["real-1"])

    def test_the_pre_run_gate_does_not_fire_on_canary_429s(self):
        self.seed()
        with mock.patch.object(saturation, "_warned_this_process", False):
            self.assertFalse(saturation.pre_run_warning(ledger=self.ledger,
                                                        use_free=True))

    def test_export_refuses_a_canary_only_ledger(self):
        self.ledger.append("model_result", model="m1", canary=True, ok=True)
        with self.assertRaises(HarnessError):
            site_export.verify_chain(self.path)

    def test_the_calibration_join_ignores_canary_evals(self):
        self.ledger.append("offer", task_id="real-1", model="m1")
        self.ledger.append("offer", task_id="canary-1", model="m1", canary=True)
        self.ledger.append("jev_eval", task_id="real-1", site="s",
                           verdict="pass", confidence=0.9, supported=True,
                           is_fallback=False)
        self.ledger.append("jev_eval", task_id="canary-1", site="s",
                           verdict="pass", confidence=1.0, supported=True,
                           is_fallback=False, canary=True)
        report = self.ledger.jev_calibration_report()
        self.assertEqual(report.get("jev_evals"), 1)
        self.assertEqual(report.get("tasks_with_jev"), 1)

    def test_the_shared_reader_is_the_single_exclusion_point(self):
        self.seed()
        rows = ledger_canary.evidence_rows(self.ledger)
        self.assertTrue(all(row.get("canary") is not True for row in rows))
        self.assertEqual(len(rows), len(self.ledger.entries()) - 25)

'''

marker = '\nif __name__ == "__main__":'
assert marker in s
s = s.replace(marker, block + marker, 1)
p.write_text(s, encoding="utf-8")
print("appended")
