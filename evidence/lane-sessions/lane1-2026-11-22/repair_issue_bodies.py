"""Repair the issue bodies that were created from a JSON payload file.

`gh issue create --body-file` posts the file verbatim, so the issues created from
.issue-body.json carry the {"title": ..., "body": ...} envelope as their body.
The envelope holds the intended markdown, so the repair reads the body back,
unwraps it and edits the issue with the plain text.
"""
import json
import pathlib
import subprocess

NUMS = (list(range(768, 775)) + list(range(775, 786)) + list(range(786, 789)))


def gh(*args):
    res = subprocess.run(("gh",) + args, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    return res.returncode, res.stdout, res.stderr


fixed, skipped, failed = [], [], []
for n in NUMS:
    rc, out, err = gh("issue", "view", str(n), "--repo", "Treystu/harness",
                      "--json", "body")
    if rc != 0 or not out.strip():
        print(n, "READ FAILED", err[-120:])
        failed.append(n)
        continue
    body = json.loads(out)["body"]
    if not body.lstrip().startswith("{"):
        print(n, "already plain")
        skipped.append(n)
        continue
    inner = json.loads(body)
    pathlib.Path(".fix-body.md").write_text(inner["body"], encoding="utf-8")
    rc, out, err = gh("issue", "edit", str(n), "--repo", "Treystu/harness",
                      "--body-file", ".fix-body.md")
    if rc == 0:
        print(n, "repaired", inner["title"])
        fixed.append(n)
    else:
        print(n, "EDIT FAILED", err[-140:])
        failed.append(n)

print("repaired", len(fixed), "already-plain", len(skipped), "failed", failed)
