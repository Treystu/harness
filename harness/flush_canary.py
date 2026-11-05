"""Planted-defect canaries for the flush loop: does it actually catch these?

FLUSH-3 of the saturation loop. A loop that scores its own targets is only as
good as its ability to fail on something it was built to catch, so the gate
plants defects the loop's rules claim to refuse and asserts the loop refuses
them. Each canary is a scenario executed against the real code -- not a mock
of it -- and `run_canary_suite` scores every canary by name.

What is planted, and why each one matters:

- ``claim-without-read``: a material claim with no evidence record. A loop
  that scores this and moves on will saturate on nothing.
- ``delta-free-pass``: the same pass twice. Rule 0 must refuse the second and
  record the refusal; otherwise two passes over one information set can be
  counted as progress.
- ``noted-disposition``: a finding parked as "noted". The register has two
  exits and neither is "noted"; the attempt must raise.
- ``stop-after-one-pass``: saturation claimed after a single clean pass. The
  stop rule requires two consecutive clean expansion passes, a cold run in the
  final pass and a bar met on a dossier.
- ``panel-counted-as-jev``: the FLUSH-1 loop handed a panel instrument. One
  judge counted as a panel rotation is exactly the false coverage the
  instrument list exists to prevent.

Rotation: the canaries run in an order rotated by ``seed``, so a run does not
always exercise them in the same sequence. There is no held-out split yet --
with five canaries a split would score the loop on two -- and that is stated
here rather than implied by silence. The suite is wired as an audit rule
(``sd_flush_canary``) so it runs with the repo's gates.
"""
import tempfile
from pathlib import Path

from .flush_loop import (
    AspectVerdict,
    EventLedger,
    FlushError,
    FlushLoop,
    GapRegister,
    GapRegisterError,
    PassRefused,
    canonical_digest,
)


def _canary_claim_without_read(directory):
    """A material finding must land as material, with no cure invented."""
    ledger = EventLedger(Path(directory) / "claim.jsonl")

    def judge(*, aspect, angle, target, records):
        return AspectVerdict(
            aspect=aspect, basis="dossier:none@canary",
            findings=({"id": "canary-claim",
                       "summary": "claim with no evidence record",
                       "materiality": "violates_invariant"},))

    loop = FlushLoop(ledger=ledger, judge=judge, campaign="canary")
    loop.run_pass(target="a claim with no read",
                  records=[("ev-canary", "unrelated")],
                  angles=["missing-evidence"], aspects=["evidence"])
    finding = loop.register.get("canary-claim")
    return (finding.state == "open" and finding.cure == "",
            f"state={finding.state} cure={finding.cure!r}")


def _canary_delta_free_pass(directory):
    """The second identical pass must be refused and recorded as refused."""
    ledger = EventLedger(Path(directory) / "delta.jsonl")

    def judge(*, aspect, angle, target, records):
        return AspectVerdict(aspect=aspect, basis="dossier:ev@canary")

    loop = FlushLoop(ledger=ledger, judge=judge, campaign="canary")
    loop.run_pass(target="t", records=[("ev-canary", "same")],
                  angles=["flaw-hunt"], aspects=["scale"])
    try:
        loop.run_pass(target="t", records=[("ev-canary", "same")],
                      angles=["flaw-hunt"], aspects=["scale"])
    except PassRefused:
        events = [event["event"] for event in ledger.read()]
        return ("pass_refused" in events, f"events={events}")
    return (False, "the delta-free pass was admitted")


def _canary_noted_disposition(directory):
    """`register.note` is not a disposition and must raise."""
    register = GapRegister()
    register.add(_finding(), materiality="axis_move")
    try:
        register.note("canary-noted", "later")
    except GapRegisterError as exc:
        return ("no 'noted' state" in str(exc), str(exc)[:120])
    return (False, "note() accepted a finding")


def _canary_stop_after_one_pass(directory):
    """One clean pass is not saturation, and the refusal says why."""
    ledger = EventLedger(Path(directory) / "stop.jsonl")

    def judge(*, aspect, angle, target, records):
        return AspectVerdict(aspect=aspect, basis="dossier:ev@canary")

    loop = FlushLoop(ledger=ledger, judge=judge, campaign="canary")
    loop.run_pass(target="t", records=[("ev-canary", "same")],
                  angles=["flaw-hunt"], aspects=["scale"])
    loop.mark_cold_run(basis="cold reader canary")
    dossier = {"axes": {"completeness": 99}, "basis": "dossier:ev@canary"}
    try:
        loop.mark_stopped(dossier)
    except FlushError as exc:
        return ("2 are required" in str(exc), str(exc)[:160])
    return (False, "saturation was claimed after one pass")


def _canary_panel_counted_as_jev(directory):
    """The Jev-only loop must refuse a panel instrument by name."""
    ledger = EventLedger(Path(directory) / "panel.jsonl")

    def judge(*, aspect, angle, target, records):
        return AspectVerdict(aspect=aspect, basis="dossier:ev@canary")

    loop = FlushLoop(ledger=ledger, judge=judge, campaign="canary")
    try:
        loop.run_pass(target="t", records=[("ev-canary", "same")],
                      angles=["flaw-hunt"], aspects=["scale"],
                      instruments=("panel",))
    except FlushError as exc:
        return ("exactly one instrument" in str(exc), str(exc)[:160])
    return (False, "a panel instrument ran on the FLUSH-1 loop")


def _finding():
    from .flush_loop import Finding
    return Finding(id="canary-noted", summary="a finding parked as noted")


#: id -> (what is planted, how it is run). The id is what a report names.
CANARIES = (
    ("claim-without-read", _canary_claim_without_read),
    ("delta-free-pass", _canary_delta_free_pass),
    ("noted-disposition", _canary_noted_disposition),
    ("stop-after-one-pass", _canary_stop_after_one_pass),
    ("panel-counted-as-jev", _canary_panel_counted_as_jev),
)


def run_canary_suite(*, seed=0):
    """Run every canary and report what the loop found and what it missed.

    ``ok`` is true only when every planted defect was caught. A missed canary
    is named with its evidence, because "the canary suite passed" is not a
    sentence anyone can act on.
    """
    canaries = list(CANARIES)
    if canaries:
        offset = int(seed) % len(canaries)
        canaries = canaries[offset:] + canaries[:offset]
    found, missed, detail = [], [], {}
    with tempfile.TemporaryDirectory(prefix="harness-flush-canary-") as tmp:
        for index, (identifier, runner) in enumerate(canaries):
            directory = Path(tmp) / f"{index:02d}-{identifier}"
            directory.mkdir(parents=True, exist_ok=True)
            try:
                caught, evidence = runner(str(directory))
            except Exception as exc:  # a canary that explodes found nothing
                caught, evidence = False, f"{type(exc).__name__}: {exc}"
            detail[identifier] = {"found": bool(caught), "evidence": evidence}
            (found if caught else missed).append(identifier)
    return {
        "seed": int(seed),
        "ran": len(canaries),
        "found": found,
        "missed": missed,
        "ok": not missed and bool(canaries),
        "detail": detail,
    }


def canary_fingerprint(result):
    """A stable digest of a suite result, for pinning the gate's corpus."""
    payload = "|".join(sorted(result.get("found") or ())) + "#" + \
        "|".join(sorted(result.get("missed") or ()))
    return canonical_digest(payload)
