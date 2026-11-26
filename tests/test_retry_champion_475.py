"""#475: the retry champion, pinned — and the comment that misdescribed it.

The Champion Audit fixture is a champion replayed exactly as-is. These tests pin
the champion's constants and the delay schedule the panel loop computes, so a
silent change is a red test rather than a surprise in a measured run.

They also pin the invariant the audit's own filing depends on: a comment may
only claim Retry-After precedence for the panel retry path if that path reads
the header. It does not — the transport does, separately, capped at 6.0 s — and
`convergence.py` claimed otherwise until this item corrected it.

The precedence detector is deliberately careful, because the corrected comment
*quotes* the old claim in order to retract it: newlines are collapsed and quoted
fragments are removed before the claim is searched, and one test feeds the
original comment text through the same helper to prove the detector still fires
on the real defect rather than passing vacuously.
"""
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import harness.convergence as conv
import harness.events as events
import harness.jev as jev
from harness._http import HttpTransport
from harness.ledger import AutonomyLedger
from harness.panel import panel_judge
from tests._fake import JUDGE, P1, P2, FakeTransport, _gov

HARNESS = Path(conv.__file__).resolve().parent

#: The comment as it stood before this item, verbatim, for the anti-vacuity test.
ORIGINAL_COMMENT = ("MAX_429_RETRIES = 2\n"
                    "# Backoff base for bounded 429 retries; Retry-After headers "
                    "take precedence.\n"
                    "RETRY_429_BACKOFF_SECONDS = 0.5\n")


def claims_retry_after_precedence(text):
    """True only for an *affirmative*, un-quoted precedence claim in ``text``."""
    flat = " ".join(text.split())
    unquoted = re.sub(r'"[^"]*"', "", flat)
    unquoted = re.sub(r"\u201c[^\u201d]*\u201d", "", unquoted)
    return bool(re.search(r"retry[- ]after[^\n]{0,40}precede", unquoted, re.I))


def reads_retry_after(path):
    source = Path(path).read_text(encoding="utf-8").lower()
    return "retry-after" in source or "retry_after" in source


class ChampionConstantsTests(unittest.TestCase):
    def test_panel_retry_budget(self):
        self.assertEqual(conv.MAX_429_RETRIES, 2)

    def test_backoff_base(self):
        self.assertEqual(conv.RETRY_429_BACKOFF_SECONDS, 0.5)

    def test_breaker_threshold_cooldown_and_cap(self):
        self.assertEqual(jev.BREAKER_FAILURE_THRESHOLD, 3)
        self.assertEqual(jev.BREAKER_COOLDOWN_SECONDS, 30.0)
        self.assertEqual(jev.SHARED_BREAKER_CAP, 64)

    def test_champion_schedule_is_base_times_retry_number(self):
        schedule = [conv.RETRY_429_BACKOFF_SECONDS * n
                    for n in range(1, conv.MAX_429_RETRIES + 1)]
        self.assertEqual(schedule, [0.5, 1.0])
        # Two retries inside a 1.5 s window: the gap #475 questions, pinned so a
        # challenger's schedule can be compared against this exact number.
        self.assertEqual(sum(schedule), 1.5)


class CommentMatchesCodeTests(unittest.TestCase):
    def _window(self):
        lines = (HARNESS / "convergence.py").read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if "RETRY_429_BACKOFF_SECONDS" in line and "=" in line:
                return "\n".join(lines[max(0, index - 12):index])
        self.fail("RETRY_429_BACKOFF_SECONDS assignment not found")

    def test_panel_retry_loop_does_not_read_retry_after(self):
        self.assertFalse(reads_retry_after(HARNESS / "panel.py"))

    def test_the_backoff_comment_does_not_claim_precedence_it_lacks(self):
        window = self._window()
        self.assertGreater(len(window), 40, "comment window is empty -- vacuous check")
        self.assertFalse(claims_retry_after_precedence(window),
                         "comment claims Retry-After precedence the panel path "
                         "does not implement (#475)")
        self.assertIn("does not read retry-after", " ".join(window.lower().split()))

    def test_the_detector_still_fires_on_the_original_comment(self):
        # Anti-vacuity: the helper must catch the comment this item corrected.
        self.assertTrue(claims_retry_after_precedence(ORIGINAL_COMMENT))


class TransportRetryAfterTests(unittest.TestCase):
    def test_transport_honors_a_retry_after_value(self):
        self.assertEqual(HttpTransport()._retry_delay(0, "3"), 3.0)

    def test_transport_caps_the_honored_value(self):
        self.assertEqual(HttpTransport()._retry_delay(0, "99"), 6.0)

    def test_transport_falls_back_to_its_own_backoff(self):
        self.assertEqual(HttpTransport()._retry_delay(0, None), 0.75)
        self.assertEqual(HttpTransport()._retry_delay(2, "not-a-number"), 3.0)


def _model_entry(mid):
    return {"id": mid, "pricing": {"prompt": "0", "completion": "0"}}


def _chat_ok(text, *, cost=0.0001):
    return {"choices": [{"message": {"content": text}}],
            "usage": {"cost": cost}}


