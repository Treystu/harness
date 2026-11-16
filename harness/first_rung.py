"""#280 -- calibration-driven first rung, and rotation after one unusable sample.

The issue is measured, not hypothetical: a fizzbuzz bench task took a mean 5.0
verify rounds because the first free model sampled succeeded one time in three,
while the harness already records per-model calibration for exactly that task
class. Two things were missing from routing:

1. **The first rung never moved.** ``Router._rotation_ordered`` deliberately
   keeps the declared head and only ranks the tail; ``capability.order_pool``
   ranks a whole pool from calibration but returns a bare list with no reasons.
   So the declared head is served first no matter what the ledger says, and the
   operator cannot see why a rung was picked.
2. **An unusable structured response cost a full rotation budget.** Rotation
   ranking is fed by binary in-session health (``note_model_result``), so a model
   that answers HTTP 200 with unparseable text is indistinguishable from one that
   worked; nothing records "rotated for structured output" as its own reason.

This module is the decision layer for both, additive and dependency-free:

* :func:`choose_first_rung` consults recorded calibration for the task class and
  may move the head -- but only on evidence that clears a sample floor and a
  margin, and it always says which rule fired. With no history it returns the
  declared ladder untouched, which is the fallback the acceptance asks for.
* :class:`StructuredRotation` rotates a model out after ``limit`` consecutive
  unusable structured responses (default 1, configurable) and records the
  rotation with its own reason string for the ledger.

Both refuse to leave the pool empty: a lane with no models is not a routing
decision, it is a crash.
"""
import json

#: Rotate out after this many consecutive unusable structured responses.
DEFAULT_STRUCTURED_LIMIT = 1

#: Below this many recorded samples, calibration may NOT move the first rung.
#: One good probe is not a task-class track record.
DEFAULT_MIN_SAMPLES = 3

#: How far a challenger's measured success must beat the declared head's before
#: it is promoted. A tie keeps the declared order (cheap-first discipline).
DEFAULT_MARGIN = 0.15

#: Reason codes for a structured-output rotation. Each is its own reason in the
#: ledger; ``ok`` is never a rotation.
STRUCTURED_REASONS = (
    "structured_output_unparseable",
    "structured_output_missing_fields",
    "structured_output_empty",
)


class FirstRungError(ValueError):
    """A routing decision that cannot be made from the inputs given."""


def _pool(pool):
    out = []
    for model in pool or []:
        if isinstance(model, str) and model and model not in out:
            out.append(model)
    if not out:
        raise FirstRungError("a pool needs at least one model id")
    return out


def calibration_for(report, model, task="structured"):
    """One model's recorded calibration for ``task``, or a no-data record.

    Reads the real report shape produced by ``capability.build_report``:
    ``report["calibration"][model]`` with ``structured_success_rate`` /
    ``structured_samples`` for structured work, ``success_rate`` / ``samples``
    otherwise, plus ``unusable_outputs`` as the strike count.
    """
    row = ((report or {}).get("calibration") or {}).get(model) or {}
    if task == "structured":
        rate = row.get("structured_success_rate")
        samples = row.get("structured_samples")
    else:
        rate = row.get("success_rate")
        samples = row.get("samples")
    samples = int(samples) if isinstance(samples, (int, float)) and samples > 0 else 0
    rate = float(rate) if isinstance(rate, (int, float)) else None
    return {
        "model": model,
        "task": task,
        "samples": samples,
        "success": rate,
        "unusable": int(row.get("unusable_outputs") or 0),
        "present": samples > 0 and rate is not None,
    }


def has_calibration(report, models, task="structured"):
    """True when at least one model in the pool has recorded samples."""
    return any(calibration_for(report, m, task)["present"] for m in models)


