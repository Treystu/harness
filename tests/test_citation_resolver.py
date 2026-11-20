"""Hermetic tests for the DOI registry resolver adapter (#422).

No network: every test injects ``fetch``. The gate in citation_verify is tested
separately; these pin the adapter's half of the contract -- canonical metadata on
success, and a closed-set status (never invented metadata) on every failure.
"""
import unittest

from harness.citation_resolver import (
    DEFAULT_BASE_URL, RegistryResolver, ResolverTransportError, crossref_metadata,
    fetch_json,
)
from harness.citation_verify import verify_citation

DOI = "10.1234/abc"
WORK = {
    "message": {
        "DOI": "10.1234/ABC",
        "title": ["A Study of Things"],
        "author": [
            {"given": "Ada", "family": "Lovelace"},
            {"given": "Grace", "family": "Hopper"},
        ],
        "issued": {"date-parts": [[2024, 4, 1]]},
        "container-title": ["Journal of Tests"],
        "type": "journal-article",
    }
}
CITATION = {
    "citation_id": "ref-1",
    "doi": "https://doi.org/10.1234/abc",
    "title": "A Study of Things",
    "authors": ["Ada Lovelace", "Grace Hopper"],
    "year": 2024,
    "venue": "Journal of Tests",
    "version": "published",
}


def resolver_returning(payload=None, error=None):
    def _fetch(url, timeout=None):
        if error is not None:
            raise error
        return payload
    return RegistryResolver(fetch=_fetch)


class MappingTests(unittest.TestCase):
    def test_crossref_envelope_maps_to_the_gate_fields(self):
        metadata = crossref_metadata(WORK)
        self.assertEqual(metadata["doi"], DOI)
        self.assertEqual(metadata["title"], "A Study of Things")
        self.assertEqual(metadata["authors"], ["Ada Lovelace", "Grace Hopper"])
        self.assertEqual(metadata["year"], 2024)
        self.assertEqual(metadata["venue"], "Journal of Tests")
        self.assertEqual(metadata["version"], "published")

    def test_a_preprint_is_recorded_as_a_preprint(self):
        payload = {"message": {"DOI": DOI, "type": "posted-content"}}
        self.assertEqual(crossref_metadata(payload)["version"], "preprint")

    def test_a_payload_without_a_message_has_no_record(self):
        self.assertIsNone(crossref_metadata({"status": "ok"}))
        self.assertIsNone(crossref_metadata({}))

    def test_missing_fields_are_omitted_rather_than_guessed(self):
        metadata = crossref_metadata({"message": {"DOI": DOI}})
        self.assertEqual(metadata, {"doi": DOI, "authors": []})


class ResolverTests(unittest.TestCase):
    def test_a_found_record_resolves_with_canonical_identity(self):
        result = resolver_returning(WORK).resolve("https://doi.org/10.1234/ABC")
        self.assertTrue(result["found"])
        self.assertEqual(result["doi"], DOI)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["metadata_source"], f"crossref:{DOI}")

    def test_a_missing_doi_is_not_found_rather_than_an_error(self):
        error = ResolverTransportError("HTTP 404", status="unavailable",
                                       http_status=404)
        result = resolver_returning(error=error).resolve(DOI)
        self.assertEqual(result["found"], False)
        self.assertNotIn("metadata", result)

    def test_rate_limiting_surfaces_as_a_closed_set_status(self):
        error = ResolverTransportError("HTTP 429", status="rate_limited",
                                       http_status=429)
        result = resolver_returning(error=error).resolve(DOI)
        self.assertEqual(result["status"], "rate_limited")
        self.assertNotIn("metadata", result)

    def test_a_timeout_surfaces_as_a_timeout(self):
        error = ResolverTransportError("request timed out", status="timeout")
        result = resolver_returning(error=error).resolve(DOI)
        self.assertEqual(result["status"], "timeout")

    def test_a_non_doi_is_refused_before_any_request(self):
        def _fetch(url, timeout=None):
            raise AssertionError("no request may be made for a non-DOI")
        result = RegistryResolver(fetch=_fetch).resolve("not-a-doi")
        self.assertEqual(result["found"], False)
        self.assertIn("not a DOI", result["error"])

    def test_the_registry_is_addressed_by_url_with_an_optional_contact(self):
        resolver = RegistryResolver(contact="ops@example.test")
        self.assertEqual(resolver.url_for(DOI),
                         f"{DEFAULT_BASE_URL}/{DOI}?mailto=ops%40example.test")
        self.assertEqual(RegistryResolver().url_for(DOI),
                         f"{DEFAULT_BASE_URL}/{DOI}")


class GateIntegrationTests(unittest.TestCase):
    def test_a_matching_record_is_supported_through_the_gate(self):
        result = verify_citation(CITATION, resolver=resolver_returning(WORK))
        self.assertEqual(result["status"], "supported", result["reasons"])
        self.assertEqual(result["reasons"], [])
        self.assertEqual(result["canonical_doi"], DOI)
        self.assertTrue(result["metadata_source"].startswith("crossref:"))
        self.assertTrue(all(check["match"] for check in result["checks"].values()))

    def test_a_wrong_title_is_surfaced_field_by_field(self):
        payload = {"message": dict(WORK["message"], title=["A Different Study"])}
        result = verify_citation(CITATION, resolver=resolver_returning(payload))
        self.assertNotEqual(result["status"], "supported")
        self.assertIn("field_mismatch:title", result["reasons"])

    def test_a_rate_limited_registry_cannot_be_promoted_to_verified(self):
        error = ResolverTransportError("HTTP 429", status="rate_limited",
                                       http_status=429)
        result = verify_citation(CITATION, resolver=resolver_returning(error=error))
        self.assertEqual(result["status"], "not_verifiable")
        self.assertIn("resolver_rate_limited", result["reasons"])

    def test_a_missing_doi_is_reported_as_not_found(self):
        error = ResolverTransportError("HTTP 404", status="unavailable",
                                       http_status=404)
        result = verify_citation(CITATION, resolver=resolver_returning(error=error))
        self.assertIn("doi_not_found", result["reasons"])


class TransportTests(unittest.TestCase):
    def _fetch_with(self, outcome):
        import urllib.error
        import urllib.request
        original = urllib.request.urlopen

        def _fake(request, timeout=None):
            if isinstance(outcome, urllib.error.HTTPError):
                raise outcome
            return outcome

        urllib.request.urlopen = _fake
        self.addCleanup(lambda: setattr(urllib.request, "urlopen", original))
        return fetch_json("http://registry.test/10.1234/abc")

    def test_an_http_error_carries_its_closed_set_status(self):
        import urllib.error
        with self.assertRaises(ResolverTransportError) as raised:
            self._fetch_with(urllib.error.HTTPError(
                "http://registry.test", 429, "Too Many", {}, None))
        self.assertEqual(raised.exception.status, "rate_limited")
        self.assertEqual(raised.exception.http_status, 429)

    def test_a_body_that_is_not_json_is_a_transport_error(self):
        class _Response:
            status = 200

            def read(self):
                return b"<html>not json</html>"

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        with self.assertRaises(ResolverTransportError) as raised:
            self._fetch_with(_Response())
        self.assertIn("unparseable", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
