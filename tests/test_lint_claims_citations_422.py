"""The #422 call site: `lint-claims` audits a declared bibliography.

Hermetic by construction. The registry is reached through one seam
(`harness.cli._citation_resolver`), which these tests replace, so no test
touches the network and the real `RegistryResolver` is exercised by
`tests/test_citation_resolver.py` on its own.
"""
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from harness import cli  # noqa: E402
from harness.citation_resolver import audit_report_citations, default_resolver  # noqa: E402
from harness.citation_verify import normalize_doi  # noqa: E402

DOI = "10.1000/xyz123"
WORK = {
    "found": True,
    "doi": DOI,
    "metadata": {"doi": DOI, "title": "A Verified Paper", "authors": ["Ada Lovelace"],
                 "year": 2024, "venue": "Journal of Tests", "version": "published"},
    "metadata_source": "crossref:" + DOI,
    "status": "ok",
}
SOURCE = {
    "source_id": "s1",
    "url": "https://example.org/paper",
    "source_class": "journal",
    "retrieved_at": "2026-11-22T00:00:00Z",
    "passage": "The measured effect was 4.2 points.",
    "locator": "p. 3",
    "doi": DOI,
}


def _manifest(**extra):
    base = {
        "context": "one report",
        "claims": [{"id": "c1", "text": "The effect was measured.", "source_refs": [1]}],
        "citations": [{"citation_id": "b1", "doi": DOI, "title": "A Verified Paper",
                       "authors": ["Ada Lovelace"], "year": 2024,
                       "venue": "Journal of Tests", "version": "published"}],
        "citation_claims": [{"claim_id": "c1", "source_ids": ["s1"]}],
        "sources": [SOURCE],
        # The gate refuses to call a claim supported on provenance alone: the
        # semantic advisory is required, exactly as #422 specifies.
        "semantic_by_claim": {"c1": {"status": "supported", "confidence": 0.93,
                                      "model": "stub-judge"}},
    }
    base.update(extra)
    return base


class _StubResolver:
    def __init__(self, answer=None):
        self.answer = answer or WORK

    def resolve(self, doi):
        return dict(self.answer)


class LintClaimsCitationAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = os.path.join(self.tmp.name, "source.txt")
        with open(self.source, "w", encoding="utf-8") as f:
            f.write("line one\nThe effect was measured.\n")

    def _write(self, payload):
        path = os.path.join(self.tmp.name, "manifest.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        return path

    def _run(self, payload, *extra):
        manifest = self._write(payload)
        argv = ["lint-claims", "--claims-file", manifest,
                "--source-file", self.source, *extra]
        out, err = StringIO(), StringIO()
        code = 0
        with redirect_stdout(out), redirect_stderr(err):
            try:
                cli.main(argv)
            except SystemExit as exc:
                code = int(exc.code or 0)
        return code, out.getvalue(), err.getvalue()

    def _resolved(self, answer=None):
        return mock.patch.object(cli, "_citation_resolver",
                                 return_value=_StubResolver(answer))

    def test_a_resolvable_report_passes_and_is_labeled_verified(self):
        with self._resolved():
            code, out, _ = self._run(_manifest())
        self.assertEqual(code, 0, out)
        report = json.loads(out)
        self.assertTrue(report["ok"])
        self.assertTrue(report["citation_verified"])
        self.assertEqual(report["citation_audit"]["resolver"], "injected")
        self.assertEqual(report["citation_audit"]["unresolved"], [])

    def test_a_fabricated_doi_now_fails_this_gate(self):
        # The recorded defect: a DOI nobody can resolve used to pass with
        # ok=True because nothing ever asked a registry.
        with self._resolved({"found": False, "doi": DOI}):
            code, out, err = self._run(_manifest())
        self.assertEqual(code, 2)
        report = json.loads(out)
        self.assertFalse(report["ok"])
        self.assertFalse(report["citation_verified"])
        self.assertIn("doi_not_found", err)

    def test_a_title_mismatch_is_surfaced_field_by_field(self):
        wrong = dict(WORK, metadata=dict(WORK["metadata"], title="A Different Paper"))
        with self._resolved(wrong):
            code, out, _ = self._run(_manifest())
        self.assertEqual(code, 2)
        report = json.loads(out)
        checks = report["citation_audit"]["citations"][0]["checks"]
        self.assertFalse(checks["title"]["match"])
        self.assertEqual(checks["title"]["resolved"], "A Different Paper")

    def test_a_registry_rate_limit_is_not_verified(self):
        with self._resolved({"status": "rate_limited", "doi": DOI,
                             "metadata_source": "crossref"}):
            code, out, err = self._run(_manifest())
        self.assertEqual(code, 2)
        self.assertIn("resolver_rate_limited", err)

    def test_no_network_flag_records_every_doi_as_not_verifiable(self):
        with mock.patch.object(cli, "_citation_resolver") as resolver:
            code, out, _ = self._run(_manifest(), "--no-network")
        resolver.assert_not_called()
        self.assertEqual(code, 2)
        report = json.loads(out)
        self.assertFalse(report["citation_verified"])
        self.assertEqual(report["citation_audit"]["resolver"], "injected")
        reasons = report["citation_audit"]["citations"][0]["reasons"]
        self.assertTrue(any("no DOI resolver was supplied" in r for r in reasons), reasons)

    def test_a_manifest_without_citations_is_unchanged(self):
        payload = {"context": "plain", "claims": [{"id": "c1", "text": "The effect was measured.",
                                                  "source_refs": [2]}]}
        with mock.patch.object(cli, "_citation_resolver") as resolver:
            code, out, _ = self._run(payload)
        resolver.assert_not_called()
        self.assertEqual(code, 0, out)
        report = json.loads(out)
        self.assertTrue(report["ok"])
        self.assertNotIn("citation_audit", report)

    def test_a_claim_without_supporting_evidence_blocks_the_label(self):
        payload = _manifest(citation_claims=[{"claim_id": "c1", "source_ids": []}])
        with self._resolved():
            code, _out, err = self._run(payload)
        self.assertEqual(code, 2)
        self.assertIn("no_source_records", err)

    def test_an_unassessed_claim_blocks_the_label(self):
        payload = _manifest(semantic_by_claim={})
        with self._resolved():
            code, _out, err = self._run(payload)
        self.assertEqual(code, 2)
        self.assertIn("semantic_support_unassessed", err)


class AuditReportCitationsTests(unittest.TestCase):
    def test_the_report_entry_uses_the_real_registry_when_none_is_given(self):
        audit = audit_report_citations({"citations": [], "citation_claims": [],
                                        "sources": []})
        self.assertEqual(audit["resolver"], "crossref")
        self.assertFalse(audit["citation_verified"])

    def test_an_explicit_none_resolver_means_no_network(self):
        audit = audit_report_citations(
            {"citations": [{"citation_id": "b1", "doi": DOI}],
             "citation_claims": [], "sources": []}, resolver=None)
        self.assertEqual(audit["resolver"], "injected")
        self.assertTrue(audit["citations"][0]["reasons"])

    def test_a_non_object_report_is_refused(self):
        from harness.errors import HarnessError

        with self.assertRaises(HarnessError):
            audit_report_citations(["not", "a", "mapping"])

    def test_the_default_resolver_is_a_registry_adapter(self):
        from harness.citation_resolver import RegistryResolver

        self.assertIsInstance(default_resolver(), RegistryResolver)

    def test_normalize_doi_is_the_gate_owner_still(self):
        self.assertEqual(normalize_doi("https://doi.org/" + DOI), DOI)


if __name__ == "__main__":
    unittest.main()
