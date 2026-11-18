"""#480 BR6 -- the perception bridge's acceptance battery, executed.

The issue's acceptance list is six probes. Five of them are provable without a
desktop, and they were each proved once in a hand-written test; the sixth needs
the owner's live session. What was missing is the *battery*: one artifact an
operator (or the sergeant's readiness run) can execute that reports, per probe,
the condition it observed, and that refuses to call a hermetic run a live pass.

So this module is deliberately not a second implementation of the bridge. Every
probe drives the shipped surfaces -- :mod:`driver_core.capture_hand`,
:func:`driver_core.osal.capture_screen`, the freshness gate, the grant ledger --
and records what came back. A battery that re-implemented the bridge would
prove only that two implementations exist.

Probe 1 is the live one and it is the one that cannot be faked. With no live
reader it reports ``blocked`` and carries the runbook; it never reports ``met``
on a stand-in. The other five run hermetically against the real hand, so they
are evidence about this tree rather than about a mock of it.

Receipt shape (``bridge-battery@1``)::

    {"schema": "bridge-battery@1", "ran_at": <unix>, "live": <bool>,
     "probes": [{"id", "state", "detail", "evidence"}, ...],
     "met": <n>, "total": 6, "passed": <bool>, "blocked": [<ids>]}

Run it::

    python -m driver_core.bridge_battery            # hermetic, probe 1 blocked
    python -m driver_core.bridge_battery --live     # owner-supervised session

Exit codes: ``0`` all six probes met; ``1`` a probe failed; ``2`` the battery
ran but the live probe is blocked (the honest state of every hermetic run).
"""
import argparse
import json
import os
import sys
import tempfile
import time

from . import capture_hand as hand

#: The receipt's schema name and version. A reader that does not know this name
#: refuses the receipt rather than reading a subset of it as if it were whole.
BATTERY_SCHEMA = "bridge-battery@1"

#: Probe states. "blocked" is not a soft failure: it names a proof this process
#: cannot produce, which is a different operator act from a failed check.
MET = "met"
BLOCKED = "blocked"
FAILED = "failed"

#: What the owner has to do for probe 1. Carried on the blocked receipt so the
#: runbook travels with the verdict instead of living only in an issue comment.
LIVE_RUNBOOK = (
    "Probe 1 needs a supervised interactive session: (1) start driver-core's "
    "capture service off port 8765 (8765 is the serving UI; do not stop it), "
    "(2) set DRIVER_SCREEN to the FreeBuff desktop, (3) confirm the bridge's "
    "kill switch is clear and a capture grant is issued for the asking seat, "
    "(4) run this battery with --live from the non-desktop driver, (5) file "
    "the receipt on #480 and #452. Owner-present only: no unsupervised input "
    "or GUI run is authorised by this lane."
)

#: The six acceptance probes, in the issue's order. The ids are stable because
#: a receipt is compared across runs.
PROBE_IDS = (
    "live_capture",
    "stale_frame",
    "locked",
    "wrong_token",
    "fingerprint_stability",
    "negative_content",
)


def _probe(probe_id, state, detail, evidence=None):
    """One probe result, with every key always present.

    A receipt whose failure carried no key would be read as an absent check
    rather than a failed one, so ``evidence`` is ``{}`` rather than omitted.
    """
    return {"id": probe_id, "state": state, "detail": str(detail),
            "evidence": dict(evidence or {})}


def _frame_file(root, payload, name="frame.png"):
    path = os.path.join(root, name)
    with open(path, "wb") as handle:
        handle.write(payload)
    return path


def probe_live_capture(*, live, capture, clock, max_age):
    """Probe 1: one evidenced capture, and only a live reader can evidence it."""
    if not live:
        return _probe(
            "live_capture", BLOCKED,
            "no live capture surface in this process; the probe needs a "
            "supervised interactive session driving the FreeBuff desktop",
            {"runbook": LIVE_RUNBOOK})
    if capture is None:
        return _probe(
            "live_capture", BLOCKED,
            "--live was requested but no capture reader was supplied; the "
            "battery does not invent one",
            {"runbook": LIVE_RUNBOOK})
    try:
        path, detail = capture()
    except Exception as exc:  # a reader bug is a failed probe, not a crash
        return _probe("live_capture", FAILED,
                      f"the live reader raised: {exc}")
    if not path:
        return _probe(
            "live_capture", FAILED,
            f"the live reader returned no frame ({detail or 'no detail'})")
    captured_at = clock()
    try:
        fingerprint = hand.frame_fingerprint(path)
    except hand.HandError as exc:
        return _probe("live_capture", FAILED,
                      f"the frame could not be digested: {exc}",
                      {"path": path})
    envelope = hand.frame_envelope(path=path, captured_at=captured_at,
                                   state=hand.INTERACTIVE,
                                   fingerprint=fingerprint)
    fresh, why = hand.check_freshness({"path": path, "frame": envelope},
                                      max_age=max_age, now=clock())
    evidence = {"path": path, "fingerprint": fingerprint,
                "captured_at": captured_at, "fresh": fresh}
    if not fresh:
        return _probe("live_capture", FAILED, why, evidence)
    return _probe(
        "live_capture", MET,
        "one frame captured through the live surface and dated inside the "
        "freshness window",
        evidence)


