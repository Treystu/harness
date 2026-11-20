"""Zero-spend credits probe for W2 LIVE-API blockers (#422/#567/#413, #415).

Reads the same key the harness uses via harness.config.load_settings and calls
OpenRouter's /api/v1/key endpoint, which reports limit/usage and costs nothing.
Prints only credit fields; the key itself is never read into the output.
"""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.abspath("."))

from harness.config import resolve_api_key_with_source, OPENROUTER_KEY_URL

key, source = resolve_api_key_with_source()
if not key:
    print(json.dumps({"probe": "openrouter_key", "error": "no key resolved from config sources"}))
    raise SystemExit(0)

req = urllib.request.Request(
    OPENROUTER_KEY_URL,
    headers={"Authorization": "Bearer %s" % key},
)
out = {"probe": "openrouter_key", "url": OPENROUTER_KEY_URL,
       "key_source_kind": (source or {}).get("kind")}
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        out["http_status"] = resp.status
        payload = json.loads(resp.read().decode("utf-8", "replace"))
except urllib.error.HTTPError as exc:
    out["http_status"] = exc.code
    out["body_excerpt"] = exc.read().decode("utf-8", "replace")[:300]
    payload = None
except Exception as exc:  # network/TLS
    out["error"] = type(exc).__name__ + ": " + str(exc)[:200]
    payload = None

if isinstance(payload, dict):
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    keep = {}
    for k, v in data.items():
        if any(t in k.lower() for t in ("limit", "usage", "credit", "free", "rate")):
            keep[k] = v
    out["credit_fields"] = keep

print(json.dumps(out, indent=2, sort_keys=True))
