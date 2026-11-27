"""Phase budgets are per phase, and a kill names the budget.

Measured 2026-11-27 on standing-20261127-coldlane2: one flat 65 s deadline cut
the search phase off in its sixth sidebar scroll round, so the run parked as
"search: driver tree terminated after deadline" - a killed phase, not a finding.
The census is the longest leg by design; it gets a census-sized budget, and the
budget is written to the audit before the phase runs so a park can name it.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import windows_freebuff_runner as runner


class _FakeProcess:
    pid = 4242
    returncode = 0

    def communicate(self, timeout=None):
        return "Platform state: ok", ""


class PhaseBudgetTests(unittest.TestCase):
    def test_each_phase_gets_a_budget_sized_for_its_own_work(self):
        self.assertGreaterEqual(runner._phase_deadline("search"), 240)
        self.assertGreaterEqual(runner._phase_deadline("query"), 240)
        self.assertGreaterEqual(runner._phase_deadline("prepare"), 120)
        self.assertGreaterEqual(runner._phase_deadline("send"), 120)

    def test_a_caller_override_still_wins(self):
        """The watch's dynamic timeout for a census result is the operator's call."""
        self.assertEqual(runner._phase_deadline("search", 480), 480.0)

    def test_the_budget_is_recorded_before_the_phase_runs(self):
        audit = Mock()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(runner.subprocess, "Popen", return_value=_FakeProcess()):
                ran = runner.run_phases(Path(tmp), "9ecc3453", audit,
                                        phases=("search",), standing=True)
        self.assertTrue(ran)
        streams = [call.kwargs for call in audit.append.call_args_list
                   if call.kwargs.get("step_id") == "phase-budget-search"]
        self.assertEqual(len(streams), 1)
        self.assertEqual(streams[0]["seconds"], 240.0)

    def test_a_kill_names_the_budget_it_exceeded(self):
        class _Stuck(_FakeProcess):
            def communicate(self, timeout=None):
                # Only the phase budget starves; the post-kill drain returns.
                if timeout and timeout > 60:
                    raise __import__("subprocess").TimeoutExpired("child", timeout)
                return "", ""

        audit = Mock()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(runner.subprocess, "Popen", return_value=_Stuck()), \
                    patch.object(runner.subprocess, "run",
                                 return_value=Mock(returncode=0)):
                with self.assertRaisesRegex(RuntimeError, r"search: .*\(240s budget\)"):
                    runner.run_phases(Path(tmp), "9ecc3453", audit,
                                      phases=("search",), standing=True)


if __name__ == "__main__":
    unittest.main()

class ObserveRunningBudgetTests(unittest.TestCase):
    """Measured on dyn-7226574169: a literal 20 s killed the probe mid-capture."""

    def test_the_probe_takes_its_budget_from_the_table(self):
        self.assertEqual(runner._phase_deadline("observe-running"),
                         float(runner.DEFAULT_PHASE_TIMEOUT))
        self.assertGreaterEqual(runner.DEFAULT_PHASE_TIMEOUT, 60)

    def test_the_runner_does_not_hardcode_the_probe_deadline(self):
        source = Path(runner.__file__).read_text(encoding="utf-8")
        self.assertNotIn('("observe-running",), standing=True, timeout=20', source)
