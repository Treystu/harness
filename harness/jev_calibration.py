"""Jev decision-gate calibration analysis — tracks issue #168.

MEASUREMENT ONLY. This module changes no active threshold, never calls
``freeze_jev_settings``, and does not alter ``freeze_jev_settings``
behavior. It turns a batch of Jev judgment records into an observed
confidence distribution plus a documented, data-driven threshold
recommendation. The final threshold choice remains the operator's explicit
decision via ``freeze_jev_settings(min_confidence=...)`` in
``harness/config.py``.

Record shape (one dict per judgment)::

    {
        "verdict": str,        # e.g. "proceed" / "needs_improvement" / "escalate"
        "confidence": float,   # 0.0 .. 1.0, required
        "destructive": float,  # is_destructive support, 0.0 .. 1.0 (default 0.0)
        "disposition": str,    # "proceed" | "needs_improvement" | "escalate"
    }

``confidence`` is required and must be a number in [0, 1]; anything else
raises ``ValueError``. ``disposition`` defaults to ``"unknown"`` when
absent so unclassified records still count toward the distribution.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

# Matches the draft spec composition rule: is_destructive.supported >= 0.5
# always escalates, at any confidence.
DESTRUCTIVE_SUPPORT_FLOOR = 0.5

#: ``judgment_route_reason`` prefixes meaning Jev did not decide the judgment:
#: the route fell back. These are the reasons ``harness/panel.py`` already
#: emits under ``jev_primary_mode``; naming them here is measurement, not a new
#: verdict -- the panel's taxonomy stays the authority for what is emitted.
FALLBACK_ROUTE_REASONS = (
    "jev_error",
    "jev_fallback",
    "jev_policy_absent",
    "jev_no_claims",
    "jev_status_missing",
    "jev_not_run",
)

#: The one reason that means the opposite: Jev ran and deferred on its own
#: gate. It is the statistical class -- a deferral with a Jev confidence behind
#: it -- and today it is invisible, because a real deferral carries no route
#: reason at all and reads as an ordinary verdict.
STATISTICAL_ROUTE_REASONS = ("jev_defer",)

#: Every deferred judgment lands in exactly one class. ``unattributed`` is a
#: reason the taxonomy does not name: counted, never dropped.
DEFERRAL_CLASSES = ("fallback", "statistical", "unattributed")


def classify_route_reason(reason):
    """Class of one ``judgment_route_reason`` string, or None when absent.

    ``unattributed`` is the honest bucket for a reason this module does not
    recognise: a new panel reason must show up as an unclassified deferral in
    the report rather than vanish into a fallback total.
    """
    if not isinstance(reason, str) or not reason.strip():
        return None
    prefix = reason.split(":", 1)[0].strip().lower()
    if prefix in FALLBACK_ROUTE_REASONS:
        return "fallback"
    if prefix in STATISTICAL_ROUTE_REASONS:
        return "statistical"
    return "unattributed"


def _class_totals(classes):
    """Sum a class counter, refusing a report whose classes do not add up."""
    total = sum(classes.get(name, 0) for name in DEFERRAL_CLASSES)
    if total != sum(classes.values()):
        raise ValueError(
            "deferral report: classes do not account for every deferral "
            f"({dict(classes)})")
    return total


def deferral_report(entries):
    """Separate fallback deferrals from statistical ones in a result stream.

    Each entry is one panel/judgment result carrying ``judgment_route`` and,
    for a fallback, ``judgment_route_reason``. Records are counted even when
    they carry no ``confidence`` -- a fallback has none, and dropping those
    records is how a fallback becomes invisible in a calibration report.

    Measurement only: the report states counts and N, never a rate it cannot
    back with a sample, and never a threshold.
    """
    rows = [e for e in entries if isinstance(e, Mapping)]
    by_route = {}
    by_class = {name: 0 for name in DEFERRAL_CLASSES}
    by_reason = {}
    unattributed = []
    n_primary = 0
    for entry in rows:
        route = entry.get("judgment_route")
        if route is None:
            continue
        by_route[route] = by_route.get(route, 0) + 1
        if route == "jev_primary":
            n_primary += 1
            continue
        reason = entry.get("judgment_route_reason")
        cls = classify_route_reason(reason) or "unattributed"
        by_class[cls] += 1
        label = reason if isinstance(reason, str) and reason.strip() else "<absent>"
        key = label.split(":", 1)[0].strip().lower() or "<absent>"
        by_reason[key] = by_reason.get(key, 0) + 1
        if cls == "unattributed":
            unattributed.append(label)
    n_verdicts = sum(by_route.values())
    n_fallback = n_verdicts - n_primary
    total = _class_totals(by_class)
    if total != n_fallback:
        raise ValueError(
            "deferral report: "
            f"{n_fallback} fallback verdict(s) but classes account for {total}")
    return {
        "n_entries": len(rows),
        "n_verdicts": n_verdicts,
        "n_primary": n_primary,
        "n_fallback": n_fallback,
        "by_route": dict(sorted(by_route.items())),
        "by_class": dict(by_class),
        "by_reason": dict(sorted(by_reason.items())),
        "unattributed_reasons": sorted(unattributed),
        "notes": [
            "measurement only: counts and N, no threshold written.",
            (
                "a record without confidence still counts: a fallback has no "
                "Jev confidence, and dropping it is how fallbacks disappear "
                "from a calibration report."
            ),
        ] if rows else ["no verdict records supplied; advisory only."],
    }


def _percentile(sorted_values: List[float], pct: float) -> float:
    """Linear-interpolation percentile over an already-sorted list."""
    n = len(sorted_values)
    if n == 0:
        raise ValueError("cannot take a percentile of an empty list")
    if n == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (n - 1)
    low = int(rank)
    frac = rank - low
    if low + 1 >= n:
        return sorted_values[-1]
    return sorted_values[low] + frac * (sorted_values[low + 1] - sorted_values[low])


def _distribution(values: Sequence[float]) -> Dict[str, Any]:
    vals = sorted(float(v) for v in values)
    n = len(vals)
    return {
        "n": n,
        "min": vals[0],
        "max": vals[-1],
        "mean": sum(vals) / n,
        "p50": _percentile(vals, 50),
        "p95": _percentile(vals, 95),
    }


def _validate_record(record: Mapping[str, Any], index: int) -> Dict[str, Any]:
    if not isinstance(record, Mapping):
        raise ValueError(f"record {index}: expected a mapping, got {type(record).__name__}")
    if "confidence" not in record:
        raise ValueError(f"record {index}: missing required field 'confidence'")
    conf = record["confidence"]
    if isinstance(conf, bool) or not isinstance(conf, (int, float)):
        raise ValueError(f"record {index}: confidence must be a number, got {conf!r}")
    conf = float(conf)
    if not 0.0 <= conf <= 1.0:
        raise ValueError(f"record {index}: confidence must be in [0, 1], got {conf!r}")
    dest = record.get("destructive", 0.0)
    if isinstance(dest, bool) or not isinstance(dest, (int, float)):
        raise ValueError(f"record {index}: destructive must be a number, got {dest!r}")
    dest = float(dest)
    if not 0.0 <= dest <= 1.0:
        raise ValueError(f"record {index}: destructive must be in [0, 1], got {dest!r}")
    disp = record.get("disposition", "unknown")
    if not isinstance(disp, str) or not disp:
        raise ValueError(f"record {index}: disposition must be a non-empty string")
    reason = record.get("route_reason")
    if reason is not None and (not isinstance(reason, str) or not reason.strip()):
        raise ValueError(
            f"record {index}: route_reason must be a non-empty string when set")
    return {
        "verdict": str(record.get("verdict", "")),
        "confidence": conf,
        "destructive": dest,
        "disposition": disp,
        "route_reason": reason,
    }


def analyze_judgments(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Analyze a batch of judgment records into a calibration report.

    The report carries the observed confidence distribution, a
    per-disposition breakdown, the destructive-flag count, and a
    threshold recommendation (see :func:`recommend_threshold`). An empty
    batch yields an advisory-only report, never an exception.
    """
    cleaned = [_validate_record(r, i) for i, r in enumerate(records)]
    report: Dict[str, Any] = {"n": len(cleaned)}
    if not cleaned:
        report["confidence"] = None
        report["by_disposition"] = {}
        report["destructive_flags"] = 0
        report["recommendation"] = None
        report["notes"] = [
            "advisory only: no judgment records supplied; no threshold can be recommended.",
        ]
        return report

    confidences = [r["confidence"] for r in cleaned]
    report["confidence"] = _distribution(confidences)

    by_disp: Dict[str, List[Dict[str, Any]]] = {}
    for r in cleaned:
        by_disp.setdefault(r["disposition"], []).append(r)
    report["by_disposition"] = {
        disp: {
            "n": len(rows),
            "confidence": _distribution([r["confidence"] for r in rows]),
        }
        for disp, rows in sorted(by_disp.items())
    }
    report["destructive_flags"] = sum(
        1 for r in cleaned if r["destructive"] >= DESTRUCTIVE_SUPPORT_FLOOR
    )
    reasoned = [r for r in cleaned if r["route_reason"]]
    if reasoned:
        classes = {name: 0 for name in DEFERRAL_CLASSES}
        for r in reasoned:
            classes[classify_route_reason(r["route_reason"]) or "unattributed"] += 1
        if _class_totals(classes) != len(reasoned):
            raise ValueError(
                "calibration report: classes do not account for every "
                f"reasoned record ({classes})")
        report["deferral_n"] = len(reasoned)
        report["by_deferral_class"] = classes
    report["recommendation"] = recommend_threshold(cleaned)
    notes = [
        f"{report['n']} judgment records analyzed.",
        (
            f"{report['destructive_flags']} record(s) met the destructive "
            f"support floor ({DESTRUCTIVE_SUPPORT_FLOOR}) and would escalate "
            "at any confidence."
        ),
    ]
    if report["confidence"]["max"] < 0.95:
        notes.append(
            f"observed max confidence {report['confidence']['max']:.2f} "
            "is below the 0.95 fail-closed threshold: at 0.95 the gate "
            "escalates 100% of these records and adds cost without signal."
        )
    report["notes"] = notes
    return report


