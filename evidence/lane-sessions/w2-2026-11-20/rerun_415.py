"""#415 re-run after the provider spend ceiling cleared (daily reset).

Same bounded ask as the 2026-11-18 attempt, on the identified head now serving
on 127.0.0.1:8797. Records: predispatch spend, run id, terminal status, post
spend, and the ledger rows the run produced. The owner token is read from the
harness UI token store and never printed.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.abspath("."))

from harness.ui_auth import load_or_create_ui_token

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797"
OUT = sys.argv[2] if len(sys.argv) > 2 else "evidence/lane-sessions/w2-2026-11-20/415_rerun.json"
TOKEN = load_or_create_ui_token()

PROMPT = (
    "Research task: report the current MCP (Model Context Protocol) "
    "specification revision and the exact URL that publishes it. "
    "Cite the URL you used. Keep the answer short."
)


def req(path, data=None, method=None, timeout=60):
    body = json.dumps(data).encode() if data is not None else None
    r = urllib.request.Request(BASE + path, data=body, method=method or ("POST" if body is not None else "GET"))
    r.add_header("X-Harness-Auth", TOKEN)
    if body is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def jload(text):
    try:
        return json.loads(text)
    except Exception:
        return None


out = {"base": BASE, "prompt": PROMPT, "head": os.popen("git rev-parse HEAD").read().strip()}

st, body = req("/api/spend")
out["spend_before"] = jload(body) if st == 200 else {"http_status": st, "body": body[:400]}

st, body = req("/api/chat", {"prompt": PROMPT, "web": True})
out["submit_http_status"] = st
sub = jload(body) or {}
out["submit_body"] = sub
run_id = sub.get("id")
if not run_id:
    out["error"] = "no run id returned"
    open(OUT, "w", encoding="utf-8").write(json.dumps(out, indent=2, sort_keys=True))
    print(json.dumps({k: out[k] for k in ("submit_http_status", "error")}, indent=2))
    raise SystemExit(1)

out["run_id"] = run_id
final = None
deadline = time.time() + 900
while time.time() < deadline:
    st, body = req("/api/runs/" + run_id)
    doc = jload(body) or {}
    run = doc.get("run", doc)
    status = str(run.get("status") or "")
    if status and status not in ("running", "queued", "pending"):
        final = run
        break
    time.sleep(10)

out["run"] = final or {"status": "timeout"}
st, body = req("/api/spend")
out["spend_after"] = jload(body) if st == 200 else {"http_status": st, "body": body[:400]}

open(OUT, "w", encoding="utf-8").write(json.dumps(out, indent=2, sort_keys=True))
print(json.dumps({
    "run_id": run_id,
    "status": (final or {}).get("status"),
    "error_kind": (final or {}).get("error_kind"),
    "error": str((final or {}).get("error"))[:200],
    "known_cost_usd": (final or {}).get("known_cost_usd"),
    "result_chars": len(json.dumps((final or {}).get("result") or "")),
    "spend_before": out["spend_before"],
    "spend_after": out["spend_after"],
}, indent=2)[:3000])
