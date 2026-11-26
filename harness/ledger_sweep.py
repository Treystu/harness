"""#336: the timed daily sweep, as a real schedule rather than a comment.

Rotation evaluates the segment it just sealed, which means a ledger that simply
stops growing never gets swept: the old segments sit there with compactable rows
and nothing asks. The filed ruling requires a daily sweep as well, so this
module owns that schedule in two forms, both real:

* :class:`LedgerSweeper` -- an in-process timer that checks every five minutes
  and sweeps once per UTC day (the ruling's trigger). It is a real
  ``threading.Thread``; :meth:`tick` is the single unit both the thread and the
  tests drive.
* :func:`run_daily_sweep` plus :func:`read_last_sweep`/:func:`write_last_sweep`
  -- the same due rule with the last sweep persisted next to the ledger, which
  is what `harness ledger sweep` uses as its cron-able entrypoint.

The sweep itself is :meth:`harness.ledger.AutonomyLedger.sweep_compaction`: it
compacts nothing it cannot prove, so a due sweep on a ledger of protected rows
is a no-op that says so. Nothing here deletes, dispatches or spends.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from .ledger_canary import maybe_run_canaries

#: The ruling's "five-minute check".
SWEEP_CHECK_SECONDS = 300.0


def _utc_day(moment: float) -> str:
    return datetime.fromtimestamp(float(moment), timezone.utc).strftime("%Y-%m-%d")


def _iso(moment: float) -> str:
    return datetime.fromtimestamp(float(moment), timezone.utc).isoformat(
        timespec="seconds")


def sweep_due(now: float, *, last_sweep_epoch: Optional[float] = None) -> bool:
    """Daily 00:00 UTC: due when this UTC day has not been swept yet."""
    if last_sweep_epoch is None:
        return True
    return _utc_day(now) > _utc_day(last_sweep_epoch)


def state_path(ledger_path: str) -> str:
    """Where the last sweep is recorded: next to the ledger, not inside it."""
    return str(ledger_path) + ".sweep-state"


def read_last_sweep(path: Optional[str]) -> Optional[float]:
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            return float(handle.read().strip())
    except (OSError, ValueError):
        return None


def write_last_sweep(path: Optional[str], moment: float) -> None:
    if not path:
        return
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{:.3f}".format(float(moment)))
    except OSError:
        # A sweep that cannot record its own time must not fail the sweep; the
        # next check simply finds the older stamp and may sweep again.
        return


def run_daily_sweep(ledger, *, now: Optional[float] = None,
                    last_sweep_epoch: Optional[float] = None,
                    state_file: Optional[str] = None,
                    force: bool = False) -> Dict[str, Any]:
    """Sweep when the UTC day is unswept, and say honestly when it is not.

    The same periodic check runs the canary probes when they are due (#683 row
    39): this function is both the five-minute timer's unit and the cron-able
    ``harness ledger sweep`` entrypoint, so the advertised daily and staleness
    triggers have a real production caller.
    """
    moment = time.time() if now is None else float(now)
    canaries = maybe_run_canaries(ledger, now=moment)
    previous = (last_sweep_epoch if last_sweep_epoch is not None
                else read_last_sweep(state_file))
    if not force and not sweep_due(moment, last_sweep_epoch=previous):
        return {"ran": False, "reason": "already swept this UTC day",
                "swept_at": _iso(moment), "segments": [],
                "canaries": canaries}
    results = ledger.sweep_compaction()
    write_last_sweep(state_file, moment)
    return {"ran": True, "reason": "due", "swept_at": _iso(moment),
            "segments": results, "canaries": canaries,
            "compacted": sum(1 for result in results
                             if result.get("compacted"))}


class LedgerSweeper:
    """The in-process timer: a five-minute check, one sweep per UTC day."""

    def __init__(self, ledger_factory: Callable[[], Any], *,
                 interval: float = SWEEP_CHECK_SECONDS,
                 clock: Callable[[], float] = time.time,
                 on_sweep: Optional[Callable[[Dict[str, Any]], None]] = None):
        self._ledger_factory = ledger_factory
        self._interval = float(interval)
        self._clock = clock
        self.on_sweep = on_sweep
        self.last_sweep_epoch: Optional[float] = None
        self.last_result: Optional[Dict[str, Any]] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def tick(self, force: bool = False) -> Dict[str, Any]:
        """One check: the unit the timer repeats and the tests drive."""
        result = run_daily_sweep(self._ledger_factory(), now=self._clock(),
                                 last_sweep_epoch=self.last_sweep_epoch,
                                 force=force)
        if result["ran"]:
            self.last_sweep_epoch = self._clock()
        self.last_result = result
        return result

    def start(self) -> "LedgerSweeper":
        self._thread = threading.Thread(target=self._run,
                                        name="ledger-sweeper", daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.is_set():
            result = self.tick()
            if result["ran"] and self.on_sweep is not None:
                self.on_sweep(result)
            self._stop.wait(self._interval)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None
