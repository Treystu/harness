"""W2 turn-15 probe: keyless driver surfaces re-run at the identified head.

Turn 14 rendered its receipt from a working tree at cdc72fde (product identity
04fb1cd0). main has since moved to d916a7b (#640, docs only). This probe binds
the same observations to d916a7b and records, per file, that the served routing
code is byte-identical to that commit -- so the receipt names its head without
depending on which branch the checkout happens to be on.

No product code is read for anything but hashing; nothing is written to the repo
outside this evidence directory.
"""
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.abspath("."))

from harness.ui_auth import load_or_create_ui_token

BASE = os.environ.get("W2_BASE", "http://127.0.0.1:8799")
TOKEN = load_or_create_ui_token()
OUT = os.environ.get("W2_OUT",
                     "evidence/lane-sessions/w2-2026-11-20/probe-turn15.json")
ROUTING = ("harness/server.py", "driver_core/server.py", "driver_core/driver.py")


def rev(ref):
    return subprocess.run(["git", "rev-parse", ref], capture_output=True,
                          text=True).stdout.strip()


def blob(ref, path):
    return subprocess.run(["git", "show", f"{ref}:{path}"], capture_output=True).stdout


def file_identity(main):
    """Compare the on-disk routing files with the commit under test, byte for byte."""
    out = {}
    for path in ROUTING:
        disk = open(path, "rb").read()
        want = blob(main, path)
        out[path] = {
            "disk_sha256": hashlib.sha256(disk).hexdigest(),
            "head_sha256": hashlib.sha256(want).hexdigest(),
            "identical": disk == want,
        }
    return out


def req(path, data=None, method=None, timeout=90, auth=True):
    body = json.dumps(data).encode() if data is not None else None
    r = urllib.request.Request(BASE + path, data=body,
                               method=method or ("POST" if body else "GET"))
    if auth:
        r.add_header("X-Harness-Auth", TOKEN)
    if body is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def as_json(text, limit=1200):
    try:
        return json.loads(text)
    except Exception:
        return text[:limit]


main = rev("origin/main")
identity = file_identity(main)
out = {"_meta": {
    "base": BASE,
    "checkout_branch": subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                                      capture_output=True, text=True).stdout.strip(),
    "checkout_head": rev("HEAD"),
    "head_under_test": main,
    "served_routing_files": identity,
    "all_routing_files_identical_to_head": all(v["identical"] for v in identity.values()),
}}

routes = {}
code, text = req("/api/driver/start", {}, timeout=120)
routes["start"] = {"status": code, "body": as_json(text)}

code, text = req("/api/driver/health")
health = as_json(text)
routes["health"] = {
    "status": code,
    "keyed": health.get("keyed") if isinstance(health, dict) else None,
    "sources": health.get("sources") if isinstance(health, dict) else None,
    "key_provisioning": (health.get("key_provisioning") or {}).get("state")
    if isinstance(health, dict) else None,
    "health_detail": (health.get("key_provisioning") or {}).get("detail")
    if isinstance(health, dict) else None,
}

code, text = req("/api/driver/vocabulary")
vocab = as_json(text)
item = {"status": code}
if isinstance(vocab, dict):
    v = vocab.get("vocabulary") or {}
    actions = v.get("actions") or []
    item["keys"] = sorted(vocab.keys())
    item["ok"] = vocab.get("ok")
    item["vocabulary_keys"] = sorted(v.keys()) if isinstance(v, dict) else None
    item["action_count"] = len(actions) if isinstance(actions, list) else None
    if isinstance(actions, list) and actions:
        item["first_action"] = actions[0]
        item["executable_true"] = sum(1 for a in actions
                                      if isinstance(a, dict) and a.get("executable"))
        item["executable_false"] = sum(1 for a in actions
                                       if isinstance(a, dict) and a.get("executable") is False)
else:
    item["text"] = str(vocab)[:600]
code_noauth, _ = req("/api/driver/vocabulary", auth=False)
item["noauth_status"] = code_noauth
routes["vocabulary_get"] = item

code, text = req("/api/driver/verify")
verify = as_json(text)
routes["verify_get"] = {
    "status": code,
    "ok": verify.get("ok") if isinstance(verify, dict) else None,
    "keys": sorted(verify.keys()) if isinstance(verify, dict) else None,
}

code, text = req("/api/driver/schemas")
schemas = as_json(text)
routes["schemas_get"] = {
    "status": code,
    "count": len((schemas.get("schemas") or [])) if isinstance(schemas, dict) else None,
}

# The turn-13 body and its neighbours, unchanged from turn 14 so the two
# receipts are directly comparable.
step = {}
for label, payload in (
    ("turn13_body", {"schema": "dom", "target": BASE + "/", "action": "vocabulary"}),
    ("plain_step", {"schema": "dom", "target": BASE + "/"}),
    ("step_no_schema", {"target": BASE + "/", "action": "read_dom"}),
    ("step_action_only", {"action": "vocabulary"}),
):
    code, text = req("/api/driver/step", payload, timeout=120)
    body = as_json(text)
    entry = {"request": payload, "status": code}
    if isinstance(body, dict):
        entry["envelope"] = {k: body.get(k) for k in
                             ("ok", "reason", "stopped_at", "cost_usd", "keyed",
                              "detail", "error")}
    else:
        entry["text"] = str(body)[:400]
    step[label] = entry
routes["step"] = step

out["413"] = routes

with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
    fh.write(json.dumps(out, indent=2, sort_keys=True) + "\n")

print(OUT)
print("head_under_test", main, "| routing identical:",
      out["_meta"]["all_routing_files_identical_to_head"])
for k, v in routes.items():
    print("--", k, json.dumps(v)[:400])