def probe_stale_frame(*, root, clock, max_age):
    """Probe 2: a delayed frame causes mutating work to refuse.

    The freshness gate is the only gate between a frame and the decision tier,
    so proving it refuses a late frame is proving the refusal the step relies
    on. The evidence carries the age and the window, because "stale" without a
    number is not reviewable.
    """
    path = _frame_file(root, b"stale-frame", name="stale.png")
    age = max_age + 25.0
    envelope = hand.frame_envelope(path=path, captured_at=clock() - age,
                                   state=hand.INTERACTIVE)
    ok, why = hand.check_freshness({"path": path, "frame": envelope},
                                   max_age=max_age, now=clock())
    evidence = {"age_s": age, "window_s": max_age, "detail": why}
    if ok:
        return _probe("stale_frame", FAILED,
                      "the freshness gate accepted a frame past its window",
                      evidence)
    if "stale" not in why:
        return _probe("stale_frame", FAILED,
                      f"the gate refused, but not for freshness: {why}",
                      evidence)
    return _probe("stale_frame", MET,
                  f"a frame {age:g}s old is refused by the gate: {why}",
                  evidence)


def probe_locked(*, root, clock):
    """Probe 3: lock mid-session, and the next request returns locked, no frame.

    The LOCK RULE is absolute in the hand, so this probe also asserts the
    capture callable was never entered -- a locked answer that still took a
    frame would satisfy the text and break the rule.
    """
    calls = []
    path = _frame_file(root, b"locked-frame", name="locked.png")

    def capture():
        calls.append(1)
        return path, "captured despite the lock"

    worker = hand.CaptureHand(
        root, session_probe=lambda: hand.LOCKED, capture=capture,
        describe=lambda: ({"model": "leaked"}, ""), clock=clock)
    hand.post_capture_request(root, "probe-locked", "capture", seat="driver")
    result = worker.poll_once()
    evidence = {"state": None if result is None else result.get("state"),
                "path": None if result is None else result.get("path"),
                "frame": None if result is None else result.get("frame"),
                "reader_calls": len(calls)}
    if result is None:
        return _probe("locked", FAILED, "the hand answered nothing", evidence)
    if calls:
        return _probe("locked", FAILED,
                      "the locked branch ran the capture reader", evidence)
    if result.get("path") is not None or result.get("frame") is not None:
        return _probe("locked", FAILED,
                      "the locked answer carried a frame", evidence)
    if result.get("state") != hand.LOCKED:
        return _probe("locked", FAILED,
                      f"the answer named state {result.get('state')!r}, "
                      "not 'locked'", evidence)
    return _probe("locked", MET,
                  "a locked session returns the condition and no frame; the "
                  "reader never ran", evidence)


