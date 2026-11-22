"""#660 line 2: snippet-versus-rendered provenance on the evidence the model reads.

A search hit is an excerpt the search engine wrote; a fetch is text extracted
from the page. Before this, the model was given ``SOURCE (search)`` /
``SOURCE (fetch)`` and nothing said which part it was reading, so a snippet
claim could be repeated as page content. These tests pin the distinction at
the producer (``gather_web_context``), at the shared label helper, and at the
answer-path formatter the model actually reads.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from harness import web


class ProvenanceTests(unittest.TestCase):
    def test_search_hit_is_a_snippet(self):
        source = {"kind": "search", "ok": True, "text": "excerpt"}
        self.assertEqual(web.evidence_provenance(source), web.EVIDENCE_SNIPPET)
        self.assertEqual(web.source_label(source), "search snippet")

    def test_fetched_page_is_rendered(self):
        source = {"kind": "fetch", "ok": True, "text": "page body"}
        self.assertEqual(web.evidence_provenance(source), web.EVIDENCE_RENDERED)
        self.assertEqual(web.source_label(source), "fetch rendered page")

    def test_a_snippet_is_never_labelled_rendered(self):
        # The whole point of the line: an excerpt must not read as page text,
        # whatever kind the surrounding pipeline recorded for it.
        snippet = {"kind": "search", "ok": True, "evidence": "snippet",
                   "text": "just an excerpt"}
        label = web.source_label(snippet)
        self.assertIn("snippet", label)
        self.assertNotIn("rendered", label)
        self.assertNotIn("page", label)

    def test_recorded_field_wins_over_the_kind(self):
        # A producer that fetched a page but could only keep a snippet says so.
        mixed = {"kind": "fetch", "ok": True, "evidence": "snippet",
                 "text": "excerpt"}
        self.assertNotIn("rendered", web.source_label(mixed))

    def test_unknown_recorded_value_is_not_guessed_at(self):
        odd = {"kind": "fetch", "ok": True, "evidence": "summary", "text": "x"}
        self.assertIsNone(web.evidence_provenance(odd))
        self.assertEqual(web.source_label(odd), "fetch")

    def test_other_kinds_carry_no_evidence_claim(self):
        self.assertIsNone(web.evidence_provenance({"kind": "browser", "ok": True}))
        self.assertEqual(web.source_label({"kind": "browser", "ok": True}),
                         "browser")


class ProducerTests(unittest.TestCase):
    """``gather_web_context`` tags what it actually read."""

    def test_search_only_path_records_snippets(self):
        sources = web.gather_web_context(
            "any news on the riemann bound",
            allowed_hosts=frozenset(),
            fetch_url_fn=lambda *a, **k: self.fail("must not fetch"),
            search_web_fn=lambda q: [
                {"title": "Hit", "url": "https://news.example/a",
                 "snippet": "bound moved to 67.2%"}],
            find_urls_fn=lambda p: [],
            extract_query_fn=lambda p: "riemann bound")
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["evidence"], "snippet")
        self.assertEqual(web.source_label(sources[0]), "search snippet")

    def test_enriched_page_records_rendered(self):
        sources = web.gather_web_context(
            "any news on the riemann bound",
            allowed_hosts=frozenset({"www.anthropic.com"}),
            fetch_url_fn=lambda url, **k: {
                "url": url, "title": "Page", "text": "full page text"},
            search_web_fn=lambda q: [
                {"title": "Primary", "url": "https://www.anthropic.com/r",
                 "snippet": "s2"}],
            find_urls_fn=lambda p: [],
            extract_query_fn=lambda p: "riemann bound")
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["evidence"], "rendered")
        self.assertEqual(web.source_label(sources[0]), "fetch rendered page")


class AnswerPathFormatterTests(unittest.TestCase):
    """The answer path names provenance for both kinds, and the legend."""

    def _agent(self, root):
        from tests.test_jev_answer_lifecycle import (
            AutonomousAgent, _ladder_settings,
        )
        return AutonomousAgent(settings=_ladder_settings(),
                               root_dir=root, history_dir=root)

    def test_snippet_and_rendered_are_distinguished_in_the_system_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._agent(Path(tmp))
            sources = [
                {"ok": True, "kind": "search", "evidence": "snippet",
                 "title": "Search hit", "url": "https://news.example/a",
                 "text": "bound moved to 67.2%"},
                {"ok": True, "kind": "fetch", "evidence": "rendered",
                 "title": "Paper", "url": "https://www.anthropic.com/r",
                 "text": "the page itself says so"},
            ]
            with patch("harness.hourglass_lifecycle.chat_routed",
                       return_value=(200, {"choices": [
                           {"message": {"content": "ok"}}],
                           "usage": {"cost": 0.0}})) as called:
                agent._hourglass_answer_once(
                    "q", "context", governor=MagicMock(), api_key="k",
                    web=True, web_sources=sources)
            sysmsg = called.call_args[1]["messages"][0]["content"]
        self.assertIn(
            "SOURCE (search snippet): Search hit https://news.example/a",
            sysmsg)
        self.assertIn(
            "SOURCE (fetch rendered page): Paper https://www.anthropic.com/r",
            sysmsg)
        # The snippet line must not borrow the rendered label.
        snippet_line = [ln for ln in sysmsg.splitlines()
                        if "https://news.example/a" in ln
                        and ln.startswith("SOURCE")][0]
        self.assertNotIn("rendered", snippet_line)
        self.assertIn("search snippet", sysmsg)
        self.assertIn("rendered page", sysmsg)  # the legend, in words


if __name__ == "__main__":
    unittest.main()
