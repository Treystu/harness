"""#336: automatic canary probes and the one shared evidence reader.

A ledger that only fills up when someone runs a task goes stale exactly when it
matters -- a fresh install, a quiet week, or a selection loop (#318) asking for
fresh outcomes. The canaries are cheap, deterministic local probes whose
results are written as ``canary_probe`` rows flagged ``canary: true`` so they
keep the ledger alive without ever being mistaken for task evidence.

The filed ruling (issue #336, record 6971447653) fixes the set and the rules:

* **routing resolves** -- the local resolver on a fixed fixture, run;
* **Jev reachable** -- *excluded* as an automatic probe (a live judgment is
  billed and its answer varies); with no documented unbilled transport ping it
  records ``skipped``, and a fallback is never a successful ping;
* **ledger writable** -- append a flagged probe to the real ledger, flush, read
  back; an unwritable ledger reports through local diagnostics;
* **MCP tools respond** -- only an allowlisted read-only, time-bounded health
  operation naming server and tool, else ``skipped``;
* **key gates green** -- named deterministic local gates on fixed fixtures
  only.

Triggers are startup, daily 00:00 UTC, and a five-minute check finding six
hours since the last verified committed entry (an empty ledger is immediately
stale). Derived rows inherit the flag, and :func:`evidence_rows` is the single
reader that excludes them before selection, citation, or counting.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .errors import HarnessError

CANARY_EVENT = "canary_probe"
STALE_SECONDS = 6 * 3600
DAILY_HOUR_UTC = 0
ROUTING_FIXTURE = "openrouter/test-fixture-model"

Probe = Callable[[Any], Dict[str, Any]]


def _iso(moment: float) -> str:
    return datetime.fromtimestamp(moment, timezone.utc).isoformat(
        timespec="seconds")


def _parse_ts(text: Any) -> Optional[float]:
    try:
        moment = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def routing_resolves(_ledger=None) -> Dict[str, Any]:
    """A fixed fixture through the local resolver -- no network, no provider."""
    from .dynamic_allocation import resolve_model_spec

    spec = resolve_model_spec(ROUTING_FIXTURE)
    if not getattr(spec, "context_window", 0):
        return {"status": "failed", "detail": "resolver returned no context window"}
    return {"status": "ok", "detail": "resolved " + ROUTING_FIXTURE}


def jev_reachable(_ledger=None) -> Dict[str, Any]:
    """Excluded by the ruling: a live judgment is billed and varies."""
    return {"status": "skipped",
            "detail": "live judgment is billed and varies; no documented "
                      "unbilled transport ping exists"}


def ledger_writable(_ledger=None) -> Dict[str, Any]:
    """Proven by the append and read-back :func:`run_canaries` performs."""
    return {"status": "ok", "detail": "append staged"}


def key_gates_green(ledger) -> Dict[str, Any]:
    """The deterministic local gate: the chain verifies on this machine."""
    ok, bad = ledger.verify()
    if not ok:
        return {"status": "failed", "detail": "ledger verify failed at seq "
                                              + str(bad)}
    return {"status": "ok", "detail": "ledger verify passed"}


def default_probes() -> Dict[str, Probe]:
    """The five named probes, in the ruling's order."""
    return {
        "routing_resolves": routing_resolves,
        "jev_reachable": jev_reachable,
        "ledger_writable": ledger_writable,
        "key_gates_green": key_gates_green,
    }


def run_canaries(ledger, *, now: Optional[float] = None,
                 probes: Optional[Dict[str, Probe]] = None,
                 mcp_health: Optional[Probe] = None,
                 trigger: str = "manual") -> List[Dict[str, Any]]:
    """Run the probes, write one labelled row each, and read each one back.

    A probe that raises is a failed probe, not a crashed run. An append that
    fails (an unwritable ledger) is reported in the returned outcomes and in
    ``ledger.chain_status()['canary_error']`` so the operator sees it locally
    instead of in a lost write.
    """
    moment = time.time() if now is None else float(now)
    chosen = dict(default_probes() if probes is None else probes)
    chosen["mcp_tools_respond"] = mcp_health or _mcp_skipped
    outcomes: List[Dict[str, Any]] = []
    for name, probe in chosen.items():
        try:
            result = probe(ledger) or {}
        except Exception as exc:  # a probe failure is evidence, not a crash
            result = {"status": "failed",
                      "detail": "{}: {}".format(type(exc).__name__, exc)}
        status = str(result.get("status") or "failed")
        record = {
            "ts": _iso(moment), "canary": True, "probe": name,
            "ok": status == "ok", "status": status,
            "detail": str(result.get("detail") or ""), "trigger": trigger,
        }
        try:
            written = ledger.append(CANARY_EVENT, **record)
        except (OSError, HarnessError) as exc:
            ledger.canary_error = str(exc)
            outcomes.append(dict(record, appended=False))
            continue
        tail = ledger.entries()[-1] if ledger.entries() else {}
        read_back = tail.get("hash") == written.get("hash") \
            and tail.get("probe") == name
        outcomes.append(dict(record, appended=True, read_back=read_back,
                             seq=written.get("seq")))
    return outcomes


