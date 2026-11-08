#!/usr/bin/env python3
"""CircleCI entry point for the driving-hygiene checks (#440).

scripts/driving_hygiene.py was written for GitHub Actions: it reads the
pull-request event payload (title, body, base SHA) from GITHUB_EVENT_PATH
and the head SHA from GITHUB_SHA. CircleCI has no event payload, so this
wrapper synthesizes an equivalent one from the checkout itself:

- base SHA: the merge-base of HEAD with origin/main; on main itself
  (merge-base == HEAD) the base is HEAD's parent, so a squash-merged
  PR's commit message -- which carries the PR title and body -- is what
  gets scanned there.
- PR text: the commit messages in base..HEAD. On a PR branch these are
  the PR's own commits; on main the single merge commit carries the
  PR text.

Deterministic, standard library only, no network calls beyond the git
fetch of origin/main that other jobs in this config already perform,
and no secrets -- the same contract as the checker itself.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import driving_hygiene


def _git(repo_root, *args):
    result = subprocess.run(
        ["git"] + list(args), cwd=str(repo_root),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout.strip()


def main():
    repo_root = Path(__file__).resolve().parents[1]
    head_sha = os.environ.get("CIRCLE_SHA1") or _git(repo_root, "rev-parse", "HEAD")
    _git(repo_root, "fetch", "origin", "main", "--quiet")
    base_sha = _git(repo_root, "merge-base", "origin/main", "HEAD")
    if base_sha == head_sha:
        base_sha = _git(repo_root, "rev-parse", "HEAD~1")
    pr_text = _git(repo_root, "log", "--format=%B%x1e",
                   "{}..{}".format(base_sha, head_sha))
    event = {"pull_request": {
        "base": {"sha": base_sha}, "title": "", "body": pr_text}}
    with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8") as handle:
        json.dump(event, handle)
        event_path = handle.name
    return driving_hygiene.main(
        repo_root=repo_root, event_path=event_path, head_sha=head_sha)


if __name__ == "__main__":
    raise SystemExit(main())
