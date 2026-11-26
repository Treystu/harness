"""#342: the single owner of a bounded, request-bound research plan.

Route selection only proposes retrieval; it never authorizes it. This module
owns the typed plan, its request binding, its validation, and the bounded
execution that turns an accepted plan into the exact search/fetch calls it
names. Native Jev owns the judgment (:meth:`JevPolicy.evaluate_research_plan`),
and code turns that judgment into a :class:`PlanApproval`, so an advisory
heuristic preview can never become native approval.

Rules this module enforces, each with a typed rejection code:

* the plan is versioned and bound to one request id and one request hash;
* every query carries a stable id, the exact string, and its purpose;
* quoted logs, pasted traces, fenced code and block quotations are untrusted
  context: a plan string that only appears there is not search intent;
* the plan declares its capabilities, domains, freshness, evidence needs,
  budget and a no-silent-fallback policy, and is rejected without them;
* execution sends only the accepted exact query strings and URLs, never a
  derived one, and a zero-text fetch ends with insufficient evidence rather
  than an implicit search;
* every rejection executes zero searches and zero fetches.

The module has no network seams of its own: search and fetch are injected, so
the whole contract is testable without a public network.
"""
import hashlib
import json
import re
import time
from dataclasses import dataclass, replace
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple

from .errors import ProviderUsageUnknown, ToolCancelled
from .events import emit

from .errors import HarnessError

SCHEMA_VERSION = 1
MAX_PLAN_QUERIES = 4
MAX_PLAN_REVISIONS = 2
MAX_RESULTS = 10
MAX_SOURCES = 5
MAX_TIMEOUT_S = 60.0
MAX_QUERY_CHARS = 300
MIN_QUERY_CHARS = 3
FALLBACK_NONE = "none"
CAPABILITIES = ("search", "fetch", "browser")

#: Native decision vocabulary (what Jev answers).
DECISION_ACCEPT = "accept"
DECISION_REVISE = "revise"
DECISION_DECLINE = "decline"
DECISION_INVALID = "invalid"
DECISION_UNAVAILABLE = "unavailable"

#: Execution states (what the runner reports).
EXECUTED = "executed"
STATE_DECLINED = "declined"
STATE_UNAVAILABLE = "unavailable"
STATE_INVALID = "invalid"
INSUFFICIENT = "insufficient-evidence"

QUERY_SEARCH = "search"
QUERY_FETCH = "fetch"


@dataclass(frozen=True)
class PlanQuery:
    """One exact retrieval action the plan proposes."""

    query_id: str
    query: str
    purpose: str
    url: str = ""

    @property
    def kind(self) -> str:
        return QUERY_FETCH if self.url else QUERY_SEARCH


