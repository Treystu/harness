"""Plan-lane honesty guards (issues #204, #205, #206).

One owner so every lane reads the policy instead of re-deriving it:
#204 failure classification + per-run 429 circuit; #205 refusal-loop
guard + phase memo; #206 honest terminal rendering. Hermetic: no
network, no model calls (``clock`` is injectable). No pricing or pool
changes; paid failover untouched.
"""

import json
import time

# ---------------------------------------------------------------------------
# #204: provider-failure classification
# ---------------------------------------------------------------------------

RATE_LIMITED = "rate_limited"
SPEND_EXHAUSTED = "spend_exhausted"
BUDGET_REFUSED = "budget_refused"
AUTH_FAILED = "auth_failed"
MODEL_UNAVAILABLE = "model_unavailable"
UNKNOWN_FAILURE = "unknown"

#: Terminal failures: stop with no retry and no model rotation.
#:
#: Only the RUN's own budget cap is terminal (#538). A provider's spend limit
#: says nothing about the other configured backends, so treating it as
#: terminal deferred a request while funded backends sat unprobed. Provider
#: exhaustion now rotates (see ``AVAILABILITY_FAILURES``) and the run stops
#: only when no servable backend is left.
TERMINAL_FAILURES = frozenset({BUDGET_REFUSED})

#: Provider-availability failures: rotate to another backend, never defer.
AVAILABILITY_FAILURES = frozenset({
    SPEND_EXHAUSTED,
    RATE_LIMITED,
    AUTH_FAILED,
    MODEL_UNAVAILABLE,
})

_SPEND_HINTS = (
    "spend", "credit", "quota", "billing", "payment", "insufficient",
    "allowance", "exhausted balance", "out of credits", "top up", "top-up",
    "limit exceeded for your account", "monthly limit",
)

_BUDGET_HINTS = (
    "would exceed phase ceiling",
    "would eat terminal_reserve",
)

_AUTH_HINTS = (
    "unauthorized", "invalid api key", "invalid key", "forbidden key",
    "authentication", "auth failed", "bad credentials",
)

_MODEL_HINTS = (
    "model not found", "unknown model", "no endpoints", "no available",
    "unsupported model", "model unavailable",
)

_MISSING_TOOL_HINTS = (
    "missing tool", "missing capability", "missing credential",
    "unavailable tool", "no such tool", "tool not found",
    "capability unavailable", "web capability", "detached",
)


def _body_text(resp):
    """Flatten a provider response body to searchable lowercase text."""
    if resp is None:
        return ""
    if isinstance(resp, str):
        return resp.lower()
    if isinstance(resp, dict):
        try:
            return json.dumps(resp, sort_keys=True).lower()
        except (TypeError, ValueError):
            return str(resp).lower()
    return str(resp).lower()


def _has_any(text, hints):
    return any(h in text for h in hints)


def classify_provider_failure(status, resp=None):
    """Classify a provider HTTP failure into a stable kind.

    ``status`` is the HTTP status int (or ``None``); ``resp`` the parsed
    body or raw text. Spend-cap is checked BEFORE 429 on purpose: quota
    exhaustion reported as 429 must be seen as spend, not a transient rate
    limit. Since #538 that is a rotation signal, not a terminal stop.
    """
    text = _body_text(resp)
    if _has_any(text, _SPEND_HINTS):
        return SPEND_EXHAUSTED
    if _has_any(text, _BUDGET_HINTS):
        return BUDGET_REFUSED
    if status == 429:
        return RATE_LIMITED
    if status == 402:
        return SPEND_EXHAUSTED
    if status == 401:
        return AUTH_FAILED
    if status == 403:
        if _has_any(text, ("rate", "throttle", "too many")):
            return RATE_LIMITED
        return AUTH_FAILED
    if status == 404 or (status == 400 and _has_any(text, _MODEL_HINTS)):
        return MODEL_UNAVAILABLE
    if status is not None and 500 <= status <= 599:
        return MODEL_UNAVAILABLE
    if _has_any(text, _AUTH_HINTS):
        return AUTH_FAILED
    if _has_any(text, _MODEL_HINTS):
        return MODEL_UNAVAILABLE
    return UNKNOWN_FAILURE