def probe_wrong_token(*, root, clock):
    """Probe 4: a wrong-seat or ungranted request is refused by name.

    Three distinct refusals, because three distinct acts fix them: a request
    from a seat this bridge was not told about, a declared seat with no grant,
    and a grant issued to a different seat. Collapsing them into one "refused"
    would tell the operator nothing about which gate to open.
    """
    path = _frame_file(root, b"granted-frame", name="granted.png")
    worker = hand.CaptureHand(
        root, session_probe=lambda: hand.INTERACTIVE,
        capture=lambda: (path, "captured"), describe=lambda: ({}, ""),
        clock=clock, seats=("driver",), require_grant=True)

    def answered(request_id, **request):
        hand.post_capture_request(root, request_id, "capture", **request)
        return worker.poll_once() or {}

    intruder = answered("probe-seat", seat="intruder")
    ungranted = answered("probe-nogrant", seat="driver")
    other = hand.issue_capture_grant(root, seat="other", clock=clock)
    wrong_seat = answered("probe-wronggrant", seat="driver",
                          grant=other["grant_id"])

    cases = {
        "intruder_seat": intruder.get("detail", ""),
        "ungranted": ungranted.get("detail", ""),
        "grant_for_other_seat": wrong_seat.get("detail", ""),
    }
    frames = [record.get("path") for record in
              (intruder, ungranted, wrong_seat)]
    evidence = dict(cases)
    evidence["frames_returned"] = frames
    expectations = {
        "intruder_seat": "not on this bridge's allowlist",
        "ungranted": "no capture grant",
        "grant_for_other_seat": "was issued to seat",
    }
    for name, expected in expectations.items():
        if expected not in cases[name]:
            return _probe("wrong_token", FAILED,
                          f"{name} did not refuse by name: {cases[name]!r}",
                          evidence)
    if any(frame is not None for frame in frames):
        return _probe("wrong_token", FAILED,
                      "a refused request still returned a frame", evidence)
    return _probe("wrong_token", MET,
                  "wrong-seat, ungranted and misaddressed grants each refuse "
                  "by name, with no frame", evidence)


def probe_fingerprint_stability(*, root, clock, polls=5):
    """Probe 5: a static screen, N describe polls, one reader run total.

    The first describe legitimately runs the reader: the hand has a digest but
    no remembered fields yet. Every poll after it must dedupe, so the cost of a
    static screen is one describe and then zero -- which is what "zero Jev
    calls" means for a loop that keeps asking.
    """
    if polls < 2:
        return _probe("fingerprint_stability", FAILED,
                      f"a stability probe needs at least 2 polls, got {polls}")
    path = _frame_file(root, b"static-screen", name="static.png")
    describes = []

    def describe():
        describes.append(1)
        return {"model": "model-A"}, "described"

    worker = hand.CaptureHand(
        root, session_probe=lambda: hand.INTERACTIVE,
        capture=lambda: (path, "captured"), describe=describe, clock=clock,
        dedupe=True)
    hand.post_capture_request(root, "probe-fp-capture", "capture",
                              seat="driver")
    worker.poll_once()
    fingerprint = hand.frame_fingerprint(path)

    deduped = 0
    for index in range(polls):
        request_id = f"probe-fp-{index}"
        hand.post_capture_request(root, request_id, "describe", seat="driver",
                                  fingerprint=fingerprint)
        result = worker.poll_once() or {}
        if result.get("deduped"):
            deduped += 1
    evidence = {"polls": polls, "describe_runs": len(describes),
                "deduped": deduped, "fingerprint": fingerprint}
    if len(describes) != 1:
        return _probe("fingerprint_stability", FAILED,
                      f"a static screen ran the reader {len(describes)} times "
                      f"across {polls} polls", evidence)
    if deduped != polls - 1:
        return _probe("fingerprint_stability", FAILED,
                      f"{deduped} of {polls} polls deduped; expected "
                      f"{polls - 1}", evidence)
    return _probe("fingerprint_stability", MET,
                  "an unchanged screen costs one describe and dedupes the "
                  "rest, so a static screen adds zero calls per poll", evidence)


def probe_negative_content(*, root, clock):
    """Probe 6: change the screen, and the new value is what gets extracted.

    A stability probe that only proves "same screen, same answer" is also
    satisfied by a hand that ignores the screen entirely. This probe changes
    the content and requires a new fingerprint, a fresh describe, and the new
    value in the fields -- the negative half of the same property.
    """
    path = os.path.join(root, "model.txt")

    def write(value):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(value)

    def describe():
        with open(path, encoding="utf-8") as handle:
            return {"model": handle.read().strip()}, "described"

    write("model-A")
    worker = hand.CaptureHand(
        root, session_probe=lambda: hand.INTERACTIVE,
        capture=lambda: (path, "captured"), describe=describe, clock=clock,
        dedupe=True)
    hand.post_capture_request(root, "probe-neg-a", "capture", seat="driver")
    worker.poll_once()
    first = hand.frame_fingerprint(path)
    hand.post_capture_request(root, "probe-neg-a-describe", "describe",
                              seat="driver", fingerprint=first)
    before = worker.poll_once() or {}

    write("model-B")
    hand.post_capture_request(root, "probe-neg-b", "capture", seat="driver")
    worker.poll_once()
    second = hand.frame_fingerprint(path)
    hand.post_capture_request(root, "probe-neg-b-describe", "describe",
                              seat="driver", fingerprint=second)
    after = worker.poll_once() or {}

    evidence = {"fingerprint_before": first, "fingerprint_after": second,
                "fields_before": before.get("fields"),
                "fields_after": after.get("fields"),
                "deduped_after": bool(after.get("deduped"))}
    if first == second:
        return _probe("negative_content", FAILED,
                      "changed content produced the same fingerprint", evidence)
    if after.get("deduped"):
        return _probe("negative_content", FAILED,
                      "the changed frame deduped against the old one", evidence)
    fields = after.get("fields") or {}
    if fields.get("model") != "model-B":
        return _probe("negative_content", FAILED,
                      f"extraction read {fields.get('model')!r}, not the new "
                      "value 'model-B'", evidence)
    return _probe("negative_content", MET,
                  "changed content yields a new fingerprint and the new value",
                  evidence)


