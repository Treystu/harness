"""Retract the keyless-vocabulary intake row from main (docs only)."""
import base64
import json
import pathlib
import subprocess
import sys

GH = "repos/Treystu/harness"
BRANCH = "w2/retract-vocab-413"
TMP = pathlib.Path("evidence/lane-sessions/w2-2026-11-20/_retract413_payload.json")
SLUG = "`driver-vocabulary-keyless-claim-false`"

BODY = """Removes one row from the found-in-use index. No product code, no mechanism rule, no brief, bar or order change.

**Why.** That row said a path documented as keyless still ended at the keyed decision tier, citing `POST /api/driver/step` with `action: vocabulary` returning `decision_not_usable`. That probe could not measure vocabulary: at this head `_api_driver_step` (`harness/server.py:2567-2585`) never reads `action`, requires `target`, and always calls `adapter.step(...)`. The cited body carried `target` and `schema`, so it ran the decision pipeline. The turn-13 body and the same body with `action` deleted return byte-identical `decision_not_usable` envelopes, and `{"action": "vocabulary"}` alone is `400 field 'target' is required and must be a string` - the field is inert.

**What the keyless route returns.** Re-probed keyless with `DRIVER_DOM_URL` declared, health `keyed: false`, `sources: ["dom"]`:

| Surface | Result |
|---|---|
| `GET /api/driver/vocabulary` (owner token) | `200`, `ok: true`, 15 actions, 4 executable, 11 `refused_until_backend` |
| `GET /api/driver/vocabulary` (no token) | `401` |
| `GET /api/driver/verify` | `200`, `ok: true` |
| `GET /api/driver/schemas` | `200`, 3 schemas |
| `GET /api/driver/health` | `200`, `keyed: false` |

Every surface the health text calls keyless answers keyless, so the contract the row described does not exist. The keyless decision tier is already on the index as `driver-decision-tier-unkeyed` (#413), and this observation adds nothing to it - so the row is withdrawn rather than rewritten.

**Diff.** `docs/found-in-use.md`, one row and its separator removed: 15 -> 14 rows, em dashes unchanged, no mojibake, no other line touched. #413 stays OPEN and its verdict stays PARTIAL; the correction is filed on the issue (`413-correction-t14.md`).

Caught by the Codex review on #639 (`2026-11-19T14:40:17Z`), which named the exact routing split. Product Jev then Lucas Gate v2 receipt: `gates-turn14.json`.

Generated with Codebuff
Co-Authored-By: Codebuff <noreply@codebuff.com>
"""


def sh(args, text=True):
    r = subprocess.run(args, capture_output=True, text=text)
    if r.returncode != 0:
        print("FAIL", args[:3], (r.stderr or b"")[:900])
        sys.exit(1)
    return r.stdout


def api(path, method="GET", payload=None):
    args = ["gh", "api", "-X", method, f"{GH}/{path}"]
    if payload is not None:
        TMP.write_text(json.dumps(payload), encoding="utf-8")
        args += ["--input", str(TMP)]
    return json.loads(sh(args))


base = sh(["git", "rev-parse", "origin/main"]).strip()
print("base", base)
raw = sh(["git", "show", f"{base}:docs/found-in-use.md"], text=False)
text = raw.decode("utf-8")
assert "\u00e2\u20ac" not in text, "main carries mojibake - aborting"
assert SLUG in text, "row not present - nothing to retract"
assert SLUG.lower().count("driver-vocabulary-keyless-claim-false") == 1
before = sum(1 for ln in text.splitlines() if ln.startswith("| `"))
dashes = text.count("\u2014")

removed = [ln for ln in text.split("\n") if ln.startswith("| " + SLUG)]
assert len(removed) == 1, removed
row = removed[0]
# the row sits between two blank lines; drop it with one separator so the table
# keeps exactly one blank line before the next section
pattern = "\n\n" + row + "\n\n"
assert text.count(pattern) == 1, text.count(pattern)
text2 = text.replace(pattern, "\n\n")
after = sum(1 for ln in text2.splitlines() if ln.startswith("| `"))
print("rows", before, "->", after, "| em dashes", dashes, "->", text2.count("\u2014"))
assert after == before - 1
assert text2.count("\u2014") == dashes
assert "\n\n\n" not in text2

pathlib.Path("evidence/lane-sessions/w2-2026-11-20/found-in-use.retract-413.md").write_bytes(
    text2.encode("utf-8"))
assert BODY.encode("ascii", "replace").decode() == BODY, "body must be ASCII-safe"

blob = api("git/blobs", "POST",
           {"content": base64.b64encode(text2.encode("utf-8")).decode(),
            "encoding": "base64"})
tree = api("git/trees", "POST", {"base_tree": base, "tree": [
    {"path": "docs/found-in-use.md", "mode": "100644", "type": "blob",
     "sha": blob["sha"]}]})
commit = api("git/commits", "POST", {
    "message": "docs(intake): retract the keyless-vocabulary row (#413)\n\n"
               "The probe behind the row measured the decision tier, not the\n"
               "keyless vocabulary route; the claimed contract does not hold.\n"
               "Docs only: one row removed.\n",
    "tree": tree["sha"], "parents": [base]})
print("commit", commit["sha"])
api("git/refs", "POST", {"ref": f"refs/heads/{BRANCH}", "sha": commit["sha"]})
pr = api("pulls", "POST", {"title": "docs(intake): retract the keyless-vocabulary row (#413)",
                           "head": BRANCH, "base": "main", "body": BODY})
print("pr", pr["number"], pr["html_url"])
