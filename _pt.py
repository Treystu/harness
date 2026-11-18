from pathlib import Path
p = Path("tests/test_ledger_sweep_336.py")
s = p.read_text(encoding="utf-8")
old = """    def seed(self):
        # Real task evidence: one honest outcome, one honest miss.
        self.ledger.append("task_outcome", task_id="real-1", task_family="fam","""
new = """    def seed(self):
        # Real task evidence: one honest outcome, one honest miss.
        self.ledger.append("offer", task_id="real-1", model="m1")
        self.ledger.append("task_outcome", task_id="real-1", task_family="fam","""
assert old in s
s = s.replace(old, new, 1)

old = """        for index in range(5):
            self.ledger.append("task_outcome", task_id="canary-%d" % index,"""
new = """        for index in range(5):
            self.ledger.append("offer", task_id="canary-%d" % index, model="m2")
            self.ledger.append("task_outcome", task_id="canary-%d" % index,"""
assert old in s
s = s.replace(old, new, 1)

old = """    def test_participation_report_counts_task_evidence_only(self):
        self.seed()
        report = self.ledger.participation_report()
        self.assertEqual(report.get("entries") or report.get("total_entries"), None) \
            if False else None
        # The canary rows are model_result/apply_attempt; the honest row is one.
        counts = json.dumps(report)"""
new = """    def test_participation_report_counts_task_evidence_only(self):
        self.seed()
        report = self.ledger.participation_report()
        # The canary rows are model_result/apply_attempt; only the honest one
        # may count here.
        counts = json.dumps(report)"""
assert old in s
s = s.replace(old, new, 1)

old = """    def test_the_calibration_join_ignores_canary_evals(self):
        self.ledger.append("jev_eval", task_id="real-1", site="s", verdict="pass","""
new = """    def test_the_calibration_join_ignores_canary_evals(self):
        self.ledger.append("offer", task_id="real-1", model="m1")
        self.ledger.append("offer", task_id="canary-1", model="m1")
        self.ledger.append("jev_eval", task_id="real-1", site="s", verdict="pass","""
assert old in s
s = s.replace(old, new, 1)

old = """        self.assertEqual(len(ledger_canary.evidence_rows(self.ledger)),
                         len(self.ledger.entries()) - 20)"""
new = """        self.assertEqual(len(ledger_canary.evidence_rows(self.ledger)),
                         len(self.ledger.entries()) - 22)"""
assert old in s
s = s.replace(old, new, 1)
p.write_text(s, encoding="utf-8")
print("patched")
