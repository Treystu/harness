"""DOI metadata resolution for the code-owned citation gate (#422).

`harness.citation_verify` is deterministic and performs no network: it takes a
``resolver`` and records whatever that resolver answers as evidence, including
refusals. What it has never had is a resolver, so in production every citation
ended ``not_verifiable`` with ``resolver_error: no DOI resolver was supplied``.

This module supplies that half in two separable pieces:

* :func:`fetch_json` -- the one HTTP call, stdlib only (the package has zero
  runtime dependencies), injectable so tests never touch the network;
* :class:`RegistryResolver` -- maps one registry's answer onto the contract
  ``citation_verify`` already documents: ``{"found", "doi", "metadata",
  "metadata_source", "status", "conflict", "error"}``.

The registry is addressed by base URL plus an optional response ``mapper``, so
the adapter is not welded to one provider's envelope. The default maps the
Crossref work envelope (``message``), which is also what several mirrors serve.

Failure is evidence, never invention: a 404 is ``found: False``, a 429 is
``rate_limited``, a 5xx is ``http_error``, a timeout is ``timeout``, an
unparseable body is an error, and none of them produce metadata. The gate turns
each of those into a closed-set reason and refuses the ``citation_verified``
label, which is the honest-insufficiency behaviour the issue requires.
"""
from typing import Any, Dict, Mapping, Optional
import json
import socket
import urllib.error
import urllib.parse
import urllib.request

from .citation_verify import audit_citations, normalize_doi
from .errors import HarnessError

#: Crossref's work endpoint. Named here so a caller can override it, not so the
#: rest of the module assumes it.
DEFAULT_BASE_URL = "https://api.crossref.org/works"
DEFAULT_TIMEOUT = 15.0
DEFAULT_SOURCE = "crossref"