def classify_harness_error(message):
    """Classify a raised HarnessError message into a failure kind.

    Harness budget refusals carry the spend owner's two refusal shapes;
    provider errors carry the ``HTTP <status>:`` prefix from
    ``results._http_error``. Anything else is unknown (never guessed).
    """
    text = (message or "").lower()
    if _has_any(text, _BUDGET_HINTS):
        return BUDGET_REFUSED
    if _has_any(text, _SPEND_HINTS):
        return SPEND_EXHAUSTED
    import re

    match = re.search(r"http\s+(\d{3})", text)
    if match:
        try:
            return classify_provider_failure(int(match.group(1)), message)
        except (TypeError, ValueError):
            pass
    if "429" in text or "rate limit" in text or "rate-limit" in text:
        return RATE_LIMITED
    return UNKNOWN_FAILURE


def is_terminal_failure(kind):
    """True when the run must stop with no retry and no model rotation.

    Only the run's own budget cap qualifies (#538). Provider availability
    outcomes rotate instead; see ``is_availability_failure``.
    """
    return kind in TERMINAL_FAILURES


def is_availability_failure(kind):
    """True when the failure is about a backend, not about this run's cap."""
    return kind in AVAILABILITY_FAILURES


def is_missing_tool_refusal(reason):
    """True when a refusal means the capability is absent, not retryable."""
    return _has_any((reason or "").lower(), _MISSING_TOOL_HINTS)


# ---------------------------------------------------------------------------
# #204: per-run 429 circuit breaker
# ---------------------------------------------------------------------------

#: How long a rate-limited model stays out of ladder rotation.
RATE_LIMIT_COOLDOWN_SECONDS = 60.0

#: Per-run ceiling on total retry waiting before the run stops honestly.
MAX_RUN_RETRY_WAIT_SECONDS = 30.0


class RateCircuit:
    """Remember 429'd models for a cooldown and cap total retry waiting.

    One instance per run: later rungs and attempts share the memory, so
    a throttled model is skipped, not stormed. Spend exhaustion does not
    enter THIS circuit (its cooldown is the availability ledger's TTL), and
    it is no longer terminal -- ``is_terminal_failure`` is the run's budget
    cap only (#538).
    """

    def __init__(self, cooldown_s=RATE_LIMIT_COOLDOWN_SECONDS,
                 max_wait_s=MAX_RUN_RETRY_WAIT_SECONDS, clock=None):
        self.cooldown_s = float(cooldown_s)
        self.max_wait_s = float(max_wait_s)
        self._clock = clock or time.monotonic
        self._limited_until = {}
        self.total_wait_s = 0.0

    def note_rate_limited(self, model, wait_s=0.0):
        """Record a 429 for ``model`` plus the seconds spent waiting."""
        now = self._clock()
        if model:
            self._limited_until[str(model)] = now + self.cooldown_s
        try:
            self.total_wait_s += max(0.0, float(wait_s))
        except (TypeError, ValueError):
            pass

    def should_skip(self, model):
        """True when ``model`` is still inside its rate-limit cooldown."""
        until = self._limited_until.get(str(model))
        if until is None:
            return False
        return self._clock() < until

    def available(self, models):
        """Filter a ladder to models outside their cooldown (order kept)."""
        return [m for m in (models or []) if not self.should_skip(m)]

    def wait_exhausted(self):
        """True when the per-run retry-wait ceiling is spent."""
        return self.total_wait_s >= self.max_wait_s

    def check_wait_budget(self):
        """Raise HarnessError when the ceiling is spent (honest stop)."""
        if self.wait_exhausted():
            from .errors import HarnessError

            raise HarnessError(
                "rate-limited: per-run retry-wait budget exhausted "
                f"({self.total_wait_s:.1f}s >= {self.max_wait_s:.1f}s); "
                "stopping instead of retrying into a storm"
            )
        return True


# ---------------------------------------------------------------------------
# #205: refusal-loop guard + phase memoization
# ---------------------------------------------------------------------------

def _normalize_refusal(reason):
    """Collapse a refusal reason to a stable signature for repeat detection."""
    return " ".join((reason or "").lower().split())


