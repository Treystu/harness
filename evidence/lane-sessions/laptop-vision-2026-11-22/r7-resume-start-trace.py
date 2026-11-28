"""R7 trace: exercise Resume staging then Start firing as ONE bounded driver action.

This is a harness trace, not a live-lane run: no session exists that is currently
expired with a staged /mission, so the composition is driven against a scripted
surface that offers exactly the controls the live app offers, and the audit log
records the acts the driver actually issued. The trace therefore proves the
composition and its bounds; it does not claim a live lane was resumed.

Run from the repo root:
    python evidence/lane-sessions/laptop-vision-2026-11-22/r7-resume-start-trace.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.abspath("."))

from driver_core.audit import AuditLog
from scripts import windows_freebuff_dispatch as dispatch
from tests.test_freebuff_watch import _Surface

OUT = Path("evidence/lane-sessions/laptop-vision-2026-11-22/r7-resume-start-trace.jsonl")


class TracedSurface(_Surface):
    """The scripted surface, but its acts land in a real hash-chained audit log."""

    def __init__(self, *, path, **kwargs):
        super().__init__(**kwargs)
        self.audit = AuditLog(path)

    def act(self, step, action, params):
        self.acts.append(params["control"])
        self.audit.append("action", step_id=step, control=params["control"],
                          point=list(params.get("point") or []))

    def yes(self, step, frame, question, *, region):
        self.audit.append("verification", step_id=step, detail=question)
        return True

    def locate_exact_text(self, step, frame, label, region, **_kwargs):
        point = super().locate_exact_text(step, frame, label, region, **_kwargs)
        self.audit.append("extraction", step_id=step, exact_label=label, point=list(point))
        return point


def main() -> int:
    OUT.unlink(missing_ok=True)
    surface = TracedSurface(path=OUT, stops=[False, False, True],
                            labels={"Resume mission": (900, 700), "Start mission": (900, 600)})
    with patch.object(dispatch.time, "sleep"):
        outcome = dispatch.resume_staged_session(surface, surface.frame("expired-composer"))
    rows = [json.loads(line) for line in OUT.read_text(encoding="utf-8").splitlines() if line.strip()]
    acts = [row for row in rows if row.get("kind") == "action"]
    located = [row.get("exact_label") for row in rows if row.get("kind") == "extraction"]
    print(json.dumps({
        "outcome": outcome,
        "acts": surface.acts,
        "located": located,
        "audit_records": len(rows),
        "audit_tail_hash": rows[-1]["hash"] if rows else None,
        "trace": str(OUT),
    }, indent=2))
    ok = (outcome in {"resumed", "started"}
          and surface.acts[:1] == ["Resume mission"]
          and located[:2] == ["Resume mission", "Start mission"]
          and len(acts) == len(surface.acts))
    print("R7 composition:", "OK" if ok else "BROKEN")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
