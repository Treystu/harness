"""W2 turn-13 probes: #567 log surfaces and #413 driver round-trip.

Runs against an already-serving harness on 127.0.0.1:8797. The owner token is
read from the harness UI token store and never printed. Records HTTP codes,
payload shapes and the driver's own refusal/response text verbatim.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.abspath("."))

from harness.ui_auth import load_or_create_ui_token

BASE = "http://127.0.0.1:8797"
TOKEN = load_or_create_ui_token()
OUT = "evidence/lane-sessions/w2-2026-11-20/probe-turn13.json"


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


def brief(text, limit=400):
    try:
        return json.loads(text)
    except Exception:
        return text[:limit]


out = {"_meta": {"base": BASE, "head_from_serve_log": "see serve-8797-turn13.log"}}

# ---- #567: the four log surfaces, authenticated and unauthenticated ----------
surfaces = {}
for name, path in (
    ("sessions", "/api/chat/sessions"),
    ("history", "/api/chat/history"),
    ("ledger_tail", "/api/ledger/tail?n=3"),
    ("status", "/api/status"),
):
    code, text = req(path)
    code_noauth, text_noauth = req(path, auth=False)
    payload = brief(text)
    item = {"auth_status": code, "noauth_status": code_noauth}
    if isinstance(payload, dict):
        item["keys"] = sorted(payload.keys())
        if name == "status":
            item["value"] = {k: payload.get(k) for k in
                             ("auth_required", "events_buffered", "run_count",
                              "recovered_count")}
        elif name == "ledger_tail":
            rows = payload.get("entries") or payload.get("rows") or payload
            if isinstance(rows, list):
                item["rows"] = len(rows)
                if rows:
                    item["row_keys"] = sorted(rows[0].keys())
                    item["first_event"] = rows[0].get("event")
        elif name == "sessions":
            items = payload.get("sessions") or payload.get("items") or []
            item["count"] = len(items) if isinstance(items, list) else None
        elif name == "history":
            items = payload.get("turns") or payload.get("history") or payload.get("items") or []
            item["count"] = len(items) if isinstance(items, list) else None
            if isinstance(items, list) and items:
                item["turn_keys"] = sorted(items[0].keys())
    else:
        item["text"] = text[:300]
    surfaces[name] = item
out["567"] = surfaces

# ---- #413: driver health, then one read_dom round-trip ----------------------
driver = {}
code, text = req("/api/driver/start", {}, timeout=120)
driver["start"] = {"status": code, "body": brief(text)}
code, text = req("/api/driver/health")
driver["health"] = {"status": code, "body": brief(text)}

for label, payload in (
    ("read_dom", {"schema": "dom", "target": BASE + "/", "action": "read_dom"}),
    ("vocabulary", {"schema": "dom", "target": BASE + "/", "action": "vocabulary"}),
    ("no_schema", {"target": BASE + "/", "action": "read_dom"}),
):
    code, text = req("/api/driver/step", payload, timeout=120)
    driver[label] = {"status": code, "body": brief(text, 1200)}
    time.sleep(1)

code, text = req("/api/driver/stop", {}, timeout=60)
driver["stop"] = {"status": code, "body": brief(text)}
out["413"] = driver

with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
    fh.write(json.dumps(out, indent=2))

print(json.dumps({k: (v if k != "567" else {kk: {x: vv for x, vv in vv.items() if x != "text"} for kk, vv in v.items()}) for k, v in out.items() if k != "_meta"}, indent=2)[:4000])
print("written", OUT)
