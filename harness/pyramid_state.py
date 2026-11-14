"""Persisted pyramid run state for DAG-level resume (HG-pyramid-resume).

One owner of the on-disk envelope: goal, DAG, per-node results, spent
ceiling, and free-form meta. ``plan --resume`` loads this state and
re-dispatches only nodes that are not already completed ok -- a finished
node is never spent on twice.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Set

from .dag import DAGNode, TaskDAG
from .errors import HarnessError
from .restart_policy import produce_assistance_request
from .results import SUCCESS_STATUSES

STATE_VERSION = 1


def persist_state(path: str, *, goal: str, dag, node_results=None,
                  spent: float = 0.0, **meta) -> Dict[str, Any]:
    """Atomically write the pyramid state envelope to ``path``."""
    if hasattr(dag, "to_dict"):
        dag_payload = dag.to_dict()
    else:
        dag_payload = dag
    payload = {
        "version": STATE_VERSION,
        "goal": goal,
        "dag": dag_payload,
        "node_results": dict(node_results or {}),
        "spent": float(spent or 0.0),
    }
    payload.update(meta)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    os.replace(tmp, path)
    return payload


def load_state(path: str, *, allow_missing: bool = False) -> Optional[Dict[str, Any]]:
    """Load a pyramid state envelope (fail-closed on unreadable/malformed).

    If ``allow_missing=True`` and the file does not exist, returns ``None``
    for cold-start bootstrapping (DF-HG-2).
    """
    if allow_missing and not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise HarnessError(f"pyramid state unreadable: {path}: {exc}") from exc
    if not isinstance(data, dict) or "dag" not in data:
        raise HarnessError(f"pyramid state malformed: {path}")
    return data


def completed_node_ids(state: Dict[str, Any]) -> Set[str]:
    """Node ids whose stored result is a successful completion."""
    results = state.get("node_results") or {}
    done: Set[str] = set()
    for node_id, res in results.items():
        if isinstance(res, dict) and res.get("status") in SUCCESS_STATUSES:
            done.add(str(node_id))
    return done


def pending_node_details(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """DAG node dicts that still need execution (not completed ok)."""
    done = completed_node_ids(state)
    dag = state.get("dag") or {}
    nodes = dag.get("nodes") if isinstance(dag, dict) else None
    pending = []
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        node_id = node.get("node_id")
        if node_id is not None and str(node_id) in done:
            continue
        pending.append(node)
    return pending


def dag_for_pending(state: Dict[str, Any]) -> TaskDAG:
    """TaskDAG of pending nodes; completed dependencies are treated as satisfied."""
    done = completed_node_ids(state)
    nodes: Dict[str, DAGNode] = {}
    for detail in pending_node_details(state):
        node_id = str(detail.get("node_id") or "")
        if not node_id:
            continue
        deps = tuple(
            str(d) for d in (detail.get("dependencies") or ())
            if str(d) not in done)
        backend = detail.get("backend")
        nodes[node_id] = DAGNode(
            node_id=node_id,
            instruction=str(detail.get("instruction") or ""),
            target_files=tuple(detail.get("target_files") or ()),
            dependencies=deps,
            local_gate=detail.get("local_gate"),
            complexity_tier=int(detail.get("complexity_tier") or 0)
            if detail.get("complexity_tier") is not None else 0,
            backend=backend if backend in ("harness", "morph", "diff") else None,
        )
    return TaskDAG(nodes=nodes)


ASSISTANCE_REGISTER_KEY = "assistance_register"

# The register is bounded: the newest entries are the ones a resume needs,
# so the oldest drop off past this size.
ASSISTANCE_REGISTER_CAP = 8


def _assistance_register_list(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The live assistance register, failing closed on a malformed store."""
    if not isinstance(state, dict):
        raise HarnessError("pyramid state must be an object")
    register = state.get(ASSISTANCE_REGISTER_KEY, [])
    if not isinstance(register, list) or any(
            not isinstance(entry, dict) for entry in register):
        raise HarnessError("pyramid assistance register is malformed: "
                           "expected a list of entries")
    return register