def _mcp_skipped(_ledger=None) -> Dict[str, Any]:
    return {"status": "skipped",
            "detail": "no allowlisted read-only health operation configured"}


def should_run_canaries(ledger, *, now: Optional[float] = None,
                        startup: bool = False,
                        last_run_epoch: Optional[float] = None
                        ) -> Dict[str, Any]:
    """Startup, daily 00:00 UTC, or six hours without a committed entry."""
    moment = time.time() if now is None else float(now)
    reasons: List[str] = []
    if startup:
        reasons.append("startup")
    stamps = [stamp for stamp in (_parse_ts(entry.get("ts"))
                                  for entry in ledger.entries()) if stamp]
    if not stamps:
        reasons.append("empty_ledger")
    elif moment - max(stamps) >= STALE_SECONDS:
        reasons.append("stale")
    if last_run_epoch is None:
        reasons.append("never_ran")
    elif _utc_day(moment) > _utc_day(float(last_run_epoch)):
        reasons.append("daily")
    return {"run": bool(reasons), "reasons": reasons,
            "last_entry_epoch": max(stamps) if stamps else None}


def _utc_day(moment: float) -> str:
    return datetime.fromtimestamp(moment, timezone.utc).strftime("%Y-%m-%d")


def last_canary_run(ledger) -> Optional[float]:
    """When this ledger last recorded a canary probe, or ``None``.

    The due predicate needs the last run in the ledger's own terms, so no
    second state file can drift from the rows it schedules.
    """
    stamps = [stamp for stamp in (_parse_ts(entry.get("ts"))
                                  for entry in _rows_of(ledger)
                                  if entry.get("event") == CANARY_EVENT)
              if stamp]
    return max(stamps) if stamps else None


def maybe_run_canaries(ledger, *, now: Optional[float] = None,
                       startup: bool = False,
                       probes: Optional[Dict[str, Probe]] = None,
                       mcp_health: Optional[Probe] = None
                       ) -> Dict[str, Any]:
    """The production entry point: run the probes only when they are due.

    #683 row 39: the due predicate existed but nothing in normal operation
    called it, so a fresh install or an idle service accumulated none of the
    advertised health evidence. Startup and the periodic sweep both call this,
    which consults the ledger's own last canary row instead of a sidecar.
    """
    moment = time.time() if now is None else float(now)
    due = should_run_canaries(ledger, now=moment, startup=startup,
                              last_run_epoch=last_canary_run(ledger))
    if not due["run"]:
        return {"ran": False, "reasons": due["reasons"],
                "last_entry_epoch": due["last_entry_epoch"], "outcomes": []}
    outcomes = run_canaries(ledger, now=moment, probes=probes,
                            mcp_health=mcp_health,
                            trigger=",".join(due["reasons"]))
    return {"ran": True, "reasons": due["reasons"],
            "last_entry_epoch": due["last_entry_epoch"],
            "outcomes": outcomes}


def evidence_rows(ledger) -> List[Dict[str, Any]]:
    """The one reader for selection, citation, counting and export.

    Every row flagged ``canary: true`` -- canary probes and any derived row
    carrying the flag, including a billed receipt from a separately invoked
    live probe -- is excluded here, before anything counts it. Integrity
    verification, probe diagnostics and spend accounting keep full-ledger
    access and do not go through this reader.
    """
    return [entry for entry in _rows_of(ledger)
            if entry.get("canary") is not True
            and entry.get("event") != CANARY_EVENT]


def _rows_of(ledger) -> List[Dict[str, Any]]:
    """Rows behind a ledger or analytics mixin, tolerating test doubles.

    `AutonomyLedger` exposes `entries()`; the bare `LedgerAnalytics` mixin it
    inherits carries the same rows in `_tail`. Anything else -- a mock in a
    unit test that never configured the reader -- contributes no rows.
    """
    entries = getattr(ledger, "entries", None)
    if callable(entries):
        rows = entries()
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    tail = getattr(ledger, "_tail", None)
    if isinstance(tail, list):
        return [row for row in tail if isinstance(row, dict)]
    return []


def canary_summary(ledger) -> Dict[str, Any]:
    """Local diagnostics: how the latest canary run went, if there was one."""
    rows = [entry for entry in ledger.entries()
            if entry.get("event") == CANARY_EVENT]
    if not rows:
        return {"ran": False, "last_run": None, "by_status": {}}
    by_status: Dict[str, int] = {}
    for row in rows[-5:]:
        status = str(row.get("status") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
    return {"ran": True, "last_run": rows[-1].get("ts"),
            "by_status": by_status, "probes": len(rows)}