def recommend_threshold(records: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """Recommend a data-supported threshold band from observed judgments.

    Method (documented, not silent):

    1. A fail-closed threshold T means ``confidence >= T`` may proceed and
       anything below escalates. T is only *discriminating* when it falls
       inside the observed confidence band — otherwise the gate is a
       constant function (0.95 on the observed data escalates everything).
    2. Setting T at the observed max is NOT sufficient: the max is a sample
       statistic, not a population guarantee, and a threshold needs labeled
       ground truth (were past escalations correct? would past proceeds have
       been safe?) per the spec's calibration criterion 3.
    3. The module therefore reports the *discriminating band* [p50, p95] of
       observed confidence: any threshold inside this band would have let a
       nontrivial fraction proceed while escalating the rest. Choosing
       inside (or outside) that band — and accepting the resulting
       false-proceed / false-escalate tradeoff — is the operator's freeze
       decision via ``freeze_jev_settings(min_confidence=...)``, informed by
       a labeled review of past escalations.

    Returns None for an empty batch. Never asserts a single "correct"
    threshold value.
    """
    cleaned = [_validate_record(r, i) for i, r in enumerate(records)]
    if not cleaned:
        return None
    dist = _distribution([r["confidence"] for r in cleaned])
    return {
        "method": (
            "discriminating band [p50, p95] of observed confidence; "
            "threshold-at-observed-max is not sufficient (see docstring). "
            "Final choice is the operator's via freeze_jev_settings."
        ),
        "observed_max": dist["max"],
        "discriminating_band": [dist["p50"], dist["p95"]],
        "warning": (
            "Do not freeze a threshold on this band alone: pair it with a "
            "labeled review of past escalations (spec criterion 3) before "
            "calling freeze_jev_settings(min_confidence=...)."
        ),
    }


def format_report(report: Mapping[str, Any]) -> str:
    """Render a calibration report as human-readable text."""
    lines = [f"jev calibration report — n={report['n']}"]
    conf = report.get("confidence")
    if conf is None:
        lines.append("no records; advisory only.")
        lines.extend(f"note: {n}" for n in report.get("notes", []))
        return "\n".join(lines)
    lines.append(
        "confidence: min={min:.2f} max={max:.2f} mean={mean:.2f} "
        "p50={p50:.2f} p95={p95:.2f}".format(**conf)
    )
    for disp, blk in report.get("by_disposition", {}).items():
        c = blk["confidence"]
        lines.append(
            f"  {disp}: n={blk['n']} "
            "min={min:.2f} max={max:.2f} mean={mean:.2f}".format(**c)
        )
    lines.append(f"destructive flags (>= {DESTRUCTIVE_SUPPORT_FLOOR}): "
                 f"{report['destructive_flags']}")
    if "by_deferral_class" in report:
        classes = report["by_deferral_class"]
        lines.append(
            f"deferral classes (n={report['deferral_n']}): "
            f"fallback={classes['fallback']} "
            f"statistical={classes['statistical']} "
            f"unattributed={classes['unattributed']}"
        )
    rec = report.get("recommendation")
    if rec:
        lo, hi = rec["discriminating_band"]
        lines.append(f"discriminating band: [{lo:.2f}, {hi:.2f}]")
        lines.append(f"warning: {rec['warning']}")
    lines.extend(f"note: {n}" for n in report.get("notes", []))
    return "\n".join(lines)


def extract_judgment_records(entries: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Extract validated calibration records from ledger entries."""
    records = []
    for e in entries:
        ev = e.get("ev") or e.get("event")
        if ev in ("jev_eval", "judgment", "jev_decision"):
            conf = e.get("confidence")
            if conf is None:
                conf = e.get("supported")
            if conf is None:
                continue
            try:
                conf = float(conf)
            except (TypeError, ValueError):
                continue
            dest = float(e.get("destructive", 0.0) or 0.0)
            disp = str(e.get("disposition") or e.get("verdict") or "unknown")
            records.append({
                "verdict": str(e.get("verdict") or ""),
                "confidence": conf,
                "destructive": dest,
                "disposition": disp,
            })
    return records

