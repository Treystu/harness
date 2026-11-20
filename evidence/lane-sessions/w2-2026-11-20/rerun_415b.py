"""#415 re-run on the $0 primary lane (allow_paid=false) after the daily reset.

Same ask and the same GUI entry point as the 2026-11-18 attempt; the only
change is the lane, because the paid route still refuses with HTTP 402 while
OpenRouter's /key surface reports a full remaining balance.
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
OUT = "evidence/lane-sessions/w2-2026-11-20/415_rerun_free_lane.json"
TOKEN = load_or_create_ui_token()
PROMPT = (
    "Research task: report the current MCP (Model Context Protocol) "
    "specification revision and the exact URL that publishes it. "
    "Cite the URL you used. Keep the answer short."
)


def req(path, data=None):
    body = json.dumps(data).encode() if data is not None else None
    r = urllib.request.Request(BASE + path, data=body,
                               method="POST" if body is not None else "GET")
    r.add_header("X-Harness-Auth", TOKEN)
    if body is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def jload(t):
    try:
        return json.loads(t)
    except Exception:
        return None


out = {"base": BASE, "prompt": PROMPT, "lane": "allow_paid=false",
       "head": os.popen("git rev-parse HEAD").read().strip()}
st, b = req("/api/spend")
out["spend_before"] = jload(b)
st, b = req("/api/chat", {"prompt": PROMPT, "web": True, "allow_paid": False})
out["submit_http_status"] = st
sub = jload(b) or {}
out["submit_body"] = sub
run_id = sub.get("id")
out["run_id"] = run_id
final = None
if run_id:
    deadline = time.time() + 1500
    while time.time() < deadline:
        st, b = req("/api/run/" + run_id) if False else req("/api/runs/" + run_id + "/result")
        doc = jload(b) or {}
        status = str(doc.get("status") or "")
        if status and status not in ("running", "queued", "pending"):
            final = doc
            break
        time.sleep(10)
out["run"] = final or {"status": "timeout"}
st, b = req("/api/spend")
out["spend_after"] = jload(b)
with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=2, sort_keys=True)
print(json.dumps({
    "run_id": run_id,
    "submit": st,
    "status": (final or {}).get("status"),
    "error_kind": (final or {}).get("error_kind"),
    "error": str((final or {}).get("error"))[:200],
    "known_cost_usd": (final or {}).get("known_cost_usd"),
    "result": (final or {}).get("result"),
}, indent=2)[:4000])
