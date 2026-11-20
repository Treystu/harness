"""Pair the two turn-15 runs into one receipt at the identified head.

`probe-turn15-default.json`   -- fresh process, no perception source declared.
`probe-turn15-configured.json` -- same head, DRIVER_DOM_URL declared (sources [dom]).

Both were produced by probe_turn15.py against main d916a7b with the served
routing files asserted byte-identical to that commit. Combining them keeps the
one fact that matters visible: which barrier the acting path stops at depends on
whether a source is declared, and the decision tier is only reachable in the
second case.
"""
import hashlib
import json
import pathlib

ROOT = pathlib.Path("evidence/lane-sessions/w2-2026-11-20")
OUT = ROOT / "probe-turn15.json"

runs = {}
for name in ("default", "configured"):
    path = ROOT / f"probe-turn15-{name}.json"
    runs[name] = json.loads(path.read_text(encoding="utf-8"))

head = runs["default"]["_meta"]["head_under_test"]
assert head == runs["configured"]["_meta"]["head_under_test"], "heads differ"
assert runs["default"]["_meta"]["all_routing_files_identical_to_head"] is True
assert runs["configured"]["_meta"]["all_routing_files_identical_to_head"] is True


def step(run, label):
    entry = run["413"]["step"][label]
    env = entry.get("envelope") or {}
    return {
        "status": entry["status"],
        "ok": env.get("ok"),
        "stopped_at": env.get("stopped_at"),
        "reason": env.get("reason"),
        "detail": env.get("detail"),
        "error": env.get("error"),
    }


table = []
for name, run in runs.items():
    table.append({
        "run": name,
        "sources": run["413"]["health"]["sources"],
        "keyed": run["413"]["health"]["keyed"],
        "vocabulary": {k: run["413"]["vocabulary_get"].get(k) for k in
                       ("status", "ok", "action_count", "executable_true",
                        "executable_false", "noauth_status")},
        "verify": run["413"]["verify_get"],
        "schemas": run["413"]["schemas_get"],
        "step_plain": step(run, "plain_step"),
        "step_turn13_body": step(run, "turn13_body"),
        "step_no_schema": step(run, "step_no_schema"),
        "step_action_only": step(run, "step_action_only"),
    })

out = {
    "_meta": {
        "head_under_test": head,
        "runs": {name: {"base": run["_meta"]["base"],
                        "checkout_head": run["_meta"]["checkout_head"],
                        "checkout_branch": run["_meta"]["checkout_branch"]}
                 for name, run in runs.items()},
        "served_routing_files": runs["configured"]["_meta"]["served_routing_files"],
        "all_routing_files_identical_to_head": True,
        "sha256": {name: hashlib.sha256((ROOT / f"probe-turn15-{name}.json")
                                        .read_bytes()).hexdigest()
                   for name in runs},
        "note": ("One harness process at a time. The driver service binds a fixed "
                 "endpoint (127.0.0.1:8791) with a token generated per start, so a "
                 "second concurrent harness reaches the first one's service and every "
                 "driver route answers 503 'driver service returned HTTP 401'. Both "
                 "runs above were taken with exactly one harness listening."),
    },
    "comparison": table,
    "default_run": runs["default"],
    "configured_run": runs["configured"],
}

OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(OUT, hashlib.sha256(OUT.read_bytes()).hexdigest()[:16])
for row in table:
    s = row["step_plain"]
    print(row["run"], "sources", row["sources"], "| vocab",
          row["vocabulary"]["status"], row["vocabulary"]["action_count"],
          "| verify", row["verify"]["status"], "| schemas",
          row["schemas"]["count"], "| step", s["status"], s["stopped_at"],
          s["reason"])
