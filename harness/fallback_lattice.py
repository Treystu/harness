"""The fallback lattice: deterministic rung-2 work for a declined request (#805).

A lifecycle may decline a request. Only the request router may conclude that a
request cannot be completed. The router keeps one request record across four
rungs:

1. a named or selected workflow, executed only when it is admissible within
   the request's target, effects and budget;
2. the deterministic workflow the request implies, with verb and object
   resolved together -- a site check probes the named site, a repo audit
   retrieves and inspects the named repository, a pull retrieves the named
   file's contents;
3. an alternate path against the same unfinished work, reusing whatever was
   already retrieved and reconciling uncertain outcomes before repeating an
   effect or a charge;
4. bounded best effort -- the strongest useful subset, with claims narrowed
   and constraints named rather than silently relaxed.

Terminal impossibility is a fixed-point record under four exhaustive grounds
(authority/resource limit; indispensable input unavailable; execution
capability unavailable; requirements jointly unsatisfiable) and names every
attempt that was made. A router exception, an unexpected tier, an empty
workspace selection and an untried candidate each fall short of that standard.

This module owns rung 2 and the record: target parsing, bounded HTTPS
acquisition of repository and file material, a deterministic review whose
findings each carry their evidence, and the fixed-point report. Every network
seam is a patchable module function, so the lattice is pinned hermetically.
"""
from __future__ import annotations

import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .errors import HarnessError, ToolCancelled
from .events import emit

#: Hosts whose repository and blob URLs resolve to retrievable material.
GITHUB_HOSTS = frozenset({"github.com", "www.github.com"})
GITHUB_API = "https://api.github.com"
GITHUB_RAW = "https://raw.githubusercontent.com"

#: Per-request limits. A retrieval that would exceed them is narrowed, and the
#: narrowing is named in the result instead of being silently applied.
MAX_FILES = 12
MAX_FILE_BYTES = 60000
MAX_PAGE_CHARS = 20000
ACQUISITION_TIMEOUT = 12.0

_CODE_SUFFIXES = (
    ".html", ".htm", ".js", ".mjs", ".css", ".py", ".json", ".md", ".txt",
)
_SKIPPED_DIRS = frozenset({
    "node_modules", ".git", "vendor", "__pycache__", ".venv", "venv",
})

_URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+")
#: A verb that makes a named target the object of real work rather than a
#: passing mention. Verb and object are resolved together: the verb alone
#: implies nothing, and the URL alone implies no operation.
_IMPLIED_VERBS = frozenset({
    "check", "audit", "verify", "pull", "retrieve", "inspect", "review",
    "validate", "fetch", "download", "confirm",
})
_ACCURACY_CLAIM_RE = re.compile(
    r"[^.\n]{0,120}(?:accura|precision|\u00b1\s*\d|error\s*(?:of|<\s*)?\d)"
    r"[^.\n]{0,120}", re.IGNORECASE)
_INSECURE_RESOURCE_RE = re.compile(
    r"(?:src|href)\s*=\s*[\"']http://[^\"']+", re.IGNORECASE)
_SCRIPT_SRC_RE = re.compile(
    r"<script\b[^>]*\bsrc\s*=\s*[\"']([^\"']+)[\"'][^>]*>", re.IGNORECASE)
_ID_ATTR_RE = re.compile(r"\bid\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
_HTML_LANG_RE = re.compile(r"<html\b[^>]*\blang\s*=", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title>\s*\S", re.IGNORECASE)
_HARDCODED_DEGREE_RE = re.compile(r"\b(?:0\.01745\d*|57\.295\d*)\b")
_LOCAL_TIME_RE = re.compile(
    r"getTimezoneOffset|Intl\.DateTimeFormat|toLocaleString|"
    r"toLocaleTimeString|timeZone")
_NAIVE_NOW_RE = re.compile(r"datetime\.now\(\s*\)")


# --------------------------------------------------------------------------
# Bounded transport (patchable seams)
# --------------------------------------------------------------------------
def _http_get_text(url, timeout=ACQUISITION_TIMEOUT,
                   accept="text/plain, text/html;q=0.9, */*;q=0.1"):
    """GET one https URL after proving its host resolves publicly.

    The public-address proof is the same guard the site probe and the governed
    fetcher use, so acquisition can never reach a private, loopback, or
    metadata address even though it is not allowlist-bound.
    """
    from .web import _resolved_addresses_public

    parsed = urllib.parse.urlsplit(str(url or ""))
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        raise HarnessError(f"acquisition refused: unusable url {url!r}")
    _resolved_addresses_public(host, socket.getaddrinfo)
    request = urllib.request.Request(
        url, headers={"User-Agent": "harness-fallback-lattice",
                      "Accept": accept})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200) or 200)
            raw = response.read(MAX_FILE_BYTES + 4096)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise HarnessError(f"acquisition failed for {url}: {exc}") from exc
    if status != 200:
        raise HarnessError(f"acquisition failed for {url}: HTTP {status}")
    return raw[:MAX_FILE_BYTES].decode("utf-8", "replace")