@dataclass(frozen=True)
class ResearchPlan:
    """A typed, request-bound retrieval plan. Code validates; Jev decides."""

    goal: str
    request_id: str
    request_hash: str
    queries: Tuple[PlanQuery, ...] = ()
    domains: Tuple[str, ...] = ()
    freshness: str = ""
    evidence_requirements: Tuple[str, ...] = ()
    max_results: int = 3
    max_sources: int = 3
    timeout_s: float = 12.0
    max_tokens: int = 0
    max_spend_usd: float = 0.0
    capabilities: Tuple[str, ...] = ()
    fallback_policy: str = FALLBACK_NONE
    revision: int = 0
    schema_version: int = SCHEMA_VERSION

    def payload(self) -> Dict[str, Any]:
        """Canonical, hashable form. Every compared field is present."""
        return {
            "schema_version": int(self.schema_version),
            "request_id": str(self.request_id),
            "request_hash": str(self.request_hash),
            "goal": str(self.goal),
            "queries": [
                {"query_id": str(q.query_id), "query": str(q.query),
                 "purpose": str(q.purpose), "url": str(q.url),
                 "kind": q.kind}
                for q in self.queries
            ],
            "domains": [str(d) for d in self.domains],
            "freshness": str(self.freshness),
            "evidence_requirements": [str(e) for e in self.evidence_requirements],
            "max_results": int(self.max_results),
            "max_sources": int(self.max_sources),
            "timeout_s": float(self.timeout_s),
            "max_tokens": int(self.max_tokens),
            "max_spend_usd": float(self.max_spend_usd),
            "capabilities": [str(c) for c in self.capabilities],
            "fallback_policy": str(self.fallback_policy),
            "revision": int(self.revision),
        }

    def hash(self) -> str:
        return _hash(self.payload())

    @classmethod
    def from_payload(cls, payload: Any) -> Optional["ResearchPlan"]:
        """Rebuild a plan from its canonical payload, or ``None``.

        #344: a lane persists ``payload()`` beside the plan hash, so a resume
        that supplies no plan can still compare the saved route decision with
        the plan it was actually made under. Only an exact read is usable: a
        missing field, a wrong type or another schema version returns ``None``
        and the caller decides again instead of reusing an unread decision.
        """
        if not isinstance(payload, dict):
            return None
        try:
            if int(payload["schema_version"]) != SCHEMA_VERSION:
                return None
            queries = tuple(
                PlanQuery(query_id=str(item["query_id"]),
                          query=str(item["query"]),
                          purpose=str(item["purpose"]),
                          url=str(item.get("url") or ""))
                for item in payload["queries"])
            return cls(
                goal=str(payload["goal"]),
                request_id=str(payload["request_id"]),
                request_hash=str(payload["request_hash"]),
                queries=queries,
                domains=tuple(str(d) for d in payload["domains"]),
                freshness=str(payload["freshness"]),
                evidence_requirements=tuple(
                    str(e) for e in payload["evidence_requirements"]),
                max_results=int(payload["max_results"]),
                max_sources=int(payload["max_sources"]),
                timeout_s=float(payload["timeout_s"]),
                max_tokens=int(payload["max_tokens"]),
                max_spend_usd=float(payload["max_spend_usd"]),
                capabilities=tuple(str(c) for c in payload["capabilities"]),
                fallback_policy=str(payload["fallback_policy"]),
                revision=int(payload["revision"]),
                schema_version=int(payload["schema_version"])
            )
        except (KeyError, TypeError, ValueError):
            return None

    def revised(self, **changes: Any) -> "ResearchPlan":
        """A new revision of the same plan; the request binding is kept."""
        revision = int(changes.pop("revision", self.revision + 1))
        return replace(self, revision=revision, **changes)


@dataclass(frozen=True)
class PlanApproval:
    """The code-owned receipt that one native judgment approved this plan."""

    decision: str
    native: bool
    plan_hash: str
    request_hash: str
    revision: int
    confidence: float = 0.0
    consent_id: str = ""
    issued_at: float = 0.0
    expires_at: float = 0.0
    query_verdicts: Tuple[bool, ...] = ()

    def payload(self) -> Dict[str, Any]:
        return {
            "decision": str(self.decision),
            "native": bool(self.native),
            "plan_hash": str(self.plan_hash),
            "request_hash": str(self.request_hash),
            "revision": int(self.revision),
            "confidence": float(self.confidence),
            "consent_id": str(self.consent_id),
            "issued_at": float(self.issued_at),
            "expires_at": float(self.expires_at),
            "query_verdicts": [bool(v) for v in self.query_verdicts],
        }


@dataclass(frozen=True)
class PlanCheck:
    """One validation answer: accepted, or rejected with a typed code."""

    ok: bool
    code: str = ""
    reason: str = ""

    @classmethod
    def accept(cls) -> "PlanCheck":
        return cls(True)

    @classmethod
    def reject(cls, code: str, reason: str) -> "PlanCheck":
        return cls(False, code, reason)


@dataclass(frozen=True)
class PlanExecution:
    """What one execution actually did, including its call counts."""

    state: str
    plan_hash: str
    sources: Tuple[Dict[str, Any], ...] = ()
    search_calls: int = 0
    fetch_calls: int = 0
    queries_sent: Tuple[str, ...] = ()
    reason: str = ""

    def as_record(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "plan_hash": self.plan_hash,
            "search_calls": self.search_calls,
            "fetch_calls": self.fetch_calls,
            "queries_sent": list(self.queries_sent),
            "sources": [dict(s) for s in self.sources],
            "reason": self.reason,
        }


# ---- request binding and untrusted context --------------------------------

_FENCE_RE = re.compile(r"```.*?```", re.S)
_BLOCKQUOTE_RE = re.compile(r"(?m)^[ \t]*>.*$")
_QUOTED_SPAN_RE = re.compile(r'"[^"\n]{12,}"|(?<!\w)\'[^\'\n]{12,}\'(?!\w)')


def _quoted_regions(prompt: str) -> List[str]:
    text = prompt or ""
    return ([m.group(0) for m in _FENCE_RE.finditer(text)]
            + [m.group(0) for m in _BLOCKQUOTE_RE.finditer(text)]
            + [m.group(0) for m in _QUOTED_SPAN_RE.finditer(text)])