class RefusalLoopGuard:
    """Stop re-planning when the environment keeps saying the same thing.

    * Missing tools/credentials stop immediately (nothing to re-plan).
    * The same normalized reason twice terminates the loop (known-failed
      strategy); a *different* reason is refinement and passes through.
    """

    def __init__(self):
        self._seen = []

    def check(self, kind, reason):
        """Return ``"stop"`` or ``"continue"`` for this refusal.

        ``kind`` is the refusal category (e.g. ``"missing_tool"``,
        ``"environmental"``, ``"policy"``); ``reason`` is the human text.
        """
        normalized = _normalize_refusal(reason)
        if (kind or "").lower() in ("missing_tool", "missing_capability",
                                    "missing_credential"):
            return "stop"
        if is_missing_tool_refusal(reason):
            return "stop"
        if normalized and normalized in self._seen:
            return "stop"
        if normalized:
            self._seen.append(normalized)
        return "continue"

    @property
    def attempts(self):
        """How many distinct refusals have been recorded."""
        return len(self._seen)


class PhaseMemo:
    """Memoize stable phase inputs within a run; invalidate on change.

    Inputs are keyed by a stable JSON rendering; the caller folds
evidence/auth/config/question inputs into the key, or calls
``invalidate`` outright when they change.
    """

    def __init__(self):
        self._cache = {}

    @staticmethod
    def stable_key(payload):
        """Render relevant inputs to a stable cache key."""
        try:
            return json.dumps(payload, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return str(payload)

    def get(self, phase, key):
        """Return the cached value for ``(phase, key)`` or ``None``."""
        return self._cache.get((phase, self.stable_key(key)))

    def put(self, phase, key, value):
        """Store ``value`` for ``(phase, key)``."""
        self._cache[(phase, self.stable_key(key))] = value
        return value

    def invalidate(self):
        """Drop every cached judgment (evidence/auth/config changed)."""
        self._cache.clear()

    def __len__(self):
        return len(self._cache)


# ---------------------------------------------------------------------------
# #206: honest terminal rendering
# ---------------------------------------------------------------------------

def has_write_surface(target_files, dag=None):
    """True when the request actually involves file writes.

    A read-only run (no target files, and no DAG nodes naming file
    targets) has no write surface, so a file-write gate-guard block
    would be alarming noise about writes that were never planned.
    """
    if target_files:
        return True
    nodes = []
    if isinstance(dag, dict):
        nodes = dag.get("nodes") or []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        targets = node.get("target_files") or node.get("targets") or []
        if targets:
            return True
    return False


def render_refused_plan(prompt, reason, stages=None, nodes=None):
    """Render a refused/empty plan honestly -- never as verified.

    Names the reason and says plainly nothing was verified. Listed
stages/nodes are labeled unconfirmed so the refusal signal survives.
    """
    reason = (reason or "unspecified").strip()
    lines = [
        f"### Plan refused for `{prompt}`",
        "",
        f"Harness could not verify a plan: {reason}.",
        "Nothing was approved and nothing will execute.",
    ]
    stage_lines = []
    for entry in (stages or [])[:5]:
        stage_lines.append(f"- `{entry}` (composed, unconfirmed)")
    for i, node in enumerate(list(nodes or [])[:5], 1):
        if isinstance(node, dict):
            name = node.get("name", "Stage")
            summary = node.get("summary", node.get("description", ""))
            stage_lines.append(f"{i}. **{name}**: {summary} (unconfirmed)")
        else:
            stage_lines.append(f"{i}. {node} (unconfirmed)")
    if stage_lines:
        lines += ["", "**Composed but unconfirmed stages:**"] + stage_lines
    else:
        lines += ["", "No executable stages were produced."]
    return "\n".join(lines) + "\n"


#: Plain-language rendering of the gate reasons an operator can actually meet.
#: A reason is an internal state name; printing it at the operator is what #569
#: reported. Each entry is (what is held, what the operator can do about it).
_GATE_REASON_TEXT = {
    "no_evidence_cited": (
        "the plan cites no evidence for the change it wants to make",
        "Name the file and line the change is grounded in (or paste that "
        "evidence), then send the request again.",
    ),
    "bounded_evidence_request": (
        "the plan needs more evidence before it can be trusted with a write",
        "Answer the evidence questions the plan listed, then send the request "
        "again.",
    ),
    "no_brief_fit_any_round": (
        "no plan matched this request with enough grounding to write",
        "Restate the request with the concrete file and the change you want, "
        "then send it again.",
    ),
    "nothing_left_to_request": (
        "planning ran out of questions without finding grounded evidence",
        "Supply the evidence the plan asked for, then send the request again.",
    ),
}

#: These reasons ask the operator to renew consent; the gate refuses to
#: dispatch on consent that predates the current assignment.
_CONSENT_REASON_MARKERS = (
    "consent no longer covers",
    "must be renewed",
    "consent required",
)


def _operator_reason(reason):
    """Say what is held in the operator's terms, never as internal state.

    Returns ``(sentence, next_step, support_code)``. ``support_code`` carries
    the raw gate reason only when the reason is not one of the recognized
    shapes, so a report can be diagnosed without making the operator read
    machine state (#569).
    """
    text = (reason or "").strip()
    lowered = text.lower()
    if text in _GATE_REASON_TEXT:
        sentence, step = _GATE_REASON_TEXT[text]
        return sentence, step, None
    if any(marker in lowered for marker in _CONSENT_REASON_MARKERS):
        return (
            "the consent recorded for this assignment no longer covers it, "
            "because the assignment changed after consent was given",
            "Renew consent for this assignment, then send the request again.",
            None,
        )
    if not text:
        return (
            "the plan did not pass the gate, so no write was made",
            "Send the request again, or approve the plan explicitly.",
            None,
        )
    return (
        "the plan did not pass the gate, so no write was made",
        "Send the request again with the change you want stated plainly, or "
        "approve the plan explicitly.",
        text,
    )


def render_gate_guard(reason, has_write, *, planned=None, paths=None,
                      prior_rounds=None):
    """Render one gate-guard block, or ``""`` when there is no write surface.

    Blocking behavior is unchanged (#206 non-goal); only what it *says* is
    scoped -- read-only runs never see file-write blocks.

    #569: the block printed the internal gate reason and told the operator to
    review changes that were never shown. It now names what is held, lists the
    change surface it was given, and states the one next step.
    """
    if not has_write:
        return ""
    sentence, step, support_code = _operator_reason(reason)
    surface = [str(p) for p in (paths or []) if str(p).strip()]
    planned_lines = []
    for entry in (planned or [])[:8]:
        if isinstance(entry, dict):
            target = (entry.get("path") or entry.get("target")
                      or entry.get("name") or "change")
            summary = entry.get("summary") or entry.get("description") or ""
            planned_lines.append(
                "  - `{}`{}".format(target, ": " + str(summary) if summary else ""))
        elif str(entry).strip():
            planned_lines.append("  - `{}`".format(str(entry).strip()))
    if not planned_lines:
        planned_lines = ["  - `{}`".format(p) for p in surface[:8]]
    # #683 finding 17: the assurance is worth having only if it is true. The
    # orchestrator executes earlier rounds before a later plan_round refuses,
    # so name those rounds and what they left written rather than claiming the
    # whole request wrote nothing.
    executed = [entry for entry in (prior_rounds or [])
                if isinstance(entry, dict)]
    if executed:
        rounds = ", ".join(str(entry.get("round")) for entry in executed)
        written = sorted({str(target) for entry in executed
                          for target in (entry.get("targets") or [])
                          if str(target).strip()})
        if written:
            assurance = (
                "**Autonomous Waist Gate Guard:** this refused plan was held "
                "before any file was written for it. Nothing was saved for "
                "that plan and nothing in it ran. Earlier round(s) {} of this "
                "run already wrote: {}."
                .format(rounds, ", ".join("`{}`".format(p) for p in written)))
        else:
            assurance = (
                "**Autonomous Waist Gate Guard:** this refused plan was held "
                "before any file was written for it. Nothing was saved for "
                "that plan and nothing in it ran. Earlier round(s) {} of this "
                "run already executed; their results remain on disk."
                .format(rounds))
    else:
        assurance = (
            "**Autonomous Waist Gate Guard:** this request was held before "
            "any file was written. Nothing was saved and nothing ran.")
    lines = [
        assurance,
        "",
        f"**What is held:** {sentence}.",
    ]
    if planned_lines:
        lines += ["", "**What would change:**"] + planned_lines
    else:
        lines += ["", "**What would change:** no file was named by the plan, "
                      "so there is no change list to show."]
    lines += ["", f"**What to do next:** {step}"]
    if support_code:
        lines += ["", f"Support code: `{support_code}`"]
    return "\n".join(lines)


def dedupe_notices(blocks):
    """Collapse identical notice blocks, preserving first-seen order."""
    seen = set()
    out = []
    for block in blocks or []:
        if block is None:
            continue
        text = str(block)
        if not text.strip() or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out
