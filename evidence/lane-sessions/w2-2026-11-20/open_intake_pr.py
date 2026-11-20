"""Open the intake PR for `campaign-trace-writer-unwired` on current main.

Reads docs/found-in-use.md as BYTES from origin/main (no locale decode), inserts
one row, asserts no mojibake, LF-normalises, and commits one file on a new
branch. No product code.
"""
import base64
import json
import pathlib
import subprocess
import sys

GH = "repos/Treystu/harness"
BRANCH = "w2/intake-469-trace-writer"
ROOT = pathlib.Path(".")
TMP = pathlib.Path("evidence/lane-sessions/w2-2026-11-20/_intake_payload.json")

ROW = (
    "| `campaign-trace-writer-unwired` | 2026-11-20 | `17906e2c` | #469 | "
    "open - high: `harness/flush_loop.py:392-396` forwards each campaign event "
    "to `DecisionTrace.campaign_event` only when a writer is injected, and no "
    "product call site injects one (`flush_loop.py:1261-1262`, `:1050`, `:1056`); "
    "the writer is green only because `tests/test_decision_trace_469.py:235-236` "
    "constructs it by hand, so #627's campaign retention is inert in use |\n"
)

BODY = """Adds one row to the found-in-use index. No product code, no mechanism rule, no brief, bar or order change.

**`campaign-trace-writer-unwired`** (#469, observed at `17906e2c`).

`harness/decision_trace.py::DecisionTrace.campaign_event` and the forwarding block at `harness/flush_loop.py:392-396` are reachable only when an `EventLedger` is constructed with a `trace` writer. At `17906e2c` the campaign CLI entry builds the ledger bare (`harness/flush_loop.py:1261-1262`), as do the canary paths (`:1050`, `:1056`). The only construction that injects a writer is `tests/test_decision_trace_469.py:235-236`, which is why the 16/16 rail at `ec664518` is green while the default path stays silent.

Consequence: campaign events still reach only `<campaign>.events.jsonl`. This is distinct from `flush-campaign-ledgers-uncommitted` (#623, observed at `699f677`): that row records that no archive exists; this one records that the archive which landed in #627 is not wired to its producer.

Dedupe run against the open row set; owner left to #469. Evidence: `469-rerun-at-17906e2c.md` (W469 re-run attempt, no completion credit), `469-intake-row.md` (classification), `gates-rerun.json` (product Jev `escalate`/proceed, then Lucas Gate v2 `pass`), all under `evidence/lane-sessions/w2-2026-11-20/`.

🤖 Generated with Codebuff
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


base_sha = sh(["git", "rev-parse", "origin/main"]).strip()
print("base", base_sha)

raw = sh(["git", "show", f"{base_sha}:docs/found-in-use.md"], text=False)
text = raw.decode("utf-8")
# main still carries #631's mojibake in older rows until #635 lands; that is
# #635's cure, not this PR's. This PR must ADD nothing but one clean row.
assert "campaign-trace-writer-unwired" not in text, "row already present"
assert "\u00e2\u20ac" not in ROW, "the row itself carries mojibake"
assert ROW.isascii(), "the row must be ASCII"

anchor = "\n## Transfer entry (#451)"
assert text.count(anchor) == 1, "transfer anchor not unique"
text = text.replace(anchor, "\n" + ROW.rstrip("\n") + "\n" + anchor)
text = text.replace("\r\n", "\n").replace("\r", "\n")
assert "\u2014" in text, "expected the file's existing em dashes to survive"
added = [ln for ln in text.splitlines() if "campaign-trace-writer-unwired" in ln]
assert added == [ROW.rstrip("\n")] and ROW.count("\n") == 1

out = ROOT / "evidence/lane-sessions/w2-2026-11-20/found-in-use.intake.md"
out.write_bytes(text.encode("utf-8"))
print("rows:", sum(1 for line in text.splitlines() if line.startswith("| `")),
      "| bytes:", len(text.encode("utf-8")))

blob = api("git/blobs", "POST",
           {"content": base64.b64encode(text.encode("utf-8")).decode(),
            "encoding": "base64"})
tree = api("git/trees", "POST", {"base_tree": base_sha, "tree": [
    {"path": "docs/found-in-use.md", "mode": "100644", "type": "blob",
     "sha": blob["sha"]}]})
commit = api("git/commits", "POST", {
    "message": "docs(intake): file the unwired campaign trace writer (#469)\n\n"
               "Records only: no product code, no rule change, no credit.\n",
    "tree": tree["sha"], "parents": [base_sha]})
print("commit", commit["sha"])

try:
    api(f"git/refs/heads/{BRANCH}", "POST",
        {"ref": f"refs/heads/{BRANCH}", "sha": commit["sha"]})
    print("ref created")
except SystemExit:
    api(f"git/refs/heads/{BRANCH}", "PATCH",
        {"sha": commit["sha"], "force": True})
    print("ref updated")

pr = api("pulls", "POST", {
    "title": "docs(intake): file the unwired campaign trace writer (#469)",
    "head": BRANCH, "base": "main", "body": BODY, "draft": False})
print("PR", pr["number"], pr["html_url"])
