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
import re
import unittest
from pathlib import Path

import harness.convergence as conv
import harness.jev as jev
from harness._http import HttpTransport

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


if __name__ == "__main__":
    unittest.main()
