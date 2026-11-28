"""Conversational fallback generation and web evidence handling."""

import re
from contextlib import contextmanager
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from .chat import assess_output, chat_routed, extract_content_and_cost, looks_truncated
from .chat_policy import (
    DEFAULT_CHAT_SYSTEM_PROMPT,
    _MAX_WEB_CONTEXT_CHARS,
    _MAX_WEB_SOURCES,
    _NO_WEB_DISCLOSURE,
    _SCRIPT_CAPABILITY_NOTE,
    _UNTRUSTED_SCRIPT_NOTE,
    _EVIDENCE_LEGEND,
    _WEB_CAPABILITY_NOTE,
)
from . import script as _script
from .config import Settings, effective_lane_policy
from .conversation_context import (
    assemble_history,
    facts_block,
    load_memory,
    needs_earlier_context,
    policy_recall_judge,
)
from .errors import HarnessError, ToolCancelled
from .events import emit
from .history import load_chat_history, save_chat_turn
from .lifecycle_types import LifecycleState
from .prompts import CAPABILITY_MARKER
from .research_plan import decide_research_plan
from .results import _http_error
from .session import governor_for, ledger_for
from .token_budget import resolve_lane_max_tokens as _resolve_lane_max_tokens
from .web import (
    apply_result_review,
    gather_web_context,
    named_target_hosts,
    resolve_fetch_allowlist,
    source_label,
)


# #342: a withheld retrieval is disclosed as exactly that. The plain
# no-web disclosure would be false here -- the tools exist, the plan was not
# accepted -- and the model must not narrate a search that never ran.
_WEB_PLAN_WITHHELD_NOTE = (
    "WEB RETRIEVAL WITHHELD: no accepted research plan for this request "
    "({reason}). You have no web results this turn; do not claim to have "
    "searched or fetched anything."
)


