"""#344: resumed web context is bound to the current request and its freshness.

The recorded failures were a saved calculator-context checkpoint resumed with a
changed ocean-tides prompt (old evidence delivered, no rebuild) and a checkpoint
holding 24-hour-old web evidence resumed on a chat answer route (old evidence
delivered because freshness was only checked when the new turn asked for web).
"""
import time
import unittest

from harness.hourglass_lifecycle import (
    HourglassLifecycleMixin,
    _CONTEXT_REUSE_MAX_AGE_S,
    _request_identity,
)


class _Holder(HourglassLifecycleMixin):
    def __init__(self, root_dir=None):
        self.root_dir = root_dir


def _checkpoint(prompt="what is the capital of Chile",
                context="CONTEXT", sources=None, age=0.0):
    return {
        "context": context,
        "request_prompt": prompt,
        "workspace_root": "",
        "workspace_context_used": False,
        "file_hashes": {},
        "web_sources": list(sources or []),
        "context_updated_at": time.time() - age,
    }


_SOURCES = [{"kind": "web", "ok": True, "url": "https://example.com/",
             "title": "t", "text": "x"}]


class CheckpointContextBindingTests(unittest.TestCase):
    def setUp(self):
        self.holder = _Holder()

    def test_unchanged_request_with_fresh_evidence_is_reusable(self):
        cp = _checkpoint(sources=_SOURCES, age=5.0)
        self.assertEqual(
            self.holder._checkpoint_context_reusable(
                cp, "what is the capital of Chile"),
            (True, "reusable"))

    def test_a_changed_request_cannot_inherit_saved_evidence(self):
        cp = _checkpoint(prompt="audit www.freeoffgridcalculator.com",
                         sources=_SOURCES, age=5.0)
        reusable, reason = self.holder._checkpoint_context_reusable(
            cp, "what are the ocean tides today")
        self.assertFalse(reusable)
        self.assertEqual(reason, "request-changed")

    def test_day_old_evidence_is_stale_even_on_a_non_web_route(self):
        cp = _checkpoint(sources=_SOURCES, age=24 * 3600.0)
        reusable, reason = self.holder._checkpoint_context_reusable(
            cp, "what is the capital of Chile")
        self.assertFalse(reusable)
        self.assertEqual(reason, "evidence-stale")

    def test_evidence_just_inside_the_window_is_reusable(self):
        cp = _checkpoint(sources=_SOURCES, age=_CONTEXT_REUSE_MAX_AGE_S - 1.0)
        self.assertTrue(self.holder._checkpoint_context_reusable(
            cp, "what is the capital of Chile")[0])

    def test_context_without_web_evidence_has_no_staleness_clock(self):
        cp = _checkpoint(sources=[], age=24 * 3600.0)
        self.assertEqual(
            self.holder._checkpoint_context_reusable(
                cp, "what is the capital of Chile"),
            (True, "reusable"))

    def test_legacy_checkpoint_binds_to_its_saved_prompt(self):
        # Checkpoints written before request_prompt existed carry the request
        # as ``prompt``; continuation reuse still binds to it, both ways.
        cp = _checkpoint(sources=_SOURCES, age=1.0)
        cp["prompt"] = cp.pop("request_prompt")
        self.assertEqual(
            self.holder._checkpoint_context_reusable(
                cp, "what is the capital of Chile"),
            (True, "reusable"))
        self.assertEqual(
            self.holder._checkpoint_context_reusable(cp, "something else"),
            (False, "request-changed"))

    def test_checkpoint_with_no_request_identity_is_not_reused(self):
        cp = _checkpoint(sources=_SOURCES, age=1.0)
        del cp["request_prompt"]
        self.assertEqual(
            self.holder._checkpoint_context_reusable(
                cp, "what is the capital of Chile"),
            (False, "request-changed"))

    def test_no_saved_context_is_not_reused(self):
        cp = _checkpoint(context=None)
        self.assertEqual(
            self.holder._checkpoint_context_reusable(cp, "anything"),
            (False, "no-saved-context"))

    def test_unreadable_age_fails_closed(self):
        cp = _checkpoint(sources=_SOURCES)
        cp["context_updated_at"] = "yesterday"
        self.assertEqual(
            self.holder._checkpoint_context_reusable(
                cp, "what is the capital of Chile"),
            (False, "unreadable-context-age"))

    def test_request_identity_ignores_case_and_whitespace(self):
        self.assertEqual(_request_identity("  What  is\tJev? "),
                         _request_identity("what is jev?"))


if __name__ == "__main__":
    unittest.main()