def assistance_register(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A read copy of the state's assistance register (service history).

    The envelope ``load_state`` returns already carries this register, so a
    relaunch imports it wholesale -- there are no clean restarts that forget
    what was asked and what was served.
    """
    return [dict(entry) for entry in _assistance_register_list(state)]


def _assistance_event_key(*, kind, detail, request_id, node_id):
    canonical = json.dumps({"kind": kind, "detail": detail,
                            "request_id": request_id, "node_id": node_id},
                           sort_keys=True, separators=(",", ":"),
                           default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def record_assistance(state: Dict[str, Any], *, kind, detail,
                      request_id=None, node_id=None) -> Dict[str, Any]:
    """Record one assistance request in the register, idempotently.

    The request is classified through the same producer the orchestrator's
    paused branch uses, so a malformed kind/quadruple fails closed here too
    -- nothing is recorded. A repeat of an already-recorded request returns
    the stored entry marked deduplicated (the ``RestartStateStore._remember``
    contract). A cure for an artifact whose earlier cure was already
    serviced is a named escalation, not another loop turn. Past the cap the
    oldest entries drop off; the newest -- the ones a resume needs -- stay.
    """
    produced = produce_assistance_request(
        {"assistance": {"kind": kind, "detail": detail}})
    if not produced["requested"]:
        raise HarnessError("assistance request malformed: " +
                           "; ".join(produced["reasons"]))
    register = _assistance_register_list(state)
    event_key = _assistance_event_key(
        kind=produced["kind"], detail=produced["detail"],
        request_id=request_id, node_id=node_id)
    for entry in register:
        if entry.get("event_key") == event_key:
            return {**entry, "deduplicated": True, "event_emitted": False}
    artifact = produced["detail"]["requested_artifact"]
    escalated = (
        produced["kind"] == "cure"
        and any(entry.get("kind") == "cure"
                and entry.get("status") == "serviced"
                and entry.get("detail", {}).get("requested_artifact")
                == artifact
                for entry in register))
    entry = {
        "kind": produced["kind"],
        "detail": produced["detail"],
        "status": "escalated" if escalated else "requested",
        "request_id": None if request_id is None else str(request_id),
        "node_id": node_id,
        "evidence": [],
        "event_key": event_key,
    }
    if escalated:
        entry["escalation"] = f"cure-repeat:{artifact}"
    register.append(entry)
    del register[:-ASSISTANCE_REGISTER_CAP]
    state[ASSISTANCE_REGISTER_KEY] = register
    return {**entry, "deduplicated": False, "event_emitted": False}


def service_assistance(state: Dict[str, Any], *, event_key,
                       evidence) -> Dict[str, Any]:
    """Service one registered request by appending an evidence injection.

    Servicing marks the entry so a later identical cure records as a named
    escalation; the evidence rides the same register the resume imports
    wholesale. An unknown key or a non-mapping injection fails closed.
    """
    register = _assistance_register_list(state)
    if not isinstance(evidence, dict):
        raise HarnessError("assistance evidence must be a mapping")
    for entry in register:
        if entry.get("event_key") == event_key:
            entry.setdefault("evidence", []).append(evidence)
            if entry.get("status") == "requested":
                entry["status"] = "serviced"
            return dict(entry)
    raise HarnessError("no assistance request matches that event key")


def node_routes_for_pending(state: Dict[str, Any],
                            plan_nodes: Optional[List[Dict[str, Any]]] = None
                            ) -> Dict[str, Dict[str, Any]]:
    """Route detail map for pending nodes (from the stored plan envelope)."""
    done = completed_node_ids(state)
    source = plan_nodes
    if source is None:
        # Prefer an explicit plan_nodes meta blob; fall back to reconstructing
        # minimal route stubs from the DAG details.
        source = state.get("plan_nodes") or []
    routes: Dict[str, Dict[str, Any]] = {}
    for detail in source:
        if not isinstance(detail, dict):
            continue
        node_id = detail.get("node_id")
        if node_id is None or str(node_id) in done:
            continue
        routes[str(node_id)] = detail
    if routes:
        return routes
    for detail in pending_node_details(state):
        node_id = detail.get("node_id")
        if node_id is None:
            continue
        routes[str(node_id)] = {
            "node_id": node_id,
            "route": detail.get("route") or {
                "ladder": [], "cost_ceiling": detail.get("cost_ceiling") or 0.0},
        }
    return routes
