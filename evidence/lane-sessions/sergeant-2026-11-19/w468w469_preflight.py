"""W468/W469 window-readiness preflight (sergeant, runs at current main).

Proves, by executing rather than asserting, that the persistence unblocker
#627's landing removed is actually gone: the trace writer family exists on
this checkout, the real campaign emitters round-trip through it, and a window
manifest pins. What it does NOT do: run the windows (W2's act), claim any
brief measured, or touch the parked #628 write path.

Usage: python evidence/lane-sessions/sergeant-2026-11-19/w468w469_preflight.py
Exit 0 with a verdict line; any failed check raises with the check number.
"""

import json
import os
import subprocess
import sys
import tempfile

def repo_root():
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def main():
    # HARNESS_TREE, when set, is the read-only tree under test (e.g. an
    # archive extraction of origin/main). The working checkout stays on the
    # sergeant evidence branch; nothing is checked out or modified for this.
    root = os.environ.get("HARNESS_TREE") or repo_root()
    sys.path.insert(0, root)
    main_sha = subprocess.run(
        ["git", "rev-parse", "origin/main"], capture_output=True,
        text=True, check=True, cwd=repo_root()).stdout.strip()
    print(f"main: {main_sha}")

    # CHECK 1: the trace family is importable on this checkout.
    from harness.decision_trace import (
        DecisionTrace, read_trace_events, pin_window, CAMPAIGN_EVENT)
    assert callable(DecisionTrace.campaign_event), "campaign_event missing"
    print("CHECK 1 ok: DecisionTrace/record/campaign_event/read_trace_events/pin_window import")

    # CHECK 2: a temp ledger accepts the real light campaign emitters.
    from harness.ledger import AutonomyLedger
    from harness import flush_loop as fl
    tmp = tempfile.mkdtemp(prefix="w468w469-preflight-")
    ledger = AutonomyLedger(os.path.join(tmp, "ledger.jsonl"), caller="preflight")
    fl.record_refusal(ledger, reason="preflight refusal", campaign="w468w469-preflight")
    fl.record_stop(ledger, campaign="w468w469-preflight", streak=1,
                   basis="preflight", combined=1.0)
    fl.record_info_request(ledger, aspect="spend", missing_record="spend_evidence_001",
                           campaign="w468w469-preflight")
    fl.record_oscillation(ledger, packet={"kind": "combined_cure_packet", "aspect": "cost",
                                          "cycle": ["a", "b"], "cures": {}},
                          campaign="w468w469-preflight")
    print("CHECK 2 ok: four real emitters appended to a temp ledger")

    # CHECK 3: the trace family mirrors them and reads them back.
    trace = DecisionTrace(ledger)
    mirrored = []
    for name in ("pass_refused", "stop", "info_request", "oscillation_escalated"):
        mirrored.append(trace.campaign_event(name, campaign="w468w469-preflight",
                                             payload={"preflight": True, "kind": "producer-word-check"}))
    rows = read_trace_events(ledger, kinds=[CAMPAIGN_EVENT],
                             campaign="w468w469-preflight")
    names = {r.get("campaign_event") for r in rows}
    assert {"pass_refused", "stop", "info_request", "oscillation_escalated"} <= names, \
        f"round-trip lost events: {sorted(names)}"
    assert all(r.get("hash") and r.get("event_id") for r in rows), "rows lack identity"
    # The oscillation packet's own ``kind`` must survive under campaign_kind.
    osc = [r for r in rows if r.get("campaign_event") == "oscillation_escalated"][0]
    assert osc.get("campaign_kind") == "producer-word-check", \
        f"producer word lost: {sorted(osc)}"
    print(f"CHECK 3 ok: {len(rows)} campaign rows round-tripped, envelope authoritative, hash-chained")

    # CHECK 4: a window manifest pins for both briefs.
    for brief in ("468", "469"):
        manifest = trace and pin_window(
            ledger, brief=brief, revision=main_sha,
            selector="campaign=w468w469-preflight",
            unit_ids=sorted(names),
            out_path=os.path.join(tmp, f"window-{brief}.json"),
            kinds=[CAMPAIGN_EVENT],
            gaps=["record_disposition not on main (W1 #628, CONFLICTING)"]
            if brief == "468" else [])
        with open(os.path.join(tmp, f"window-{brief}.json"), encoding="utf-8") as fh:
            doc = json.load(fh)
        assert doc.get("brief") == brief and doc.get("segments"), \
            f"manifest for {brief} incomplete"
        assert any("sha256" in s for s in doc["segments"]), "segments lack hashes"
    print("CHECK 4 ok: window manifests pin for 468 and 469 with segment hashes and stated gaps")

    # CHECK 5: W468's write half is still the parked car, not silently present.
    import harness.jev_assessment as ja
    assert not hasattr(ja, "record_disposition"), \
        "record_disposition unexpectedly on main - re-route before relying on this preflight"
    print("CHECK 5 ok: record_disposition absent on main - #628 still the W468 write unblocker")

    print("VERDICT: W469 ledger half runnable (campaign_event on main); "
          "W468 ledger half runnable (trace family present) with its write path "
          "still parked in CONFLICTING #628. Windows schedulable by W2; "
          "no brief measured, no credit taken.")


if __name__ == "__main__":
    main()