def _http_get_json(url, timeout=ACQUISITION_TIMEOUT):
    """GET one https JSON document through the same bounded seam."""
    text = _http_get_text(
        url, timeout=timeout, accept="application/vnd.github+json")
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise HarnessError(f"acquisition failed for {url}: unparseable JSON") from exc
    if not isinstance(payload, dict):
        raise HarnessError(f"acquisition failed for {url}: unexpected JSON shape")
    return payload


def _fetch_page(url, timeout=ACQUISITION_TIMEOUT):
    """Rung-3 alternate: retrieve the hosted page for a target URL.

    The page is a wrapper for repository and blob targets, so a page-only
    result is reported as partial coverage rather than as file contents.
    """
    from .web import fetch_url

    host = (urllib.parse.urlsplit(str(url or "")).hostname or "").lower()
    if not host:
        raise HarnessError(f"acquisition refused: no host in url {url!r}")
    page = fetch_url(url, allowed_hosts=(), named_hosts={host},
                     timeout=timeout, max_chars=MAX_PAGE_CHARS)
    return {"url": page.get("url") or url,
            "title": page.get("title") or "",
            "text": str(page.get("text") or "")[:MAX_PAGE_CHARS],
            "fetched_by": page.get("fetched_by") or "http"}


# --------------------------------------------------------------------------
# Target parsing
# --------------------------------------------------------------------------
def named_url(prompt) -> Optional[str]:
    """Return the first URL the request itself names."""
    match = _URL_RE.search(str(prompt or ""))
    if not match:
        return None
    return match.group(0).rstrip(".,;:!?)]}")


def parse_target(url) -> Optional[Dict[str, Any]]:
    """Resolve a URL into the material shape it names.

    ``repository`` and ``blob`` targets carry owner/repo (and, for a blob, the
    revision and path) so the deterministic workflow can retrieve contents.
    Every other URL is a ``page``.
    """
    text = str(url or "").strip()
    if not text:
        return None
    parsed = urllib.parse.urlsplit(text)
    host = (parsed.hostname or "").lower()
    if not host:
        return None
    entry: Dict[str, Any] = {"url": text, "host": host, "kind": "page",
                             "owner": None, "repo": None,
                             "revision": None, "path": None}
    if host not in GITHUB_HOSTS:
        return entry
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return entry
    owner, repo, rest = parts[0], parts[1], parts[2:]
    entry.update({"owner": owner, "repo": repo})
    if rest and rest[0] in ("blob", "tree"):
        entry["revision"] = urllib.parse.unquote(rest[1]) if len(rest) >= 2 else None
        if rest[0] == "blob" and len(rest) >= 3:
            entry["kind"] = "blob"
            entry["path"] = urllib.parse.unquote("/".join(rest[2:]))
        else:
            entry["kind"] = "repository"
        return entry
    entry["kind"] = "repository"
    return entry


def implied_operation(prompt) -> Optional[Dict[str, Any]]:
    """Resolve a request's verb and object into the workflow it implies.

    Only a named repository or blob target resolves here: a plain page target
    stays with the bounded site-check lane, which already owns it.
    """
    lowered = str(prompt or "").lower()
    if not any(verb in lowered for verb in _IMPLIED_VERBS):
        return None
    url = named_url(prompt)
    if url is None:
        return None
    target = parse_target(url)
    if target is None or target["kind"] == "page":
        return None
    return {"operation": ("retrieve_file" if target["kind"] == "blob"
                          else "inspect_repository"),
            "target": target}