class ResolverTransportError(Exception):
    """A resolver transport that produced no usable answer."""

    def __init__(self, message: str, *, status: str = "unavailable",
                 http_status: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status
        self.http_status = http_status


def fetch_json(url: str, *, timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """GET one JSON document. Raises :class:`ResolverTransportError` on failure.

    The exception carries a closed-set status from ``RETRIEVAL_STATUSES`` so the
    caller never has to classify an HTTP code twice.
    """
    request = urllib.request.Request(url, headers={
        "Accept": "application/json",
        # Crossref asks for a contact address; the caller may append one.
        "User-Agent": "sovereign-harness citation resolver",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            status = getattr(response, "status", 200)
    except urllib.error.HTTPError as exc:
        mapping = {401: "blocked", 403: "blocked", 402: "paywalled",
                   404: "unavailable", 429: "rate_limited"}
        code = int(exc.code)
        # The error object owns the response stream. Leaving it open leaks the
        # descriptor and surfaces as a ResourceWarning on any later GC, which
        # the hermetic audit treats as a failure of the whole suite. A
        # hand-built error object may carry no stream at all (and close()
        # itself raises there), so the release is best-effort by design.
        try:
            exc.close()
        except Exception:
            pass
        raise ResolverTransportError(
            f"HTTP {code}", status=mapping.get(code, "http_error"),
            http_status=code) from exc
    except (socket.timeout, TimeoutError) as exc:
        raise ResolverTransportError("request timed out", status="timeout") from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        status = "timeout" if isinstance(reason, (socket.timeout, TimeoutError)) \
            else "unavailable"
        raise ResolverTransportError(str(reason), status=status) from exc
    if status != 200:
        raise ResolverTransportError(f"HTTP {status}",
                                     status="http_error" if status >= 500 else
                                     "unavailable")
    try:
        return json.loads(body.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ResolverTransportError(f"unparseable registry body: {exc}",
                                     status="unavailable") from exc


def crossref_metadata(payload: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """Map a Crossref work envelope onto the gate's metadata fields.

    Returns ``None`` when the payload carries no work record, so a caller can
    tell "there is no record here" apart from "the record has empty fields".
    """
    message = payload.get("message")
    if not isinstance(message, Mapping):
        return None
    doi = normalize_doi(message.get("DOI") or payload.get("DOI") or "")
    authors = []
    for author in message.get("author") or ():
        if not isinstance(author, Mapping):
            continue
        given = str(author.get("given") or "").strip()
        family = str(author.get("family") or "").strip()
        name = " ".join(part for part in (given, family) if part)
        if not name:
            name = str(author.get("name") or "").strip()
        if name:
            authors.append(name)
    issued = message.get("issued") or {}
    parts = issued.get("date-parts") if isinstance(issued, Mapping) else None
    year = None
    if parts and isinstance(parts, (list, tuple)) and parts[0]:
        try:
            year = int(parts[0][0])
        except (TypeError, ValueError, IndexError):
            year = None
    titles = message.get("title") or ()
    title = str(titles[0]) if isinstance(titles, (list, tuple)) and titles \
        else (str(titles) if isinstance(titles, str) else "")
    containers = message.get("container-title") or ()
    venue = str(containers[0]) if isinstance(containers, (list, tuple)) and containers \
        else (str(containers) if isinstance(containers, str) else "")
    parent_type = str(message.get("type") or "").lower()
    subtype = str(message.get("subtype") or "").lower()
    if parent_type in ("posted-content", "preprint"):
        # Posted content is never formally published, whatever its subtype
        # (preprint, working paper, ...). Testing the subtype first stamped a
        # posted-content record with a non-preprint subtype as published (#73).
        version = "preprint"
    elif subtype in ("posted-content", "preprint"):
        version = "preprint"
    elif subtype or parent_type:
        version = "published"
    else:
        version = ""
    metadata: Dict[str, Any] = {"doi": doi, "authors": authors}
    if title:
        metadata["title"] = title
    if year is not None:
        metadata["year"] = year
    if venue:
        metadata["venue"] = venue
    if version:
        metadata["version"] = version
    return metadata


def default_resolver(*, contact: str = "",
                     timeout: float = DEFAULT_TIMEOUT) -> "RegistryResolver":
    """The resolver a product path uses when the caller supplies none.

    One function instead of a construction site in every caller, so the
    registry and the contact address are decided in one place. Tests never
    call this: they inject their own resolver at the call site.
    """
    return RegistryResolver(contact=contact, timeout=timeout)


#: Sentinel: "the caller said nothing", which means use the real registry.
#: ``None`` is different -- it means "audit without network", and every DOI
#: then stays ``not_verifiable`` rather than being looked up.
_UNSET = object()


def audit_report_citations(report: Any, *, resolver: Any = _UNSET,
                           contact: str = "") -> Dict[str, Any]:
    """Audit one report's declared bibliography and claim support (#422).

    ``report`` is a mapping with the sections the gate consumes:

    * ``citations`` -- bibliography items (``citation_id``/``id`` + DOI or URL);
    * ``citation_claims`` -- claims to assess, each with ``source_ids``;
    * ``sources`` -- retrieved source records admitted by #342/#344;
    * ``semantic_by_claim`` -- optional advisory Jev support per claim id.

    With ``resolver`` omitted the real Crossref registry answers; pass
    ``None`` to audit with no network at all. This is the product entry to the
    network half: the returned ``citation_verified`` flag is the same one
    ``audit_citations`` computes, so no caller can make a weaker claim than
    the gate itself does.
    """
    if not isinstance(report, Mapping):
        raise HarnessError(
            "citation audit: the report must be an object with its citation "
            "sections")
    use_default = resolver is _UNSET
    active = default_resolver(contact=contact) if use_default else resolver
    audit = audit_citations(
        report.get("citations") or [],
        report.get("citation_claims") or [],
        report.get("sources") or [],
        resolver=active,
        semantic_by_claim=report.get("semantic_by_claim") or {},
    )
    # The audit can only assess the claims it was handed. If the report's
    # claims section names an id that ``citation_claims`` omits, that claim was
    # never assessed -- leave it unresolved and refuse the report-level label
    # rather than certifying a report whose own claims escaped review (row 75).
    assessed = {
        str(raw.get("claim_id") or raw.get("id"))
        for raw in (report.get("citation_claims") or [])
        if isinstance(raw, Mapping) and (raw.get("claim_id") or raw.get("id"))
    }
    unassessed = [
        str(raw.get("claim_id") or raw.get("id"))
        for raw in (report.get("claims") or [])
        if isinstance(raw, Mapping) and (raw.get("claim_id") or raw.get("id"))
        and str(raw.get("claim_id") or raw.get("id")) not in assessed
    ]
    if unassessed:
        audit["unresolved"] = list(audit.get("unresolved") or []) + [
            {"kind": "claim", "id": claim_id, "status": "not_verifiable",
             "reasons": ["no citation assessment covers this claim"]}
            for claim_id in unassessed]
        audit["unassessed_claims"] = unassessed
        audit["citation_verified"] = False
        audit["ok"] = False
    # State which half answered, so a reader can tell a registry refusal from
    # an injected answer without guessing.
    audit["resolver"] = ("crossref" if use_default or isinstance(
        active, RegistryResolver) else "injected")
    return audit


class RegistryResolver:
    """Resolve a DOI to canonical metadata through one registry.

    ``fetch`` defaults to :func:`fetch_json` and takes ``(url, timeout=...)``;
    passing a different callable is how tests stay hermetic. ``mapper``
    defaults to :func:`crossref_metadata`.
    """

    def __init__(self, *, base_url: str = DEFAULT_BASE_URL,
                 fetch=None, mapper=None, timeout: float = DEFAULT_TIMEOUT,
                 source: str = DEFAULT_SOURCE,
                 contact: str = "") -> None:
        self.base_url = str(base_url).rstrip("/")
        self.fetch = fetch if fetch is not None else fetch_json
        self.mapper = mapper if mapper is not None else crossref_metadata
        self.timeout = float(timeout)
        self.source = str(source)
        self.contact = str(contact)

    def url_for(self, doi: str) -> str:
        url = f"{self.base_url}/{urllib.parse.quote(doi, safe='/')}"
        if self.contact:
            url = f"{url}?mailto={urllib.parse.quote(self.contact)}"
        return url

    def resolve(self, doi: str) -> Dict[str, Any]:
        canonical = normalize_doi(doi)
        if canonical is None:
            return {"found": False, "error": f"not a DOI: {doi!r}"}
        try:
            payload = self.fetch(self.url_for(canonical), timeout=self.timeout)
        except ResolverTransportError as exc:
            if exc.http_status == 404:
                return {"found": False, "doi": canonical,
                        "metadata_source": self.source}
            # No ``error`` key on a classified failure: the gate reads ``error``
            # first and would collapse a closed-set status into a generic
            # resolver_error, losing the reason an operator needs.
            return {"status": exc.status, "doi": canonical,
                    "metadata_source": self.source}
        metadata = self.mapper(payload) if isinstance(payload, Mapping) else None
        if metadata is None:
            return {"found": False, "doi": canonical,
                    "metadata_source": self.source}
        resolved_doi = normalize_doi(metadata.get("doi") or canonical) or canonical
        return {
            "found": True,
            "doi": resolved_doi,
            "metadata": metadata,
            "metadata_source": f"{self.source}:{resolved_doi}",
            "status": "ok",
        }