class ConversationLifecycleMixin:
    """Own one-shot conversational fallback behavior."""

    _REFUSAL_RE = re.compile(
        r"\b(?:i can(?:'t|not)|i'?m unable|unable to|i have no access|"
        r"i (?:do not|don't) have (?:access|tools|internet|a browser|file|compute))\b",
        re.IGNORECASE,
    )
    # A capability caveat is only a deferral when it IS the answer (#543).
    # A turn that says "I can't generate an image, but here is the scale you
    # asked for ..." and then delivers the scale completed the request; the
    # caveat belongs in the answer body. The line between the two is how much
    # substance the turn carries outside the caveat sentence: below this many
    # words it is a deferral with padding, at or above it the user got an
    # answer. Stated as a constant so the tradeoff is visible and testable
    # rather than buried in a regex.
    _REFUSAL_SUBSTANCE_WORDS = 40

    # #705: the chat lane and the plan lane may hand a request back and forth
    # (a defer escalates, a refusal is explained conversationally), and every
    # such handoff is a fresh entry into a handler that can hand off again.
    # Worth keeping: one escalation plus the refusal's answer. Not worth
    # keeping: the same pair re-entering forever, which is what looped a live
    # GUI session until the operator cancelled it. The budget is per request:
    # the request's own entry is depth 0.
    _HANDLER_HANDOFF_LIMIT = 3

    def _handler_handoff_depth(self) -> int:
        return int(getattr(self, "_handler_handoff_depth_value", 0) or 0)

    def _handler_handoff_allowed(self) -> bool:
        return self._handler_handoff_depth() < self._HANDLER_HANDOFF_LIMIT

    def _handoff_suppressed(self, target: str,
                            reason: Optional[str] = None) -> bool:
        """True when the budget is spent; records the skipped handoff."""
        if self._handler_handoff_allowed():
            return False
        emit("handler_handoff_suppressed", target=target,
             depth=self._handler_handoff_depth(), reason=reason)
        return True

    @contextmanager
    def _handler_handoff(self):
        """Count one handler-to-handler handoff; restore the depth on exit."""
        depth = self._handler_handoff_depth()
        self._handler_handoff_depth_value = depth + 1
        try:
            yield
        finally:
            if depth:
                self._handler_handoff_depth_value = depth
            else:
                try:
                    del self._handler_handoff_depth_value
                except AttributeError:
                    pass

    def _handle_conversation(
        self,
        prompt: str,
        session_id: str,
        cancel_check: Optional[Callable[[], bool]] = None,
        web: bool = False,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
        token_budget: Optional[Any] = None,
        lifecycle_state: Optional[LifecycleState] = None,
        untrusted_evidence: Optional[str] = None,
        propose_scripts: Optional[bool] = None,
        allow_escalation: bool = True,
        persist: bool = True,
    ) -> Dict[str, Any]:
        # Handle informational or technical questions with conversational routing
        api_key, gov = governor_for(self.settings)
        target_tokens, lane_effort = effective_lane_policy(
            "chat", max_tokens=max_tokens, reasoning_effort=reasoning_effort
        )

        # A proposal turn is one model reply plus a consent card; the lane
        # owns that shape so history saves one turn instead of an answer and a
        # duplicate proposal. A follow-up answer disables the capability.
        wants_proposals = (getattr(self, "script_proposals", False)
                           if propose_scripts is None else propose_scripts)
        system_prompt = DEFAULT_CHAT_SYSTEM_PROMPT
        if wants_proposals:
            system_prompt += "\n\n" + _SCRIPT_CAPABILITY_NOTE
        web_sources: List[Dict[str, Any]] = []
        web_review_cost = 0.0
        plan_record: Optional[Dict[str, Any]] = None
        if web:
            if cancel_check and cancel_check():
                raise ToolCancelled("Prompt execution was cancelled by user")
            named_hosts = named_target_hosts(prompt)
            web_policy = None
            try:
                from .jev_policy import policy_for as _policy_for
                web_policy = _policy_for(
                    self.settings, governor=gov,
                    ledger=ledger_for(self.settings, caller="agent"))
            except Exception as exc:  # reviewer setup must not kill the chat
                emit("web_result_review_unavailable",
                     reason=type(exc).__name__)
            # #342: the web flag grants capability, never approval. One plan is
            # proposed here and native Jev judges it exactly once; only a plan
            # validate_plan accepts may search or fetch. A missing reviewer, an
            # unkeyed one, a decline or an invalid answer leaves both at zero.
            request_id = str(
                (lifecycle_state or {}).get("request_id") or "") or (
                f"chat:{session_id}:{uuid4().hex}")
            plan, approval, plan_record = decide_research_plan(
                prompt, policy=web_policy, request_id=request_id,
                task_id=session_id)
            if approval is None:
                system_prompt += "\n\n" + _WEB_PLAN_WITHHELD_NOTE.format(
                    reason=(plan_record.get("reason")
                            or plan_record.get("state") or "declined"))
            else:
                try:
                    web_sources = self._gather_web_context(
                        prompt, named_hosts, jev_policy=web_policy,
                        task_id=session_id, plan=plan, approval=approval,
                        request_id=request_id)
                    web_review_cost = float(
                        getattr(web_sources, "cost", 0.0) or 0.0)
                except ToolCancelled:
                    raise
                except Exception as e:  # web tools must never kill the chat
                    web_sources = [{"kind": "web", "ok": False,
                                    "note": f"web tools error: {e}"}]
                _allowed, _any = resolve_fetch_allowlist(self.settings)
                if _any:
                    hosts = "any public website (SSRF-guarded)"
                else:
                    hosts = ", ".join(sorted(_allowed)) or "(none configured)"
                system_prompt += "\n\n" + _WEB_CAPABILITY_NOTE.format(
                    hosts=hosts)
                context_lines = []
                for s in web_sources:
                    if s.get("kind") == "reviewer":
                        # #660 line 1: the evidence block discloses a reviewer
                        # outage, so withheld results never read as absence.
                        context_lines.append(
                            "EVIDENCE REVIEW: "
                            + str(s.get("note") or "results withheld"))
                        continue
                    if s.get("ok"):
                        body = (s.get("text") or "")[:_MAX_WEB_CONTEXT_CHARS]
                        context_lines.append(
                            f"SOURCE ({source_label(s)}): {s.get('title') or ''} {s['url']}\n{body}"
                        )
                    else:
                        context_lines.append(
                            f"SOURCE ({s['kind']}) FAILED: {s.get('url') or ''} {s.get('note')}"
                        )
                if context_lines:
                    system_prompt += (
                        "\n\n[Web tool results for this turn -- cite only these; do not invent others. "
                        + _EVIDENCE_LEGEND + "]\n"
                        + "\n\n".join(context_lines)
                    )
        else:
            system_prompt += "\n\n" + _NO_WEB_DISCLOSURE
        if untrusted_evidence:
            # Evidence produced by the approved script is attached at the
            # system level, delimited and labeled as data. It is never merged
            # into the user message or treated as instructions.
            system_prompt += "\n\n" + _UNTRUSTED_SCRIPT_NOTE + "\n\n" + untrusted_evidence

        messages = [{"role": "system", "content": system_prompt}]
        turns = load_chat_history(session_id, self.history_dir)
        # History is budget-driven, never count-capped: the lane's own token
        # allowance sets the room, so a larger lane (or a later policy) admits
        # more context without editing a constant in this file.
        history_budget = max(0, int(target_tokens) * 4)
        memory = load_memory(self.history_dir)
        remembered = facts_block(
            memory, budget_chars=max(0, history_budget // 2), focus=prompt)
        recent_text = "\n".join(
            f"User: {str(t.get('prompt') or '')[:240]}\n"
            f"Assistant: {str(t.get('response') or '')[:240]}"
            for t in turns[-2:]
        )
        recall = needs_earlier_context(
            prompt,
            judge=self._context_recall_judge(remembered, recent_text, gov, session_id),
        )
        past_messages = assemble_history(
            prompt, turns, budget_chars=history_budget,
            memory=memory, expand=recall.needed)
        fact_count = sum(1 for line in remembered.splitlines()
                         if line.startswith("- "))
        if remembered:
            messages.append({"role": "system", "content": remembered})
        messages.extend(past_messages)
        messages.append({"role": "user", "content": prompt})
        emit("chat_context", facts=fact_count,
             turns=sum(1 for m in past_messages if m["role"] == "user"),
             expanded=recall.needed, native=recall.native,
             reason=recall.reason)

        # One governed attempt per ladder rung (preflight -> chat -> bill, the
        # governed_text contract), advancing on HTTP failure or an unusable
        # body. The old code pinned one free model, ignored the status, and
        # rendered a fake apology on a 429; now every failure is recorded,
        # emitted as a rotation, and an all-rungs failure raises honestly.
        if lifecycle_state is not None:
            usage = lifecycle_state["usage"]
            known_cost = max(0.0, float(usage.get("known_cost") or 0.0))
            unknown_liability = max(
                0.0, float(usage.get("unknown_liability") or 0.0))
            if known_cost:
                gov.record_actual(
                    known_cost, "chat-continuation", lane="answer")
            if unknown_liability:
                gov.retain_unknown(
                    unknown_liability, "cancelled-chat-provider-call")
        answered = None
        attempts: List[str] = []
        # Longest cut-off body seen while every rung was failing: the raw
        # material for the honest truncation deferral.
        best_truncated: Optional[tuple] = None
        # #539: do not dispatch to a backend already known to be unservable;
        # #540 keeps the documented free-first posture on the answer ladder.
        from .availability import (
            default_ledger as _availability,
            failover_models as _failover_models,
        )

        _ledger = _availability()
        _prefer_free = bool(getattr(self.settings, "use_free", False))
        _local_pool = getattr(self.settings, "local_pool", None)
        configured_ladder = self._chat_ladder(self.settings)
        active_ladder = list(
            _failover_models(configured_ladder, _local_pool, prefer_free=_prefer_free)
            or _ledger.order(configured_ladder, prefer_free=_prefer_free)
        )
        _failover_extended = False
        for model in active_ladder:
            if (
                _failover_extended
                and model in configured_ladder
                and "/" in str(model)
                and _ledger.is_excluded(model)
            ):
                continue
            if cancel_check and cancel_check():
                raise ToolCancelled("Prompt execution was cancelled by user")
            note = None
            content, cost = None, 0.0
            allocated_tokens = _resolve_lane_max_tokens(
                gov, model, prompt, target_tokens, token_budget=token_budget
            )
            if allocated_tokens < 1:
                attempts.append(f"{model}: insufficient budget for output tokens")
                continue
            try:
                gov.preflight(prompt, [("chat", model, allocated_tokens, 0)])
                status, resp = chat_routed(
                    transport=self.transport,
                    api_key=api_key,
                    model=model,
                    messages=messages,
                    max_tokens=allocated_tokens,
                    reasoning_effort=lane_effort,
                    governor=gov,
                )
            except HarnessError as e:
                note = str(e)
                from .lifecycle_guards import (
                    classify_harness_error,
                    is_availability_failure,
                )

                _kind = classify_harness_error(note)
                if is_availability_failure(_kind):
                    from .availability import record_error

                    record_error(model, e, kind=_kind)
                    if not _failover_extended:
                        _extra = _failover_models(
                            configured_ladder, _local_pool, prefer_free=_prefer_free
                        )
                        if _extra:
                            _failover_extended = True
                            for _m in _extra:
                                if _m not in active_ladder:
                                    active_ladder.append(_m)
            else:
                if status != 200:
                    note = _http_error(status, resp)
                else:
                    content, finish_reason, cost, is_byok = extract_content_and_cost(resp)
                    if is_byok:
                        gov.record_byok(model)
                        note = (
                            f"response for {model} was BYOK-routed; "
                            "spend is not tracked on this key"
                        )
                    else:
                        # A billable-but-unusable completion is still billed
                        # (the provider charged for it); only usable content
                        # ends the walk.
                        if cost:
                            gov.record_actual(cost, model)
                        usable, why = assess_output(content, finish_reason)
                        if usable and looks_truncated(content):
                            # Providers do not always report finish_reason
                            # "length" honestly; an unbalanced fence/bracket
                            # body is cut regardless of what they claim.
                            usable, why = (
                                False,
                                ("response cut off mid-body (unbalanced code fence or brackets)"),
                            )
                        if not usable:
                            note = why
                            if (content or "").strip() and (
                                best_truncated is None or len(content) > len(best_truncated[1])
                            ):
                                best_truncated = (model, content, cost)
            if note is None:
                answered = (model, content or "", cost)
                _ledger.record_success(model)
                break
            attempts.append(f"{model}: {note}")
            emit("rotation", model=model, reason="chat_ladder_advance", note=note)
        if answered is None and best_truncated is not None:
            # Every rung failed, but one produced substantive cut-off
            # content: defer honestly, keeping the content. Rotating more
            # cannot finish a body that exceeds the output cap.
            model, response_text, cost = best_truncated
            defer_reason = (
                f"response truncated at the token cap on every "
                f"ladder model (max_tokens={target_tokens})"
            )
            marker_defer = False
            truncation_defer = True
        elif answered is None:
            raise HarnessError("chat failed on every ladder model: " + "; ".join(attempts))
        else:
            model, response_text, cost = answered
            defer_reason = None
            marker_defer = CAPABILITY_MARKER in response_text
            truncation_defer = False
        cost += web_review_cost

        # A marked script proposal is a consent gate, not an answer: capture it
        # before the refusal/deferral heuristics, so "I cannot scrape this from
        # memory, here is a script" does not get routed to the plan lane.
        if wants_proposals and not truncation_defer:
            draft = {"response": response_text, "model": model, "cost": cost}
            proposal = _script.proposal_turn(
                prompt, draft, root=self.root_dir,
                policy=_script.resolve_script_policy(self.settings),
                task_id=session_id or None)
            response_text = draft["response"]
            if proposal is not None:
                if persist:
                    save_chat_turn(session_id, proposal, self.history_dir)
                emit("chat_response", intent="script",
                     cost=proposal["cost"], model=proposal["model"])
                return proposal

        # The chat lane honors the same deferral contract as apply: a
        # HARNESS_DEFER marker is the model handing the decision back instead
        # of guessing. Free models usually defer in prose instead, so a
        # refusal-shaped answer with no successful tool evidence is treated
        # as the deferral it is; the model's own words become the reason.
        if marker_defer:
            head, _, tail = response_text.partition(CAPABILITY_MARKER)
            first_line = tail.strip().splitlines()[0].strip() if tail.strip() else ""
            defer_reason = (
                " ".join(first_line.split())[:200]
                or "request exceeds the conversation lane's capability"
            )
            # A bare marker (no prose before it) still owes the user visible
            # text in the saved turn; the UI banner carries the same reason.
            response_text = head.strip() or f"Deferred: {defer_reason}"
        elif defer_reason is None:
            did_work = bool(web_sources and any(s.get("ok") for s in web_sources))
            if not did_work:
                defer_reason = self._refusal_reason(response_text)
        if defer_reason is not None:
            next_step = (
                'route to the plan lane: harness plan --goal "..." '
                "--execute (or the MCP plan_and_execute tool)"
            )
            if best_truncated is not None and answered is None:
                next_step = (
                    'say "continue" to keep this going in the chat '
                    "lane, or route long-generation work to the plan "
                    'lane: harness plan --goal "..." --execute '
                    "(it has multi-round continuation)"
                )
            elif not marker_defer:
                next_step = (
                    "reframe within this lane (Q&A, small lookups), "
                    "enable web or adjust the fetch allowlist for "
                    "live data, or route real work to the plan lane: "
                    'harness plan --goal "..." --execute'
                )
            ledger_for(self.settings).append(
                "model_result",
                task_id=session_id or "(chat)",
                event_note="chat",
                status="deferred",
                category="capability",
                model=model,
                reason=defer_reason,
                cost=round(cost, 6),
            )
            # AUTO-ESCALATION: a capability defer with the paid key armed does
            # not stop at a handoff note -- the request routes itself into the
            # hourglass plan lane (frontier-planned DAG, governed apply with
            # paid escalation rungs). Truncation defers keep their "continue"
            # resume instead: the content already exists, it needs more room.
            if (not truncation_defer and allow_escalation
                    and self._auto_escalation_armed()
                    # #705: when the budget is spent the plan lane has already
                    # come back to this one; the defer text below is the
                    # honest answer for this turn.
                    and not self._handoff_suppressed("plan_lane", defer_reason)):
                emit("chat_escalated", reason=defer_reason, target="plan_lane")
                try:
                    with self._handler_handoff():
                        return self._handle_edit(
                            prompt,
                            session_id,
                            auto_apply=True,
                            cancel_check=cancel_check,
                            escalation_note=defer_reason,
                        )
                except HarnessError as e:
                    # The handoff failed (no routable target files, plan
                    # refusal, ...): the honest defer stands with the
                    # failure recorded -- never a silent swallow.
                    response_text += (
                        f"\n\n[auto-escalation to the plan lane failed: {e}]")

        result = {
            "status": "deferred" if defer_reason else "ok",
            "intent": "conversation",
            "prompt": prompt,
            "response": response_text,
            "model": model,
            "cost": round(cost, 6),
            **({"truncated": True} if truncation_defer else {}),
            **(
                {
                    "defer_reason": defer_reason,
                    # The resume hint a deferral owes the operator (render.py's
                    # contract): what to do instead of this lane's refusal.
                    "next_step": next_step,
                }
                if defer_reason
                else {}
            ),
            # Honest provenance: did this turn actually retrieve web evidence?
            "web_used": bool(web_sources and any(s.get("ok") for s in web_sources)),
            "web_sources": [
                {k: s[k] for k in ("kind", "ok", "url") if k in s} for s in web_sources
            ],
            **({"research_plan": dict(plan_record)} if plan_record else {}),
        }

        result["context"] = {
            "facts": fact_count,
            "turns": sum(1 for m in past_messages if m["role"] == "user"),
            "expanded": bool(recall.needed),
            "native": bool(recall.native),
            "reason": recall.reason,
        }
        if persist:
            save_chat_turn(session_id, result, self.history_dir)
        emit("chat_response", intent="conversation", cost=cost, model=model)
        return result

    def _context_recall_judge(self, remembered: str, recent: str, gov: Any,
                              session_id: str):
        """The Jev decision behind context expansion, or None when Jev cannot
        judge.  None leaves the deterministic referential fallback in charge;
        it never silently widens or narrows context."""
        if not remembered:
            return None
        try:
            from .jev_policy import policy_for

            policy = policy_for(self.settings, governor=gov)
        except Exception:  # noqa: BLE001 - absence of Jev is not a failure
            return None
        return policy_recall_judge(
            policy, remembered, recent,
            site="chat-context", task_id=session_id or "chat")

    def answer_from_script_output(self, prompt: str, evidence: str, *,
                                  session_id: Optional[str] = None,
                                  cancel_check=None) -> Dict[str, Any]:
        """Answer the original request from approved script output.

        One governed completion, with the output attached as untrusted system
        evidence. This is not persisted as its own chat turn (the run's turn
        owns it) and it cannot propose another script, so the approval loop
        cannot chain model turns into executions.
        """
        return self._handle_conversation(
            prompt, session_id or "script-followup",
            cancel_check=cancel_check, web=False,
            untrusted_evidence=evidence, propose_scripts=False,
            allow_escalation=False, persist=False)

    def _gather_web_context(self, prompt: str,
                            named_hosts=None, *, jev_policy=None,
                            task_id: Optional[str] = None,
                            plan=None, approval=None, request_id: str = ""
                            ) -> List[Dict[str, Any]]:
        # Web owns the network seams; pass those module functions through so
        # policy and hermetic test patches remain at the single owner.
        import harness.web as _web

        allowed, any_public = resolve_fetch_allowlist(self.settings)
        gathered = gather_web_context(
            prompt,
            allowed_hosts=allowed,
            allow_any_public=any_public,
            named_hosts=named_hosts or named_target_hosts(prompt),
            fetch_url_fn=_web.fetch_url,
            search_web_fn=_web.search_web,
            find_urls_fn=_web.find_urls,
            extract_query_fn=_web.extract_query,
            max_sources=_MAX_WEB_SOURCES,
            plan=plan,
            approval=approval,
            request_id=request_id,
        )
        # #660 line 1: ONE admission point for every retrieval path, so the
        # hourglass lane inheriting this method cannot drift from the chat lane.
        return apply_result_review(
            prompt, gathered, jev_policy, site="web-results", task_id=task_id)

    @staticmethod
    def _chat_ladder(settings: Settings) -> List[str]:
        # Single-owner ladder: delegate to router's chat-ladder helper
        # (harness/chat.py: chat_ladder) so panel/escalation policy isn't
        # duplicated between the agent and the router.
        from .chat import chat_ladder as _chat_ladder

        return _chat_ladder(settings)

    @classmethod
    def _refusal_reason(cls, response_text: str) -> Optional[str]:
        """The refusal sentence, when the turn is a deferral rather than an answer.

        Returns ``None`` when a refusal-shaped sentence sits inside delivered
        content: a completed answer may carry a capability caveat without
        being reported as Deferred (#543).
        """
        text = (response_text or "").strip()
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if not cls._REFUSAL_RE.search(sentence):
                continue
            rest = " ".join(text.replace(sentence, " ", 1).split())
            if len(rest.split()) >= cls._REFUSAL_SUBSTANCE_WORDS:
                return None
            return " ".join(sentence.split())[:200]
        return None
