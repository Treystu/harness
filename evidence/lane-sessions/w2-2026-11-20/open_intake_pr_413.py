"""Open the intake PR for driver-vocabulary-keyless-claim-false on current main."""
import base64
import json
import pathlib
import subprocess
import sys

GH = "repos/Treystu/harness"
BRANCH = "w2/intake-413-vocabulary"
TMP = pathlib.Path("evidence/lane-sessions/w2-2026-11-20/_intake413_payload.json")

ROW = (
    "| `driver-vocabulary-keyless-claim-false` | 2026-11-20 | `6ea96c29` | #413 | "
    "open - medium: with a DOM source declared the driver's health text still says "
    "health/verify/vocabulary are \"intentionally keyless\", yet `action: vocabulary` "
    "returns `decision_not_usable` at `stopped_at: decision` with `keyed: false`, so a "
    "path promised not to need a key is gated on the keyed decision tier |"
)

BODY = """Adds one row to the found-in-use index. No product code, no mechanism rule, no brief, bar or order change.

**`driver-vocabulary-keyless-claim-false`** (#413, observed at `6ea96c29`, product code identical to `main` `4618b5f9`).

At the verification head the driver was started with `DRIVER_DOM_URL=http://127.0.0.1:8797/` declared, and its health reported `sources: ["dom"]`, `keyed: false`, plus the in-process text "health, verify and vocabulary are intentionally keyless". `POST /api/driver/step` with `action: vocabulary` then returned 200 with `ok: false`, `reason: decision_not_usable`, `stopped_at: decision`, `cost_usd: 0.0`. The same call with `action: read_dom` stops at the same stage.

Distinct from `driver-decision-tier-unkeyed` (#413, 2026-11-18): that row records that decisions need a key; this one records that a path documented as keyless still ends at the keyed decision stage.

Dedupe run against the open row set; owner left to #413. Evidence: `413-result-t13.md`, `probe-turn13.json`, `gates-turn13.json` under `evidence/lane-sessions/w2-2026-11-20/`. Product decision on whether vocabulary should bypass the decision tier (owner #413).

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
assert "driver-vocabulary-keyless-claim-false" not in text, "row already present"
assert ROW.isascii()
before = sum(1 for ln in text.splitlines() if ln.startswith("| `"))
dashes = text.count("\u2014")

anchor = "\n## Transfer entry (#451)"
assert text.count(anchor) == 1
text = text.replace(anchor, "\n" + ROW + "\n" + anchor)
text = text.replace("\r\n", "\n").replace("\r", "\n")
after = sum(1 for ln in text.splitlines() if ln.startswith("| `"))
print("rows", before, "->", after, "| em dashes", dashes, "->", text.count("\u2014"))
assert after == before + 1 and text.count("\u2014") == dashes

pathlib.Path("evidence/lane-sessions/w2-2026-11-20/found-in-use.intake-413.md").write_bytes(
    text.encode("utf-8"))

blob = api("git/blobs", "POST",
           {"content": base64.b64encode(text.encode("utf-8")).decode(),
            "encoding": "base64"})
tree = api("git/trees", "POST", {"base_tree": base, "tree": [
    {"path": "docs/found-in-use.md", "mode": "100644", "type": "blob",
     "sha": blob["sha"]}]})
commit = api("git/commits", "POST", {
    "message": "docs(intake): file the keyless-vocabulary contract gap (#413)\n\n"
               "Records only: one row, no product code, no rule change.\n",
    "tree": tree["sha"], "parents": [base]})
print("commit", commit["sha"])
code = subprocess.run(["gh", "api", "-X", "POST", f"{GH}/git/refs",
                       "-f", f"ref=refs/heads/{BRANCH}", "-f", f"sha={commit['sha']}"],
                      capture_output=True, text=True)
print("ref:", code.returncode, (code.stdout or code.stderr)[:120])
pr = api("pulls", "POST", {"title": "docs(intake): file the keyless-vocabulary "
                                    "contract gap (#413)",
                           "head": BRANCH, "base": "main", "body": BODY,
                           "draft": False})
print("PR", pr["number"], pr["html_url"], pr["head"]["sha"])