# --------------------------------------------------------------------------
# Acquisition
# --------------------------------------------------------------------------
def _select_files(tree: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Pick a bounded, ranked set of inspectable text files from a tree."""
    entries = [entry for entry in (tree.get("tree") or [])
               if isinstance(entry, dict) and entry.get("type") == "blob"]
    ranked = []
    for entry in entries:
        path = str(entry.get("path") or "")
        if not path:
            continue
        if any(part in _SKIPPED_DIRS for part in path.split("/")[:-1]):
            continue
        suffix = os.path.splitext(path)[1].lower()
        if suffix not in _CODE_SUFFIXES:
            continue
        size = entry.get("size")
        if isinstance(size, int) and size > MAX_FILE_BYTES:
            continue
        rank = (_CODE_SUFFIXES.index(suffix), len(path), path)
        ranked.append((rank, {"path": path, "size": size}))
    ranked.sort(key=lambda item: item[0])
    return [entry for _rank, entry in ranked[:MAX_FILES]]


def acquire_file(target: Dict[str, Any], *, get_text=None,
                 attempts: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Retrieve one named file's contents at its recorded revision."""
    text_fn = get_text or _http_get_text
    owner, repo = target.get("owner"), target.get("repo")
    path = target.get("path")
    revision = target.get("revision") or "HEAD"
    if not (owner and repo and path):
        raise HarnessError("acquisition refused: incomplete file target")
    source = f"{GITHUB_RAW}/{owner}/{repo}/{revision}/{path}"
    text = text_fn(source)
    return {"kind": "blob", "revision": revision,
            "source": source, "files": {path: text},
            "paths_inspected": [path], "path": path}


def acquire_repository(target: Dict[str, Any], *, get_text=None,
                       get_json=None,
                       attempts: Optional[List[Dict[str, Any]]] = None
                       ) -> Dict[str, Any]:
    """Retrieve repository material at an identified revision.

    Metadata supplies the default branch and full name; the recursive tree
    supplies the candidate paths; contents come from the raw host. A file that
    fails to retrieve is recorded as a narrowing, never as a silent omission.
    """
    text_fn = get_text or _http_get_text
    json_fn = get_json or _http_get_json
    owner, repo = target.get("owner"), target.get("repo")
    if not (owner and repo):
        raise HarnessError("acquisition refused: incomplete repository target")
    meta = json_fn(f"{GITHUB_API}/repos/{owner}/{repo}")
    branch = str(meta.get("default_branch") or target.get("revision") or "main")
    revision = str(target.get("revision") or branch)
    tree = json_fn(
        f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{revision}?recursive=1")
    selected = _select_files(tree)
    files: Dict[str, str] = {}
    inspected: List[str] = []
    failures: List[Dict[str, str]] = []
    for entry in selected:
        path = entry["path"]
        source = f"{GITHUB_RAW}/{owner}/{repo}/{revision}/{path}"
        try:
            files[path] = text_fn(source)
        except HarnessError as exc:
            failures.append({"path": path, "error": str(exc)})
            continue
        inspected.append(path)
    if not inspected:
        detail = failures[0]["error"] if failures else "no inspectable text files"
        raise HarnessError(f"acquisition failed: no repository contents ({detail})")
    return {"kind": "repository", "revision": revision,
            "full_name": str(meta.get("full_name") or f"{owner}/{repo}"),
            "files": files, "paths_inspected": inspected,
            "failures": failures,
            "not_retrieved": [entry["path"] for entry in selected
                              if entry["path"] not in files]}


def acquire_target(target: Dict[str, Any], *, get_text=None, get_json=None,
                   attempts: Optional[List[Dict[str, Any]]] = None
                   ) -> Dict[str, Any]:
    """Retrieve the material a parsed target names."""
    if target.get("kind") == "blob":
        return acquire_file(target, get_text=get_text, attempts=attempts)
    if target.get("kind") == "repository":
        return acquire_repository(target, get_text=get_text, get_json=get_json,
                                  attempts=attempts)
    raise HarnessError(
        f"acquisition refused: {target.get('url')} names no retrievable material")


# --------------------------------------------------------------------------
# Deterministic review
# --------------------------------------------------------------------------
def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _check(path: str, name: str, passed: Optional[bool]) -> Dict[str, Any]:
    return {"path": path, "check": name,
            "result": ("pass" if passed else
                       "not_applicable" if passed is None else "fail")}


def _finding(path, check, line, severity, message, evidence,
             enhancement=None) -> Dict[str, Any]:
    return {"path": path, "check": check, "line": line,
            "severity": severity, "message": message,
            "evidence": evidence, "evidence_class": "code-reading",
            **({"enhancement": enhancement} if enhancement else {})}


def review_html(path: str, text: str):
    """Static checks over one HTML document, each with its evidence."""
    checks: List[Dict[str, Any]] = []
    findings: List[Dict[str, Any]] = []
    lowered = text.lower()

    doctype = "<!doctype" in lowered
    checks.append(_check(path, "doctype", doctype))
    if not doctype:
        findings.append(_finding(
            path, "doctype", 1, "minor",
            "the document has no doctype declaration",
            (text.splitlines() or [""])[0][:120],
            "start the document with <!doctype html> so the browser "
            "renders in standards mode"))

    lang = bool(_HTML_LANG_RE.search(text))
    checks.append(_check(path, "html_lang", lang))
    if not lang:
        findings.append(_finding(
            path, "html_lang", 1, "minor",
            "the root element declares no document language",
            (text.splitlines() or [""])[0][:120],
            "declare lang on <html> so assistive technology and "
            "hyphenation use the right language"))

    charset = "charset=" in lowered
    checks.append(_check(path, "charset", charset))
    if not charset:
        findings.append(_finding(
            path, "charset", 1, "minor",
            "no character-set declaration was found",
            (text.splitlines() or [""])[0][:120],
            "declare <meta charset=\"utf-8\"> so non-ASCII text such as "
            "degree signs decodes deterministically"))

    viewport = "name=\"viewport\"" in lowered or "name='viewport'" in lowered
    checks.append(_check(path, "viewport", viewport))
    if not viewport:
        findings.append(_finding(
            path, "viewport", 1, "minor",
            "no viewport meta tag was found",
            (text.splitlines() or [""])[0][:120],
            "declare a viewport so the page is not scaled on mobile"))

    title = bool(_TITLE_RE.search(text))
    checks.append(_check(path, "title", title))
    if not title:
        findings.append(_finding(
            path, "title", 1, "minor",
            "the document has no non-empty title",
            (text.splitlines() or [""])[0][:120],
            "give the document a title so tabs and share cards identify it"))

    insecure = list(_INSECURE_RESOURCE_RE.finditer(text))
    checks.append(_check(path, "insecure_resource", not insecure))
    for match in insecure:
        findings.append(_finding(
            path, "insecure_resource", _line_of(text, match.start()),
            "major",
            "a resource is loaded over plain HTTP from an HTTPS page",
            match.group(0)[:160],
            "load the resource over https so it is not blocked as mixed "
            "content and cannot be altered in transit"))

    scripts = list(_SCRIPT_SRC_RE.finditer(text))
    unverified = [match for match in scripts
                  if "integrity=" not in match.group(0).lower()
                  and str(match.group(1)).lower().startswith("https://")]
    checks.append(_check(path, "script_integrity", not unverified))
    for match in unverified:
        findings.append(_finding(
            path, "script_integrity", _line_of(text, match.start()),
            "minor",
            "an external script is loaded without a subresource integrity hash",
            match.group(0)[:160],
            "pin an integrity hash or self-host the script so a compromised "
            "CDN cannot change the page's behaviour"))

    id_counts: Dict[str, int] = {}
    id_first: Dict[str, int] = {}
    for match in _ID_ATTR_RE.finditer(text):
        value = match.group(1)
        id_counts[value] = id_counts.get(value, 0) + 1
        id_first.setdefault(value, match.start())
    duplicates = sorted(name for name, count in id_counts.items() if count > 1)
    checks.append(_check(path, "unique_ids", not duplicates))
    for name in duplicates:
        findings.append(_finding(
            path, "unique_ids", _line_of(text, id_first[name]), "major",
            f"the element id '{name}' is declared {id_counts[name]} times",
            f"id=\"{name}\" appears {id_counts[name]} times",
            "make ids unique so script and label lookups bind to one element"))

    claims = []
    for match in _ACCURACY_CLAIM_RE.finditer(text):
        claims.append({"path": path,
                       "line": _line_of(text, match.start()),
                       "text": " ".join(match.group(0).split())[:240]})
    checks.append(_check(path, "accuracy_claims_recorded", True))
    return checks, findings, claims


def review_script(path: str, text: str):
    """Static checks over one script or module, each with its evidence."""
    checks: List[Dict[str, Any]] = []
    findings: List[Dict[str, Any]] = []
    hardcoded = _HARDCODED_DEGREE_RE.search(text)
    checks.append(_check(path, "degree_conversion_constant", not hardcoded))
    if hardcoded:
        findings.append(_finding(
            path, "degree_conversion_constant",
            _line_of(text, hardcoded.start()), "major",
            "a rounded degree/radian constant is used instead of an exact "
            "conversion",
            hardcoded.group(0),
            "use Math.PI / 180 so the conversion is exact to the limit of "
            "the number type"))
    uses_date = "new Date(" in text or "Date.now(" in text
    zone_aware = bool(_LOCAL_TIME_RE.search(text))
    checks.append(_check(path, "timezone_explicit", None if not uses_date
                         else zone_aware))
    if uses_date and not zone_aware:
        first = text.find("new Date(")
        index = first if first >= 0 else text.find("Date.now(")
        findings.append(_finding(
            path, "timezone_explicit", _line_of(text, index), "minor",
            "wall-clock values are read from the host without an explicit "
            "time zone",
            (text.splitlines()[_line_of(text, index) - 1] or "")[:160],
            "name the time zone (Intl.DateTimeFormat or an explicit offset) "
            "so results do not change with the viewer's machine"))
    return checks, findings, []


def review_python(path: str, text: str):
    """Static checks over one Python source file."""
    checks: List[Dict[str, Any]] = []
    findings: List[Dict[str, Any]] = []
    naive = _NAIVE_NOW_RE.search(text)
    checks.append(_check(path, "naive_local_time", not naive))
    if naive:
        findings.append(_finding(
            path, "naive_local_time", _line_of(text, naive.start()), "minor",
            "datetime.now() returns a naive local time",
            (text.splitlines()[_line_of(text, naive.start()) - 1] or "")[:160],
            "use datetime.now(timezone.utc) so stored values are unambiguous"))
    return checks, findings, []


def review_material(material: Dict[str, Any]):
    """Review every retrieved file and collect checks, findings and claims."""
    checks: List[Dict[str, Any]] = []
    findings: List[Dict[str, Any]] = []
    claims: List[Dict[str, Any]] = []
    for path in material.get("paths_inspected") or []:
        text = (material.get("files") or {}).get(path, "")
        suffix = os.path.splitext(path)[1].lower()
        if suffix in (".html", ".htm"):
            file_checks, file_findings, file_claims = review_html(path, text)
        elif suffix in (".js", ".mjs"):
            file_checks, file_findings, file_claims = review_script(path, text)
        elif suffix == ".py":
            file_checks, file_findings, file_claims = review_python(path, text)
        else:
            file_checks, file_findings, file_claims = (
                [_check(path, "retrieved", True)], [], [])
        checks.extend(file_checks)
        findings.extend(file_findings)
        claims.extend(file_claims)
    return checks, findings, claims


# --------------------------------------------------------------------------
# Result construction
# --------------------------------------------------------------------------
def _severity_line(findings: List[Dict[str, Any]]) -> str:
    counts: Dict[str, int] = {}
    for finding in findings:
        counts[finding["severity"]] = counts.get(finding["severity"], 0) + 1
    return ", ".join(f"{count} {name}"
                     for name, count in sorted(counts.items())) or "none"


def build_report(prompt: str, material: Dict[str, Any],
                 checks: List[Dict[str, Any]],
                 findings: List[Dict[str, Any]],
                 claims: List[Dict[str, Any]],
                 *, reachability: Optional[Dict[str, Any]] = None,
                 narrowing: Optional[List[str]] = None) -> str:
    """Compose the evidence-bearing answer for a rung-2 execution."""
    revision = material.get("revision") or "unrecorded"
    paths = material.get("paths_inspected") or []
    lines = []
    if material.get("kind") == "blob":
        lines.append(f"Retrieved {material.get('path')} at revision "
                     f"{revision} and read its contents "
                     f"({len(material.get('files', {}).get(material.get('path'), ''))} "
                     "characters).")
    elif material.get("kind") == "page":
        page_text = (material.get("files") or {}).get("(hosted page)", "")
        lines.append(f"Retrieved the hosted page at {material.get('url')} "
                     f"({len(page_text)} characters of readable text).")
    else:
        name = material.get("full_name") or f"{material.get('owner')}/{material.get('repo')}"
        lines.append(f"Retrieved {name} at revision {revision} and read "
                     f"{len(paths)} file(s).")
    if reachability:
        status = reachability.get("http_status")
        verdict = reachability.get("verdict") or "unknown"
        if status is not None:
            lines.append(f"Reachability observed: the named URL answered "
                         f"HTTP {status} ({verdict}).")
        else:
            lines.append(f"Reachability observed: no HTTP status "
                         f"({verdict}).")
    lines.append("")
    lines.append("Paths inspected: " + (", ".join(paths) if paths else "none") + ".")
    passed = sum(1 for check in checks if check["result"] == "pass")
    lines.append(f"Checks performed: {len(checks)} across {len(paths)} "
                 f"file(s); {passed} passed, {len(checks) - passed} did not.")
    lines.append("")
    if findings:
        lines.append(f"Discrepancies found ({len(findings)}; "
                     f"{_severity_line(findings)}), each tied to its line:")
        for finding in findings:
            lines.append(
                f"- {finding['path']}:{finding['line']} [{finding['check']}] "
                f"{finding['message']} Evidence: {finding['evidence']}")
        enhancements = [finding for finding in findings
                        if finding.get("enhancement")]
        if enhancements:
            lines.append("")
            lines.append("Enhancements tied to those findings:")
            for finding in enhancements:
                lines.append(f"- {finding['path']}:{finding['line']} "
                             f"{finding['enhancement']} (from "
                             f"{finding['check']})")
    else:
        lines.append("No discrepancy was found by the static checks that ran; "
                     "that is a statement about those checks, not a claim that "
                     "the material is correct in every respect.")
    if claims:
        lines.append("")
        lines.append(f"Accuracy claims found in the material "
                     f"({len(claims)}):")
        for claim in claims[:6]:
            lines.append(f"- {claim['path']}:{claim['line']} "
                         f"{claim['text']}")
    if narrowing:
        lines.append("")
        lines.append("Coverage narrowed, and why:")
        for note in narrowing:
            lines.append(f"- {note}")
    lines.append("")
    lines.append(
        "Not tested: every property that requires executing the code -- live "
        "solar-position output, rendered layout, and timing accuracy against "
        "a reference. Findings above come from reading the retrieved bytes; "
        "inferences are labelled where they are not observations.")
    return "\n".join(lines)


def build_acquisition_result(prompt: str, material: Dict[str, Any],
                             *, attempts: List[Dict[str, Any]],
                             reason: str,
                             reachability: Optional[Dict[str, Any]] = None,
                             narrowing: Optional[List[str]] = None,
                             intent: str = "conversation") -> Dict[str, Any]:
    """Assemble the router-owned result for one executed rung-2 workflow."""
    checks, findings, claims = review_material(material)
    response = build_report(prompt, material, checks, findings, claims,
                            reachability=reachability, narrowing=narrowing)
    return {
        "status": "ok",
        "intent": intent,
        "workflow_tier": "deterministic-acquisition",
        "prompt": prompt,
        "answer": response,
        "response": response,
        "model": None,
        "cost": 0.0,
        "target": material.get("url") or material.get("source"),
        "revision": material.get("revision"),
        "paths_inspected": list(material.get("paths_inspected") or []),
        "checks": checks,
        "findings": findings,
        "claims": claims,
        "evidence": {"reachability": reachability,
                     "files": {path: len(text) for path, text
                               in (material.get("files") or {}).items()}},
        "fallback_lattice": {
            "rung": 2,
            "operation": "acquire_and_review",
            "reason": reason,
            "attempts": list(attempts),
        },
    }


def fixed_point_failure(prompt: str, target: Dict[str, Any],
                        attempts: List[Dict[str, Any]],
                        *, ground: str = "indispensable_input_unavailable",
                        intent: str = "conversation") -> Dict[str, Any]:
    """Record a terminal impossibility under one of the four named grounds.

    The difference from a defer is visible: every permitted attempt was
    performed and is listed, the observed error is quoted, the spend is stated,
    and no claim of accuracy or of permanent unavailability is made.
    """
    observed = "; ".join(
        f"{attempt.get('operation')} via {attempt.get('via')}: "
        f"{attempt.get('error')}"
        for attempt in attempts if attempt.get("error")) or "no attempt ran"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    response = (
        f"I could not complete this request against {target.get('url')}. "
        f"Ground: {ground.replace('_', ' ')}. Operation: "
        f"{attempts[0].get('operation') if attempts else 'acquisition'}. "
        f"Observed: {observed}. Attempts made: {len(attempts)}. "
        f"Time: {stamp}. Spend: $0.000000 (no model call was needed or "
        "billed). No conclusion is drawn about the target's accuracy from a "
        "retrieval that never returned material."
    )
    return {
        "status": "failed",
        "intent": intent,
        "workflow_tier": "deterministic-acquisition",
        "prompt": prompt,
        "response": response,
        "model": None,
        "cost": 0.0,
        "target": target.get("url"),
        "fixed_point": {
            "ground": ground,
            "operation": attempts[0].get("operation") if attempts else None,
            "observed": observed,
            "attempted_at": stamp,
            "attempts": list(attempts),
            "spend": 0.0,
        },
        "fallback_lattice": {
            "rung": 4,
            "operation": "bounded_best_effort",
            "reason": "every permitted attempt was performed and none "
                      "returned usable material",
            "attempts": list(attempts),
        },
    }


# --------------------------------------------------------------------------
# Router-owned dispatch
# --------------------------------------------------------------------------
class FallbackLatticeMixin:
    """Run the deterministic workflow a request implies, once, for the router."""

    def _lattice_probe(self, url: str, cancel_check=None):
        """Observe reachability of the named URL, tolerating its absence."""
        try:
            from .web import preflight_public_site, probe_public_site

            plan = preflight_public_site(url, cancel_check=cancel_check)
            return probe_public_site(url, preflight_plan=plan,
                                     cancel_check=cancel_check)
        except ToolCancelled:
            raise
        except HarnessError as exc:
            return {"ok": False, "http_status": None, "verdict": "refused",
                    "reason": str(exc)}

    def _run_acquired_workflow(self, prompt: str, implied: Dict[str, Any],
                               *, session_id: str, cancel_check=None,
                               attempts: Optional[List[Dict[str, Any]]] = None,
                               reason: str = "") -> Dict[str, Any]:
        """Rungs 2-4 over one named repository or file target."""
        from .history import save_chat_turn

        target = dict(implied["target"])
        operation = implied["operation"]
        record: List[Dict[str, Any]] = list(attempts or [])
        emit("lattice_rung_start", rung=2, operation=operation,
             target=target.get("url"))
        attempt = {"rung": 2, "operation": operation, "via": "material",
                   "target": target.get("url"), "outcome": None}
        material = None
        narrowing: List[str] = []
        try:
            if cancel_check and cancel_check():
                raise ToolCancelled("Prompt execution was cancelled by user")
            material = acquire_target(target)
            attempt["outcome"] = "ok"
            attempt["revision"] = material.get("revision")
        except ToolCancelled:
            raise
        except HarnessError as exc:
            attempt["outcome"] = "failed"
            attempt["error"] = str(exc)
            material = None
        record.append(attempt)
        emit("lattice_rung_complete", rung=2, outcome=attempt["outcome"])
        if material is None:
            # Rung 3: an alternate path against the same unfinished work. The
            # hosted page is retrieved for the same URL, and its coverage is
            # named so a wrapper can never pass as file contents.
            alternate = {"rung": 3, "operation": operation, "via": "page",
                         "target": target.get("url"), "outcome": None}
            emit("lattice_rung_start", rung=3, operation=operation,
                 target=target.get("url"))
            try:
                page = _fetch_page(target.get("url"))
            except ToolCancelled:
                raise
            except HarnessError as exc:
                alternate["outcome"] = "failed"
                alternate["error"] = str(exc)
            else:
                alternate["outcome"] = "partial"
                narrowing.append(
                    "the hosted page was retrieved, but the named file "
                    "contents were not; findings are limited to the page the "
                    "host renders and do not describe the repository bytes")
                material = {"kind": "page", "url": target.get("url"),
                            "revision": None, "path": None,
                            "files": {"(hosted page)": page.get("text") or ""},
                            "paths_inspected": ["(hosted page)"]}
            record.append(alternate)
            emit("lattice_rung_complete", rung=3, outcome=alternate["outcome"])
        if material is None:
            # Rung 4 fixed point: every permitted attempt ran and none
            # returned material, so the router records impossibility.
            emit("lattice_fixed_point", ground="indispensable_input_unavailable",
                 target=target.get("url"))
            result = fixed_point_failure(prompt, target, record)
            save_chat_turn(session_id, result, self.history_dir)
            return result

        reachability = None
        if material.get("kind") != "page":
            reachability = self._lattice_probe(target.get("url"), cancel_check)
        for failure in material.get("failures") or []:
            narrowing.append(
                f"{failure['path']} was not retrieved ({failure['error']}); "
                "the review covers the files that were")
        result = build_acquisition_result(
            prompt, material, attempts=record,
            reason=reason or "the deterministic workflow the request implies",
            reachability=reachability, narrowing=narrowing)
        save_chat_turn(session_id, result, self.history_dir)
        emit("lattice_complete", rung=2,
             paths=len(result["paths_inspected"]),
             findings=len(result["findings"]))
        return result

    def _implied_request_workflow(self, prompt: str, *, session_id: str,
                                  cancel_check=None,
                                  attempts: Optional[List[Dict[str, Any]]] = None,
                                  reason: str = "") -> Optional[Dict[str, Any]]:
        """Run rung 2 for the workflow this request implies, if any.

        Returns None when the request implies no deterministic workflow, so
        the caller keeps its own lane instead of inventing work.
        """
        implied = implied_operation(prompt)
        if implied is None:
            return None
        return self._run_acquired_workflow(
            prompt, implied, session_id=session_id,
            cancel_check=cancel_check, attempts=attempts, reason=reason)

    def _route_declined_request(self, prompt: str, session_id: str, *,
                               cancel_check=None, max_tokens=None,
                               reasoning_effort=None, token_budget=None,
                               web: bool = False,
                               reason: str = "") -> Dict[str, Any]:
        """Give a declined request back to the router, never to a dead end.

        Only the router concludes; every branch here executes something: the
        deterministic workflow the request implies, the workspace inspection
        lane when a workspace exists, or the ordinary conversation lane.
        """
        from .simple_request import is_workspace_inspection_request

        routed = self._implied_request_workflow(
            prompt, session_id=session_id, cancel_check=cancel_check,
            reason=reason or "the declined request names a retrievable target")
        if routed is not None:
            return routed
        emit("lattice_fallthrough", lane="declined-request",
             target=bool(named_url(prompt)))
        if (is_workspace_inspection_request(prompt)
                and getattr(self, "root_dir", None) is not None):
            return self.run_hourglass_request(
                prompt, session_id=session_id, cancel_check=cancel_check,
                web=False, max_tokens=max_tokens,
                reasoning_effort=reasoning_effort, token_budget=token_budget)
        if self._live_jev_available():
            return self.run_hourglass_request(
                prompt, session_id=session_id, cancel_check=cancel_check,
                web=web, max_tokens=max_tokens,
                reasoning_effort=reasoning_effort, token_budget=token_budget)
        return self._run_fallback_conversation(
            prompt, session_id, cancel_check=cancel_check, web=web,
            max_tokens=max_tokens, reasoning_effort=reasoning_effort,
            token_budget=token_budget)