def quoted_context(prompt: str) -> str:
    """The prompt's untrusted region: quoted logs, traces, code, gate prose."""
    return "\n".join(_quoted_regions(prompt))


def goal_from_prompt(prompt: str) -> str:
    """The effective research goal, with the untrusted region removed.

    A quoted process log, a pasted trace, a fenced code block or a block
    quotation is context the request carries, not a statement of what to
    research. Removing it here keeps that text out of the goal even when a
    caller hands the raw prompt to a heuristic.
    """
    text = _FENCE_RE.sub(" ", prompt or "")
    text = _BLOCKQUOTE_RE.sub(" ", text)
    text = _QUOTED_SPAN_RE.sub(" ", text)
    return " ".join(text.split())


def request_hash_for(request_id: str, prompt: str) -> str:
    """The identity a plan is bound to: this request, verbatim."""
    return _hash({"request_id": str(request_id or ""),
                  "prompt": str(prompt or "")})


def only_quoted(text: str, prompt: str) -> bool:
    """Is ``text`` present only inside the prompt's untrusted region?"""
    needle = " ".join(str(text or "").split()).lower()
    if not needle:
        return False
    goal = goal_from_prompt(prompt).lower()
    if needle in goal:
        return False
    return needle in quoted_context(prompt).lower()