def run_battery(*, live=False, capture=None, clock=None, root=None,
                polls=5, max_age=hand.DEFAULT_MAX_AGE):
    """Run all six probes and return the receipt.

    ``root`` is the bridge ledger the hand and the driver share; when it is
    omitted a temporary one is used and removed afterwards, so a hermetic run
    leaves nothing behind. ``capture`` is the live reader for probe 1 -- the
    battery never builds one, because a reader it built would be its own
    evidence.
    """
    now = clock or time.time
    temporary = None
    if root is None:
        temporary = tempfile.TemporaryDirectory(prefix="bridge-battery-")
        root = temporary.name
    root = os.path.abspath(root)
    os.makedirs(root, exist_ok=True)
    try:
        probes = [
            probe_live_capture(live=live, capture=capture, clock=now,
                               max_age=max_age),
            probe_stale_frame(root=root, clock=now, max_age=max_age),
            probe_locked(root=root, clock=now),
            probe_wrong_token(root=root, clock=now),
            probe_fingerprint_stability(root=root, clock=now, polls=polls),
            probe_negative_content(root=root, clock=now),
        ]
    finally:
        if temporary is not None:
            temporary.cleanup()
    met = [p["id"] for p in probes if p["state"] == MET]
    blocked = [p["id"] for p in probes if p["state"] == BLOCKED]
    return {"schema": BATTERY_SCHEMA, "ran_at": now(), "live": bool(live),
            "probes": probes, "met": len(met), "total": len(probes),
            "passed": len(met) == len(probes), "blocked": blocked}


def format_receipt(receipt):
    """A human-readable rendering. The JSON is the evidence; this is for eyes."""
    lines = [f"{receipt['schema']}  live={receipt['live']}  "
             f"met={receipt['met']}/{receipt['total']}  "
             f"passed={receipt['passed']}"]
    for probe in receipt["probes"]:
        lines.append(f"  [{probe['state']:>7}] {probe['id']}: "
                     f"{probe['detail']}")
    if receipt["blocked"]:
        lines.append(f"blocked: {', '.join(receipt['blocked'])}")
    return "\n".join(lines)


def exit_code(receipt):
    """``0`` all met, ``1`` a probe failed, ``2`` something is blocked.

    A blocked run is neither success nor failure, and collapsing it into
    either is how an unproven bridge gets reported as a proved one.
    """
    if receipt["passed"]:
        return 0
    if any(probe["state"] == FAILED for probe in receipt["probes"]):
        return 1
    return 2


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="driver_core.bridge_battery",
        description="#480 BR6: run the perception bridge acceptance battery.")
    parser.add_argument("--live", action="store_true",
                        help="probe 1 against a live, supervised session")
    parser.add_argument("--root", default=None,
                        help="the bridge ledger root (default: a temp dir)")
    parser.add_argument("--polls", type=int, default=5,
                        help="describe polls for the stability probe")
    parser.add_argument("--max-age", type=float, default=hand.DEFAULT_MAX_AGE,
                        help="freshness window in seconds")
    parser.add_argument("--out", default=None,
                        help="write the JSON receipt to this path")
    args = parser.parse_args(argv)

    receipt = run_battery(live=args.live, root=args.root, polls=args.polls,
                          max_age=args.max_age)
    text = json.dumps(receipt, indent=2, sort_keys=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
        print(format_receipt(receipt))
        print(f"receipt: {os.path.abspath(args.out)}")
    else:
        print(text)
    return exit_code(receipt)


if __name__ == "__main__":
    sys.exit(main())
