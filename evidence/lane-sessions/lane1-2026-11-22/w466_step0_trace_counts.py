"""#466 STEP 0: two independent counts of decision traces, on what can run here.

Part A - a LIVE decision-gate call through the product seam the CLI faces use
(`jev_face_governor` -> `policy_for` -> real ledger). This makes a real Jev
model call. It is measured as it behaves: the gate itself persists nothing,
because persistence belongs to its callers.

Part B - the persistence seam those callers use, driven through the real CLI
(`harness assess --trace-ledger`, the same `record_disposition` call site at
`harness/cli.py`). Count 1 is the writer's own answer (the printed event_id);
count 2 is the shared reader over the ledger; count 3 is a raw line scan that
does not use the reader. All three must agree and the chain must verify.

The live *brief* run the order asks for is NOT claimed: this machine resolves
only a Jev key (`api_key`, `openrouter_api_key`, `typesafe_api_key` are all
None), so no brief or plan run can reach a model. That gap is reported, not
papered over - see `live_brief_run` in the report.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.abspath("."))

from harness.config import load_settings  # noqa: E402
from harness.decision_trace import DecisionTrace, read_trace_events  # noqa: E402
from harness.jev_policy import policy_for  # noqa: E402
from harness.ledger import AutonomyLedger  # noqa: E402
from harness.session import jev_face_governor, ledger_for  # noqa: E402

BRIEF = pathlib.Path(
    "evidence/lane-sessions/lane1-2026-11-22/filings/295-pass19-checkin.md"
).read_text(encoding="utf-8")
GOAL = ("Ship verified harness changes through the review gates without "
        "unapproved destructive action.")
QUESTION = "Gate the pass-19 filing for accuracy and scope"

PAYLOAD = {"aspects": {
    "completeness": {"probabilities": {"85-89": 0.09, "<85": 0.03, ">=90": 0.88}},
    "confidence": {"probabilities": {"85-89": 0.11, "<85": 0.03, ">=90": 0.86}},
    "correctness": {"probabilities": {"85-89": 0.07, "<85": 0.03, ">=90": 0.90}},
    "no_regression": {"probabilities": {"85-89": 0.12, "<85": 0.04, ">=90": 0.84}},
    "evidence_quality": {"probabilities": {"85-89": 0.06, "<85": 0.03, ">=90": 0.91}},
}}


def _counts(ledger_path, ledger):
    rows = read_trace_events(ledger)
    raw = [json.loads(line) for line in
           pathlib.Path(ledger_path).read_text(encoding="utf-8").splitlines()
           if line.strip()]
    return rows, [r for r in raw if r.get("event") == "decision_trace"]


def part_a(tmp):
    settings = load_settings()
    settings.ledger_path = str(tmp / "a-ledger.jsonl")
    gov = jev_face_governor(settings)
    ledger = ledger_for(settings, caller="lane1-w466-step0")
    policy = policy_for(settings, governor=gov, ledger=ledger)
    emitted = []

    original = DecisionTrace.record

    def counting(self, kind, **kwargs):
        row = original(self, kind, **kwargs)
        emitted.append(row.get("event_id"))
        return row

    DecisionTrace.record = counting
    try:
        verdict, state = policy.evaluate_decision(
            BRIEF, GOAL, QUESTION, site="w466-step0")
    finally:
        DecisionTrace.record = original
    rows, raw = _counts(settings.ledger_path, ledger)
    return {
        "kind": "live decision-gate call (real Jev model call)",
        "site": "w466-step0",
        "verdict": verdict.get("verdict"),
        "disposition": verdict.get("disposition"),
        "supported": state.get("supported"),
        "in_memory_writer_calls": len(emitted),
        "reader_rows": len(rows),
        "raw_file_scan_rows": len(raw),
        "finding": ("the gate persists nothing itself; persistence belongs to "
                    "its callers (apply_policy, escalation, jev_assessment)"),
    }


def part_b(tmp):
    ledger_path = tmp / "b-ledger.jsonl"
    payload_path = tmp / "payload.json"
    payload_path.write_text(json.dumps(PAYLOAD), encoding="utf-8")
    written = []
    exits = []
    for n in (1, 2):
        proc = subprocess.run(
            [sys.executable, "-m", "harness.cli", "assess",
             "--input", str(payload_path), "--trace-ledger", str(ledger_path),
             "--subject", f"w466-step0-persist-{n}"],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        exits.append(proc.returncode)
        written.append((json.loads(proc.stdout).get("trace") or {}).get("event_id"))
    ledger = AutonomyLedger(str(ledger_path), caller="lane1-w466-step0")
    rows, raw = _counts(ledger_path, ledger)
    wrote = [w for w in written if w]
    ids_agree = (set(wrote) == {r["event_id"] for r in rows}
                 == {r["event_id"] for r in raw})
    chained = (all(r.get("prev_hash") == (raw[i - 1].get("hash") if i else None)
                   for i, r in enumerate(raw)))
    return {
        "kind": "harness assess --trace-ledger, run twice (product persist seam)",
        "exit": exits,
        "verdict": "both runs wrote",
        "counts": {
            "writer_answer": len(wrote),
            "reader_rows": len(rows),
            "raw_file_scan_rows": len(raw),
            "all_three_agree": len(wrote) == len(rows) == len(raw) == 2,
            "event_ids_agree": ids_agree,
        },
        "kinds": sorted({r.get("kind") for r in rows}),
        "seq": [r.get("seq") for r in raw],
        "prev_hash_linked": chained,
        "chain_verified": bool(ledger.verify()),
        "rows": [{k: r.get(k) for k in
                  ("kind", "seq", "event_id", "hash", "prev_hash", "subject_id")}
                 for r in raw],
    }


def main() -> int:
    settings = load_settings()
    keys = {"jev_api_key": bool(getattr(settings, "jev_api_key", None)),
            "api_key": bool(getattr(settings, "api_key", None)),
            "openrouter_api_key": bool(getattr(settings, "openrouter_api_key", None)),
            "typesafe_api_key": bool(getattr(settings, "typesafe_api_key", None))}
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="w466-step0-"))
    a = part_a(tmp)
    b = part_b(tmp)
    report = {
        "live_brief_run": {
            "performed": False,
            "why": ("no model provider key resolves on this machine; only the "
                    "Jev key is set, so a brief or plan run cannot reach a "
                    "model. The order's live brief run is NOT claimed."),
            "keys_resolved": keys,
        },
        "part_a_live_gate": a,
        "part_b_persistence": b,
        "verdict": ("persistence counts agree on the product seam"
                    if b["counts"]["all_three_agree"] and b["chain_verified"]
                    and b["counts"]["event_ids_agree"] else "MISMATCH"),
    }
    out = pathlib.Path("evidence/lane-sessions/lane1-2026-11-22/"
                       "filings/466-step0-trace-counts.json")
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    ok = (report["verdict"].startswith("persistence")
          and b["prev_hash_linked"] and b["chain_verified"]
          and a["in_memory_writer_calls"] == 0)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