def _hash(payload: Dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ---- validation ------------------------------------------------------------

def _capability_set(capabilities: Iterable[str]) -> FrozenSet[str]:
    return frozenset(str(c).strip().lower() for c in capabilities if str(c).strip())


def _query_check(plan: ResearchPlan, prompt: str) -> PlanCheck:
    if not plan.queries:
        return PlanCheck.reject("no_queries", "the plan proposes no retrieval")
    if len(plan.queries) > MAX_PLAN_QUERIES:
        return PlanCheck.reject(
            "budget", f"{len(plan.queries)} queries exceeds {MAX_PLAN_QUERIES}")
    seen_ids = set()
    seen_texts = set()
    for index, query in enumerate(plan.queries):
        qid = str(query.query_id or "").strip()
        text = " ".join(str(query.query or "").split())
        if not qid:
            return PlanCheck.reject(
                "query_id_missing", f"query {index} has no id")
        if qid in seen_ids:
            return PlanCheck.reject(
                "query_id_duplicate", f"query id {qid!r} appears twice")
        seen_ids.add(qid)
        if len(text) < MIN_QUERY_CHARS or len(text) > MAX_QUERY_CHARS:
            return PlanCheck.reject(
                "query_text", f"query {qid!r} is outside the length band")
        if not str(query.purpose or "").strip():
            return PlanCheck.reject(
                "query_purpose", f"query {qid!r} has no purpose")
        key = query.url or text
        if key in seen_texts:
            return PlanCheck.reject(
                "query_duplicate", f"retrieval {key!r} appears twice")
        seen_texts.add(key)
        if only_quoted(text, prompt) or (
                query.url and only_quoted(query.url, prompt)):
            # A quoted trace or gate phrase is not search intent.
            return PlanCheck.reject(
                "quoted_context",
                f"query {qid!r} comes only from quoted context")
    return PlanCheck.accept()


def _budget_check(plan: ResearchPlan) -> PlanCheck:
    if not 1 <= int(plan.max_results) <= MAX_RESULTS:
        return PlanCheck.reject("budget", "max_results is outside the band")
    if not 1 <= int(plan.max_sources) <= MAX_SOURCES:
        return PlanCheck.reject("budget", "max_sources is outside the band")
    if not 0.0 < float(plan.timeout_s) <= MAX_TIMEOUT_S:
        return PlanCheck.reject("budget", "timeout_s is outside the band")
    if int(plan.max_tokens) < 0 or float(plan.max_spend_usd) < 0.0:
        return PlanCheck.reject("budget", "a declared limit is negative")
    return PlanCheck.accept()


def validate_plan(plan: Optional[ResearchPlan], *,
                  request_id: str,
                  prompt: str,
                  capabilities: Iterable[str] = (),
                  approval: Optional[PlanApproval] = None,
                  now: Optional[float] = None) -> PlanCheck:
    """Validate a plan, its request binding, its capability set and approval.

    Returns :class:`PlanCheck`; the first failing condition wins and its code
    names the rule. Callers execute nothing unless this accepts.
    """
    if now is None:
        now = time.time()
    if plan is None:
        return PlanCheck.reject("plan_missing", "no research plan was supplied")
    if int(plan.schema_version) != SCHEMA_VERSION:
        return PlanCheck.reject(
            "schema_version",
            f"plan schema {plan.schema_version} is not {SCHEMA_VERSION}")
    if not str(plan.goal or "").strip():
        return PlanCheck.reject("no_goal", "the plan has no effective goal")
    if str(plan.fallback_policy or "") != FALLBACK_NONE:
        # Only an exact approved action may reach the provider.
        return PlanCheck.reject(
            "fallback_policy",
            "a plan must declare no silent fallback")
    if not plan.freshness.strip():
        return PlanCheck.reject("no_freshness", "the plan declares no freshness")
    if not plan.evidence_requirements:
        return PlanCheck.reject(
            "no_evidence_requirements",
            "the plan declares no evidence requirements")
    if int(plan.revision) < 0 or int(plan.revision) > MAX_PLAN_REVISIONS:
        return PlanCheck.reject(
            "revision", f"revision {plan.revision} exceeds {MAX_PLAN_REVISIONS}")
    check = _query_check(plan, prompt)
    if not check.ok:
        return check
    check = _budget_check(plan)
    if not check.ok:
        return check
    if str(plan.request_id or "") != str(request_id or ""):
        return PlanCheck.reject(
            "request_mismatch", "the plan belongs to another request")
    if str(plan.request_hash or "") != request_hash_for(request_id, prompt):
        return PlanCheck.reject(
            "request_hash", "the plan was not built for this request text")
    available = _capability_set(capabilities)
    declared = _capability_set(plan.capabilities)
    missing = sorted(
        {q.kind for q in plan.queries} - available)
    if missing:
        return PlanCheck.reject(
            "capability_missing",
            "the request lane cannot " + "/".join(missing))
    undeclared = sorted({q.kind for q in plan.queries} - declared)
    if undeclared:
        return PlanCheck.reject(
            "capability_undeclared",
            "the plan does not declare " + "/".join(undeclared))
    if approval is None:
        return PlanCheck.reject("approval_missing", "the plan is not approved")
    return _approval_check(plan, approval, now=now)


def _approval_check(plan: ResearchPlan, approval: PlanApproval, *,
                    now: Optional[float]) -> PlanCheck:
    if now is None:
        now = time.time()
    if not approval.native:
        # An advisory or local preview is not an approval.
        return PlanCheck.reject(
            "approval_not_native", "the approval is not a native judgment")
    if str(approval.decision or "") != DECISION_ACCEPT:
        return PlanCheck.reject(
            "approval_declined",
            f"the native decision was {approval.decision or 'missing'}")
    if str(approval.plan_hash or "") != plan.hash():
        return PlanCheck.reject(
            "approval_hash", "the approval judges a different plan")
    if str(approval.request_hash or "") != str(plan.request_hash or ""):
        return PlanCheck.reject(
            "approval_request", "the approval belongs to another request")
    if int(approval.revision) != int(plan.revision):
        return PlanCheck.reject(
            "approval_revision", "the approval judges another revision")
    if len(approval.query_verdicts) != len(plan.queries) or not all(
            approval.query_verdicts):
        return PlanCheck.reject(
            "approval_incomplete", "the approval does not accept every query")
    if approval.expires_at and float(now) >= float(
            approval.expires_at):
        # Consent is request-scoped and does not outlive the turn.
        return PlanCheck.reject(
            "consent_stale", "the approval has expired")
    return PlanCheck.accept()


def saved_plan_approval(
        plan: Optional[ResearchPlan], *,
        plan_hash: Any = "", receipt: Any = None
) -> Optional[PlanApproval]:
    """Rebuild the recorded accepting receipt for this exact live plan.

    #344 names valid resume as not replaying billed retrieval or reassigning
    an old judgment: a resumed turn whose plan is byte-identical to the one a
    native judgment accepted may adopt that recorded receipt instead of paying
    for a second review. Only an exact match may be adopted -- same plan hash,
    same request hash, same revision and an ``accept`` that was native -- so a
    changed plan, a changed request, an unrecorded plan or a decline returns
    ``None`` and the caller asks again.

    This rebuilds the *recorded* receipt; it never manufactures one. Expiry is
    preserved, so :func:`validate_plan` still rejects an out-of-date consent.
    """
    if plan is None or not isinstance(receipt, dict) or not receipt:
        return None
    recorded = str(plan_hash or "")
    if not recorded or recorded != plan.hash():
        return None
    if not bool(receipt.get("native")):
        return None
    if str(receipt.get("decision") or "") != DECISION_ACCEPT:
        return None
    if str(receipt.get("plan_hash") or "") != recorded:
        return None
    if str(receipt.get("request_hash") or "") != str(plan.request_hash or ""):
        return None
    try:
        revision = int(receipt.get("revision") or 0)
    except (TypeError, ValueError):
        return None
    if revision != int(plan.revision):
        return None
    verdicts = receipt.get("query_verdicts")
    return PlanApproval(
        decision=DECISION_ACCEPT,
        native=True,
        plan_hash=recorded,
        request_hash=str(plan.request_hash or ""),
        revision=revision,
        confidence=float(receipt.get("confidence") or 0.0),
        consent_id=str(receipt.get("consent_id") or ""),
        issued_at=float(receipt.get("issued_at") or 0.0),
        expires_at=float(receipt.get("expires_at") or 0.0),
        query_verdicts=tuple(bool(v) for v in (verdicts or ())),
    )


def approval_from_judgment(plan: ResearchPlan, judgment: Dict[str, Any],
                           *, consent_id: str = "", issued_at: float = 0.0,
                           expires_at: float = 0.0) -> PlanApproval:
    """Turn one native structural judgment into the code-owned receipt.

    ``judgment`` is the structural envelope from
    :meth:`JevPolicy.evaluate_research_plan`. Only a native ``accept`` with a
    complete per-query relevance set becomes an accepting approval; everything
    else is carried through as a declining approval so the reason is recorded.
    """
    decision = str(judgment.get("decision") or DECISION_UNAVAILABLE)
    verdicts = tuple(bool(v) for v in (judgment.get("query_verdicts") or []))
    native = bool(judgment.get("native"))
    # Preserve the binding fields from the judgment rather than restamping
    # them from the supplied plan, so a judgment for one plan cannot be
    # used to authorize a different plan (#80).
    plan_hash = str(judgment.get("plan_hash") or plan.hash())
    request_hash = str(judgment.get("request_hash") or plan.request_hash)
    try:
        revision = int(judgment.get("revision") or plan.revision)
    except (TypeError, ValueError):
        revision = int(plan.revision)
    return PlanApproval(
        decision=decision if native else DECISION_UNAVAILABLE,
        native=native,
        plan_hash=plan_hash,
        request_hash=request_hash,
        revision=revision,
        confidence=float(judgment.get("confidence") or 0.0),
        consent_id=str(consent_id or ""),
        issued_at=float(issued_at or 0.0),
        expires_at=float(expires_at or 0.0),
        query_verdicts=verdicts,
    )


# ---- proposal (a heuristic draft; never approval) ---------------------------

PROPOSED_MAX_QUERIES = 2
PROPOSED_GOAL_CHARS = 600
PROPOSED_FRESHNESS = "current"
PROPOSED_EVIDENCE = ("readable text that answers the stated goal",)
_TRAILING_PUNCT = ".,;:!?"
_URL_RE = re.compile(r"https?://[^\s<>\"'`)\]]+", re.I)


def goal_urls(goal: str) -> List[str]:
    """The exact URLs named by the effective goal, in order, de-duplicated.

    Callers pass :func:`goal_from_prompt` output, so a URL that only appears
    inside a quoted log or a fenced block is not named by the goal and never
    reaches a plan.
    """
    seen: set = set()
    urls: List[str] = []
    for match in _URL_RE.finditer(goal or ""):
        url = match.group(0).rstrip(_TRAILING_PUNCT)
        if not url or url.lower() in seen:
            continue
        seen.add(url.lower())
        urls.append(url)
    return urls


def propose_plan(prompt: str, *, request_id: str,
                 capabilities: Iterable[str] = ("search", "fetch"),
                 max_queries: int = PROPOSED_MAX_QUERIES,
                 freshness: str = PROPOSED_FRESHNESS,
                 evidence_requirements: Sequence[str] = ()
                 ) -> Tuple[Optional[ResearchPlan], str]:
    """Draft a bounded plan from the effective goal.

    This is the *proposal* half of #342 and nothing more: it derives the goal,
    the exact named URLs (or one search query), the capability set those
    actions need, and the declared limits. It can never approve retrieval --
    only a native judgment passed through :func:`approval_from_judgment` can.

    Returns ``(plan, "")`` or ``(None, why_not)``; the reason names the
    condition that stopped the draft.
    """
    goal = goal_from_prompt(prompt)
    if len(goal.strip()) < MIN_QUERY_CHARS:
        return None, "goal_too_short"
    available = _capability_set(capabilities)
    if not available:
        return None, "capability_unavailable"
    queries: List[PlanQuery] = []
    for index, url in enumerate(goal_urls(goal)[:max_queries], start=1):
        if "fetch" not in available:
            return None, "capability_missing"
        queries.append(PlanQuery(
            query_id=f"q{index}", query=url, url=url,
            purpose="read the page the request names"))
    if not queries:
        if "search" not in available:
            return None, "capability_missing"
        queries.append(PlanQuery(
            query_id="q1", query=goal[:MAX_QUERY_CHARS].strip(),
            purpose="find current information for the goal"))
    return ResearchPlan(
        goal=goal[:PROPOSED_GOAL_CHARS],
        request_id=str(request_id or ""),
        request_hash=request_hash_for(request_id, prompt),
        queries=tuple(queries),
        freshness=str(freshness or PROPOSED_FRESHNESS),
        evidence_requirements=tuple(
            evidence_requirements or PROPOSED_EVIDENCE),
        capabilities=tuple(sorted({q.kind for q in queries})),
    ), ""


def decide_research_plan(
        prompt: str, *, policy: Any, request_id: str,
        task_id: Optional[str] = None, now: Optional[float] = None,
        capabilities: Sequence[str] = ("search", "fetch"),
        saved_plan: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[ResearchPlan], Optional[PlanApproval], Dict[str, Any]]:
    """Propose one plan and band one native judgment on it.

    Every request entrypoint that can reach the network calls this one owner
    (#342) instead of proposing and judging separately. The proposal is a
    heuristic and authorizes nothing. Only ``policy.evaluate_research_plan``
    can approve, and only a plan that both that judgment and
    :func:`validate_plan` accept returns an approval. A missing callable, an
    unkeyed reviewer, a decline or an invalid answer returns ``None`` for the
    approval, which is what keeps every network path closed.

    Returns ``(plan, approval, record)``; ``record`` is the gate's account of
    what happened and is what a lane persists for audit.
    """
    # Resolve omitted now so consent expiry is always enforced, even when the
    # caller (or a saved-receipt resume) omits an explicit timestamp.
    if now is None:
        now = time.time()
    proposal, why = propose_plan(
        prompt, request_id=request_id, capabilities=capabilities)
    plan_hash = proposal.hash() if proposal is not None else ""
    active_caps = sorted(_capability_set(capabilities))
    record: Dict[str, Any] = {
        "source": "research_plan_gate",
        "proposed": proposal is not None,
        "plan_hash": plan_hash,
        "request_hash": (proposal.request_hash
                         if proposal is not None else ""),
        "state": ("capability_unavailable"
                  if why == "capability_unavailable" else "invalid"),
        "native": False,
        "decision": "",
        "reason": why or "",
        "cost": 0.0,
        "active_capabilities": active_caps,
        "capability_unavailable": why == "capability_unavailable",
        "search_calls": 0,
        "fetch_calls": 0,
    }
    if proposal is None:
        emit("research_plan_gate", phase="blocked", code=why,
             capabilities=active_caps)
        return None, None, record
    record.update({
        "goal": proposal.goal,
        "queries": [
            {"query_id": q.query_id, "query": q.query,
             "purpose": q.purpose, "url": q.url, "kind": q.kind}
            for q in proposal.queries
        ],
        "target_domains": list(proposal.domains),
        "freshness": proposal.freshness,
        "evidence_requirements": list(proposal.evidence_requirements),
        "max_results": int(proposal.max_results),
    })
    if saved_plan:
        # #344: an identical plan that a native judgment already accepted does
        # not need a second billed review. The adoption still passes through
        # validate_plan below, so an expired receipt or a drifted request
        # binding falls back to a fresh judgment rather than riding in.
        reused = saved_plan_approval(
            proposal,
            plan_hash=saved_plan.get("plan_hash"),
            receipt=saved_plan.get("receipt"))
        if reused is not None:
            check = validate_plan(
                proposal, request_id=request_id, prompt=prompt,
                capabilities=capabilities, approval=reused, now=now)
            if check.ok:
                record.update({
                    "state": "accepted", "native": True,
                    "decision": reused.decision, "reason": "",
                    "cost": 0.0, "reused": True,
                    "consent_id": str(reused.consent_id or ""),
                })
                emit("research_plan_gate", phase="accepted", code="",
                     plan_hash=plan_hash, native=True,
                     decision=reused.decision, reused=True,
                     capabilities=active_caps)
                return proposal, reused, record
            record["reuse_reason"] = f"{check.code}: {check.reason}"
            emit("research_plan_gate", phase="reuse-rejected",
                 code=check.code, plan_hash=plan_hash,
                 capabilities=active_caps)
    evaluate = getattr(policy, "evaluate_research_plan", None)
    if not callable(evaluate):
        record.update(state="unavailable", reason="policy_missing")
        emit("research_plan_gate", phase="blocked", code="policy_missing",
             capabilities=active_caps)
        return proposal, None, record
    try:
        _result, structural = evaluate(
            proposal.payload(), plan_hash=plan_hash,
            request_hash=proposal.request_hash,
            revision=proposal.revision, task_id=task_id)
    except ToolCancelled:
        raise
    except ProviderUsageUnknown:
        raise
    except Exception as exc:  # a reviewer outage never authorizes retrieval
        record.update(state="unavailable",
                      reason=f"reviewer_error: {type(exc).__name__}")
        emit("research_plan_gate", phase="blocked", code="reviewer_error",
             capabilities=active_caps)
        return proposal, None, record
    structural = structural if isinstance(structural, dict) else {}
    approval = approval_from_judgment(
        proposal, structural,
        consent_id=f"{request_id}:research-plan",
        issued_at=float(now if now is not None else time.time()))
    check = validate_plan(
        proposal, request_id=request_id, prompt=prompt,
        capabilities=capabilities, approval=approval, now=now)
    accepted = bool(check.ok)
    record.update({
        "decision": str(approval.decision or ""),
        "native": bool(approval.native),
        "state": "accepted" if accepted else "declined",
        "reason": "" if accepted else f"{check.code}: {check.reason}",
        "cost": float(structural.get("cost") or 0.0),
        "jev_model": str(structural.get("model")
                         or getattr(_result, "model", "") or ""),
        "jev_verdict": str(structural.get("verdict")
                           or getattr(_result, "verdict", "") or ""),
        "consent_id": str(approval.consent_id or ""),
    })
    emit("research_plan_gate",
         phase=("accepted" if accepted else "blocked"),
         code="" if accepted else check.code, plan_hash=plan_hash,
         native=bool(approval.native), decision=record["decision"],
         capabilities=active_caps)
    return proposal, (approval if accepted else None), record


def _url_identity(url: str) -> str:
    return str(url or "").strip().rstrip("/").lower()


def plan_authorizes_url(plan: Optional[ResearchPlan], url: str) -> bool:
    """Does this plan name ``url`` as one exact action it proposes?

    The direct browser renderer is a network path of its own (#342/#426): it
    runs only for a URL an accepted plan already names, never for a URL a
    heuristic extracted.
    """
    if plan is None:
        return False
    key = _url_identity(url)
    if not key:
        return False
    return any(q.url and _url_identity(q.url) == key for q in plan.queries)


# ---- bounded execution -----------------------------------------------------

def execute_plan(plan: Optional[ResearchPlan],
                 approval: Optional[PlanApproval], *,
                 request_id: str,
                 prompt: str,
                 capabilities: Iterable[str],
                 search_fn=None,
                 fetch_fn=None,
                 now: Optional[float] = None) -> PlanExecution:
    """Run exactly the accepted plan, and nothing when it is not accepted.

    The only query string sent to the provider is ``query.query`` as approved;
    the only URL fetched is ``query.url``. A fetch that returns no text ends
    the run with insufficient evidence -- never a derived search.
    """
    plan_hash = plan.hash() if plan is not None else ""
    check = validate_plan(
        plan, request_id=request_id, prompt=prompt,
        capabilities=capabilities, approval=approval, now=now)
    if not check.ok:
        declined = ("approval_", "consent_", "request_mismatch",
                    "request_hash")
        invalid = ("schema_version", "no_goal", "no_freshness",
                   "no_evidence_requirements", "query_id_missing",
                   "query_id_duplicate", "query_text", "query_purpose",
                   "query_duplicate")
        state = (STATE_UNAVAILABLE
                 if check.code == "approval_not_native" else
                 STATE_DECLINED
                 if check.code.startswith(declined) else
                 STATE_INVALID if check.code in invalid else
                 STATE_UNAVAILABLE)
        return PlanExecution(state=state, plan_hash=plan_hash,
                             reason=f"{check.code}: {check.reason}")
    sources: List[Dict[str, Any]] = []
    sent: List[str] = []
    searches = 0
    fetches = 0
    for query in plan.queries:
        if query.url:
            fetches += 1
            sent.append(query.url)
            source = _fetch_source(fetch_fn, query.url)
            sources.append(source)
            continue
        searches += 1
        sent.append(query.query)
        sources.extend(_search_sources(
            search_fn, query.query, max_results=int(plan.max_results)))
    # Enforce the accepted plan's aggregate source budget (#82).
    limit = int(getattr(plan, "max_sources", len(sources)) or len(sources))
    if limit > 0 and len(sources) > limit:
        sources = sources[:limit]
    usable = any(s.get("ok") and str(s.get("text") or "").strip()
                 for s in sources)
    if not usable and fetches and not searches:
        # A plan naming pages only: a zero-text page is honest insufficient
        # evidence, never a reason to derive a query and search instead.
        return PlanExecution(
            state=INSUFFICIENT, plan_hash=plan_hash,
            sources=tuple(sources), search_calls=searches,
            fetch_calls=fetches, queries_sent=tuple(sent),
            reason="every accepted page returned no readable text")
    return PlanExecution(
        state=EXECUTED, plan_hash=plan_hash, sources=tuple(sources),
        search_calls=searches, fetch_calls=fetches,
        queries_sent=tuple(sent))


def _fetch_source(fetch_fn, url: str) -> Dict[str, Any]:
    if not callable(fetch_fn):
        return {"kind": "fetch", "ok": False, "url": url,
                "note": "no fetch capability attached"}
    try:
        page = fetch_fn(url)
    except HarnessError as exc:
        return {"kind": "fetch", "ok": False, "url": url, "note": str(exc)}
    body = str((page or {}).get("text") or "")
    if not body.strip():
        return {"kind": "fetch", "ok": False,
                "url": (page or {}).get("url") or url,
                "title": (page or {}).get("title") or "",
                "note": "empty page (0 chars)"}
    return {"kind": "fetch", "ok": True, "evidence": "rendered", "pinned": True,
            "url": (page or {}).get("url") or url,
            "title": (page or {}).get("title") or "", "text": body}


def _search_sources(search_fn, query: str, *,
                    max_results: int) -> List[Dict[str, Any]]:
    if not callable(search_fn):
        return [{"kind": "search", "ok": False,
                 "note": "no search capability attached"}]
    try:
        results = search_fn(query) or []
    except HarnessError as exc:
        return [{"kind": "search", "ok": False, "note": str(exc)}]
    out: List[Dict[str, Any]] = []
    for result in list(results)[:max_results]:
        out.append({"kind": "search", "ok": True, "evidence": "snippet",
                    "url": str((result or {}).get("url") or ""),
                    "title": str((result or {}).get("title") or ""),
                    "text": str((result or {}).get("snippet") or "")})
    if not out:
        return [{"kind": "search", "ok": False,
                 "note": "search returned no results"}]
    return out


def approved_queries(plan: ResearchPlan) -> Sequence[PlanQuery]:
    """The exact actions an accepted plan authorizes, in order."""
    return tuple(plan.queries)


__all__ = [
    "CAPABILITIES",
    "EXECUTED",
    "FALLBACK_NONE",
    "INSUFFICIENT",
    "MAX_PLAN_QUERIES",
    "MAX_PLAN_REVISIONS",
    "DECISION_ACCEPT",
    "DECISION_DECLINE",
    "DECISION_INVALID",
    "DECISION_REVISE",
    "DECISION_UNAVAILABLE",
    "STATE_DECLINED",
    "STATE_INVALID",
    "STATE_UNAVAILABLE",
    "PlanApproval",
    "PlanCheck",
    "PlanExecution",
    "PlanQuery",
    "ResearchPlan",
    "SCHEMA_VERSION",
    "approval_from_judgment",
    "approved_queries",
    "decide_research_plan",
    "execute_plan",
    "goal_from_prompt",
    "goal_urls",
    "only_quoted",
    "plan_authorizes_url",
    "propose_plan",
    "saved_plan_approval",
    "quoted_context",
    "request_hash_for",
    "validate_plan",
]