class BreakerAndRetryTelemetryTests(unittest.TestCase):
    def test_circuit_breaker_emits_lifecycle_transitions(self):
        now = [0.0]
        board = jev.CircuitBreakers(threshold=2, cooldown=30.0,
                                    clock=lambda: now[0])
        seen = []
        sink = events.add_sink(seen.append)
        try:
            refusal, g1 = board.acquire("chat")
            self.assertIsNone(refusal)
            board.record("chat", "failure", g1)
            refusal, g2 = board.acquire("chat")
            self.assertIsNone(refusal)
            board.record("chat", "failure", g2)

            refusal, _ = board.acquire("chat")
            self.assertIsNotNone(refusal)

            now[0] = 31.0
            refusal, g3 = board.acquire("chat")
            self.assertIsNone(refusal)
            board.record("chat", "failure", g3)

            now[0] = 62.0
            refusal, g4 = board.acquire("chat")
            self.assertIsNone(refusal)
            board.record("chat", "success", g4)
        finally:
            if sink is not None:
                events.remove_sink(sink)

        transitions = [e["transition"] for e in seen if e["type"] == "jev_breaker"]
        self.assertEqual(
            transitions,
            ["opened", "refused_open", "probe_admitted",
             "reopened", "probe_admitted", "closed"],
        )

    def test_panel_429_records_retry_position_delay_and_elapsed_s(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "ledger.jsonl")
            fake = FakeTransport(
                models=[_model_entry(P1), _model_entry(P2), _model_entry(JUDGE)],
                posts=[
                    (429, {"error": {"message": "rate limited"},
                           "usage": {"cost": 0.0002}}),
                    _chat_ok("recovered take", cost=0.0003),
                    (500, {"error": {"message": "down"}}),
                    _chat_ok("second panelist", cost=0.0001),
                    _chat_ok('{"verdict": "ok", "agreement": "high", '
                             '"confidence": 0.9, "disagreements": [], '
                             '"defer": false}', cost=0.0001),
                ],
            )
            gov = _gov(fake, max_cost=0.01)
            ledger = AutonomyLedger(path)
            ledger.ensure_offered_task_id("telemetry-475", source="test")
            seen = []
            sink = events.add_sink(seen.append)
            try:
                with mock.patch("harness.panel.interruptible_sleep"):
                    panel_judge(
                        transport=fake, api_key="k", governor=gov, prompt="Q?",
                        panel=[P1, P2], judge=JUDGE, max_panelists=2,
                        ledger=ledger, task_id="telemetry-475",
                    )
            finally:
                if sink is not None:
                    events.remove_sink(sink)
            rows = [e for e in ledger.entries() if e["event"] == "model_result"]
            retries = [r for r in rows if r.get("retry")]
            self.assertEqual(retries[0]["retry_position"], 1)
            self.assertEqual(retries[0]["retry_delay_s"], 0.5)
            finals = [r for r in rows if r["event_note"] == "panel" and not r.get("retry")]
            self.assertTrue(all("elapsed_s" in r for r in finals))
            rate_events = [e for e in seen if e.get("reason") == "rate_limited"]
            self.assertEqual(rate_events[0]["retry_position"], 1)
            self.assertEqual(rate_events[0]["retry_delay_s"], 0.5)


class OfflineComparatorReplayTests(unittest.TestCase):
    def test_simulate_retry_schedule_covers_champion_and_comparators(self):
        self.assertEqual(conv.simulate_retry_schedule([])["recovery_rate"], 0.0)
        timelines = [
            {"window_duration_s": 0.4, "retry_cost_usd": 0.0002},
            {"window_duration_s": 1.4, "retry_cost_usd": 0.0002},
            {"window_duration_s": 5.5, "retry_cost_usd": 0.0002},
            {"window_duration_s": None, "retry_cost_usd": 0.0002},
        ]
        champ = conv.simulate_retry_schedule(timelines)
        self.assertEqual(champ["recovered_calls"], 2)
        self.assertEqual(champ["recovery_rate"], 0.5)
        comp = conv.simulate_retry_schedule(timelines, max_retries=3, backoff_base=2.0)
        self.assertGreater(comp["recovered_calls"], champ["recovered_calls"])
        self.assertGreater(comp["total_wait_s"], champ["total_wait_s"])

    def test_simulate_breaker_schedule_covers_champion_and_comparators(self):
        trace = [
            {"t": 0.0, "site": "apply", "outcome": "neutral", "cost_usd": 0.0},
            {"t": 1.0, "site": "apply", "outcome": "failure", "cost_usd": 0.001},
            {"t": 2.0, "site": "apply", "outcome": "failure", "cost_usd": 0.001},
            {"t": 3.0, "site": "apply", "outcome": "failure", "cost_usd": 0.001},
            {"t": 5.0, "site": "apply", "outcome": "failure", "cost_usd": 0.001},
            {"t": 10.0, "site": "apply", "outcome": "success", "cost_usd": 0.001},
            {"t": 35.0, "site": "apply", "outcome": "success", "cost_usd": 0.001},
        ]
        champ = conv.simulate_breaker_schedule(trace)
        self.assertEqual(champ["threshold"], 3)
        self.assertEqual(champ["blocked"], 2)
        self.assertEqual(champ["avoided_failures"], 1)
        self.assertEqual(champ["false_blocks"], 1)
        self.assertAlmostEqual(champ["avoided_spend_usd"], 0.001, places=6)
        wider = conv.simulate_breaker_schedule(trace, threshold=5, cooldown_s=120.0)
        self.assertEqual(wider["blocked"], 0)
        self.assertEqual(wider["false_blocks"], 0)


if __name__ == "__main__":
    unittest.main()