def choose_first_rung(pool, report=None, task="structured",
                      min_samples=DEFAULT_MIN_SAMPLES, margin=DEFAULT_MARGIN):
    """Decide the first rung from recorded calibration, with its reasons.

    Returns ``{"first", "order", "source", "reasons", "candidates"}`` where
    ``source`` is ``"declared"`` (fallback, nothing recorded or nothing credible)
    or ``"calibration"`` (the head moved). ``order`` always starts with
    ``first`` and otherwise keeps the declared order, so a demotion never
    reshuffles models that were not measured.
    """
    models = _pool(pool)
    if min_samples < 1:
        raise FirstRungError("min_samples must be at least 1")
    if margin < 0:
        raise FirstRungError("margin must not be negative")

    if len(models) == 1:
        return {"first": models[0], "order": list(models), "source": "declared",
                "reasons": [f"only declared model in the pool: {models[0]}"],
                "candidates": []}

    if not has_calibration(report, models, task):
        return {"first": models[0], "order": list(models), "source": "declared",
                "reasons": ["no recorded calibration for this pool; declared "
                            "ladder kept"],
                "candidates": []}

    candidates = []
    for model in models:
        cal = calibration_for(report, model, task)
        candidates.append({
            "model": model,
            "present": cal["present"],
            "samples": cal["samples"],
            "success": cal["success"],
            "unusable": cal["unusable"],
            # A model with unusable structured output is never promoted, however
            # high its success rate looks on the samples that did parse.
            "promotable": cal["present"] and cal["samples"] >= min_samples
            and cal["unusable"] == 0,
        })

    head = models[0]
    head_cal = next(c for c in candidates if c["model"] == head)
    reasons = []
    best = None
    for cand in candidates:
        if cand["model"] == head or not cand["promotable"]:
            continue
        if best is None or (cand["success"], -models.index(cand["model"])) > \
                (best["success"], -models.index(best["model"])):
            best = cand

    if not head_cal["present"]:
        reasons.append(f"declared head {head} has no recorded samples; kept")
    elif head_cal["samples"] < min_samples:
        reasons.append(f"declared head {head} has {head_cal['samples']} sample(s), "
                       f"below the {min_samples}-sample floor; kept")
    elif head_cal["unusable"]:
        reasons.append(f"declared head {head} has {head_cal['unusable']} unusable "
                       "structured response(s)")

    if best is not None and (not head_cal["present"]
                             or head_cal["samples"] < min_samples
                             or head_cal["unusable"]):
        # A head we cannot vouch for loses to a model we can.
        best_success = best["success"]
        reasons.append(f"{best['model']} promoted on {best['samples']} sample(s) "
                       f"at {best_success:.3f} because the declared head is "
                       "unmeasured or struck")
        first = best["model"]
        source = "calibration"
    elif best is not None and head_cal["success"] is not None \
            and best["success"] - head_cal["success"] >= margin:
        reasons.append(f"{best['model']} promoted: {best['success']:.3f} vs "
                       f"{head_cal['success']:.3f} for {head} over "
                       f"{best['samples']} sample(s) (margin {margin:.2f})")
        first = best["model"]
        source = "calibration"
    elif best is not None and head_cal["success"] is not None:
        reasons.append(f"{head} kept: best challenger {best['model']} at "
                       f"{best['success']:.3f} does not clear "
                       f"{head_cal['success']:.3f} by {margin:.2f}")
        first = head
        source = "declared"
    else:
        reasons.append(f"{head} kept: no usable challenger calibration")
        first = head
        source = "declared"

    order = [first] + [m for m in models if m != first]
    return {"first": first, "order": order, "source": source,
            "reasons": reasons, "candidates": candidates}


def route_reasons(spec):
    """The reasons line(s) a `route` face prints for a chosen first rung."""
    if not isinstance(spec, dict):
        raise FirstRungError(f"a routing spec must be a mapping, got {type(spec).__name__}")
    reasons = spec.get("reasons")
    if not reasons:
        raise FirstRungError("a routing spec carries no reasons to print")
    return list(reasons)


class StructuredRotation:
    """Rotate after ``limit`` consecutive unusable *structured* responses.

    Counting is consecutive on purpose: one clean structured response means the
    model can emit what the gate needs, so the budget starts again. Every
    decision is appended as its own ledger-shaped record whose ``reason`` is one
    of :data:`STRUCTURED_REASONS` (or ``ok``), so "rotated for structured output"
    is a visible reason rather than an inference from a binary failure count.
    """

    def __init__(self, limit=DEFAULT_STRUCTURED_LIMIT):
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise FirstRungError(f"limit must be a positive int, got {limit!r}")
        self.limit = limit
        self._streak = {}
        self._rotated = set()
        self.records = []

    def record(self, model, ok, reason="ok"):
        if not isinstance(model, str) or not model:
            raise FirstRungError("record needs a model id")
        if reason != "ok" and reason not in STRUCTURED_REASONS:
            raise FirstRungError(
                f"reason must be 'ok' or one of {list(STRUCTURED_REASONS)}, "
                f"got {reason!r}")
        if ok:
            self._streak[model] = 0
            self._rotated.discard(model)
        else:
            self._streak[model] = self._streak.get(model, 0) + 1
            if self._streak[model] >= self.limit:
                self._rotated.add(model)
        entry = {
            "model": model,
            "ok": bool(ok),
            "reason": "ok" if ok else reason,
            "sample": self._streak.get(model, 0),
            "limit": self.limit,
            "rotates_out": self.rotates_out(model),
        }
        self.records.append(entry)
        return entry

    def rotates_out(self, model):
        return model in self._rotated

    def streak(self, model):
        return self._streak.get(model, 0)

    def eligible(self, pool):
        """The pool with rotated-out models removed, never emptied."""
        models = _pool(pool)
        keep = [m for m in models if not self.rotates_out(m)]
        return keep or [models[-1]]

    def reasons(self):
        """One line per rotation, naming the reason and the sample count."""
        out = []
        for entry in self.records:
            if entry["rotates_out"]:
                out.append(f"{entry['model']} rotated after "
                           f"{entry['sample']}/{entry['limit']} sample(s): "
                           f"{entry['reason']}")
        return out

    def to_json(self):
        return json.dumps(self.records, sort_keys=True)
