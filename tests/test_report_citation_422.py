"""#422 report-path acceptance: a report's citations are audited in product.

The deterministic gate (`harness.citation_verify`) and the registry adapter
(`harness.citation_resolver`, #645) both existed with no product importer, so
no user path could resolve a DOI or produce a citation-checked report. These
tests drive the product entry of the web report path (`run_prompt` ->
`_handle_conversation`) and assert that the returned report carries an audit
produced through `harness.citation_resolver`:

  * the registry resolver the product builds is the one that answers;
  * a citation is only `supported` when the resolved metadata matches what the
    source supplied, field by field;
  * a retrieval failure is recorded as `not_verifiable` with its reason;
  * the `citation_verified` label is never added by the report path -- an
    unassessed claim keeps it closed, which is the gate's contract.

The registry is replaced at the module seam, so nothing here touches the
network and no provider is billed.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from harness.agent import AutonomousAgent

DOI = "10.1000/xyz123"
DOI_URL = "https://doi.org/10.1000/xyz123"
PAGE_TITLE = "A bounded zero-free region for the Riemann zeta function"
PROMPT = f"what does {DOI_URL} support?"
PLAIN_URL = "https://example.org/paper"


class _Registry:
    """A registry answer with no network."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def resolve(self, doi):
        self.calls.append(doi)
        answer = dict(self.answer)
        answer.setdefault("doi", doi)
        return answer


class _RaisingRegistry:
    def __init__(self):
        self.calls = []

    def resolve(self, doi):
        self.calls.append(doi)
        raise RuntimeError("registry unreachable")


def _supported_registry():
    return _Registry({
        "found": True,
        "metadata": {"doi": DOI, "title": PAGE_TITLE},
        "metadata_source": f"crossref:{DOI}",
        "status": "ok",
    })


class TestReportCitationAudit(unittest.TestCase):
    def _agent(self, hdir):
        return AutonomousAgent(history_dir=Path(hdir))

    def _answer(self, agent, *, registry, page, prompt=PROMPT,
                session="c422"):
        """One web report turn through the product entry, hermetically."""
        response = {
            "choices": [{"message": {"content": "answer"}}],
            "usage": {"cost": 0.0},
        }
        with patch("harness.web.fetch_url", return_value=page), \
             patch("harness.web.search_web", return_value=[]), \
             patch("harness.conversation_lifecycle._report_citation_resolver",
                   return_value=registry), \
             patch("harness.conversation_lifecycle.chat_routed",
                   return_value=(200, response)), \
             patch("harness.conversation_lifecycle.governor_for",
                   return_value=(None, MagicMock())):
            return agent.run_prompt(prompt, session_id=session, web=True,
                                    force_conversation=True)

    def test_report_ships_a_citation_audit_resolved_by_the_product_resolver(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._agent(tmp)
            registry = _supported_registry()
            res = self._answer(
                agent, registry=registry,
                page={"url": DOI_URL, "title": PAGE_TITLE,
                      "text": "we prove a bounded zero-free region"})

        self.assertEqual(res["intent"], "conversation")
        audit = res["citation_audit"]
        # The product path itself reached the registry: this is the import
        # census moving from tests-only to product, proven by execution.
        self.assertEqual(registry.calls, [DOI])
        citation = audit["citations"][0]
        self.assertEqual(citation["citation_id"], "web-1")
        self.assertEqual(citation["canonical_doi"], DOI)
        self.assertEqual(citation["metadata_source"], f"crossref:{DOI}")
        self.assertEqual(citation["status"], "supported")
        self.assertEqual(audit["report"]["doi_citations"], 1)
        self.assertEqual(audit["report"]["sources"], 1)
        # The label stays the gate's: one citation is supported, but the claim
        # has no semantic assessment, so the report may not claim verification.
        self.assertIs(audit["citation_verified"], False)
        self.assertEqual(audit["label"], "not_verified")
        self.assertIn("semantic_support_unassessed", audit["claims"][0]["reasons"])

    def test_a_resolution_failure_is_recorded_not_promoted(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._agent(tmp)
            registry = _Registry({"status": "rate_limited"})
            res = self._answer(
                agent, registry=registry,
                page={"url": DOI_URL, "title": PAGE_TITLE,
                      "text": "abstract"})

        citation = res["citation_audit"]["citations"][0]
        self.assertEqual(registry.calls, [DOI])
        self.assertEqual(citation["status"], "not_verifiable")
        self.assertIn("resolver_rate_limited", citation["reasons"])
        self.assertEqual(res["citation_audit"]["label"], "not_verified")

    def test_a_raising_registry_never_costs_the_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._agent(tmp)
            registry = _RaisingRegistry()
            res = self._answer(
                agent, registry=registry,
                page={"url": DOI_URL, "title": PAGE_TITLE,
                      "text": "abstract"})

        self.assertEqual(res["status"], "ok")
        citation = res["citation_audit"]["citations"][0]
        self.assertEqual(citation["status"], "not_verifiable")
        self.assertTrue(any("resolver_error" in r for r in citation["reasons"]))
        self.assertIn("RuntimeError", citation["reasons"][0])

    def test_a_report_without_a_doi_still_carries_its_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = self._agent(tmp)
            registry = _supported_registry()
            res = self._answer(
                agent, registry=registry, prompt=f"what does {PLAIN_URL} say?",
                page={"url": PLAIN_URL, "title": "A paper",
                      "text": "no doi on this page"})

        audit = res["citation_audit"]
        self.assertEqual(registry.calls, [])
        self.assertEqual(audit["citations"], [])
        self.assertEqual(audit["report"]["sources"], 1)
        self.assertEqual(audit["report"]["doi_citations"], 0)
        self.assertEqual(audit["label"], "not_verified")
        self.assertIs(audit["citation_verified"], False)


if __name__ == "__main__":
    unittest.main()
