"""RSI Build 2 - the epoch workspace manager (plan section 5).

An epoch runs in a throwaway workspace: a branch in the canonical repo
(``iteration/selfimprove-<epoch>``) plus a dedicated clone created fresh from
the epoch head SHA and discarded at epoch end. This module owns the mechanics
and the credential boundary:

- CREATE: clone from the named SHA, branch the iteration branch there, and set
  a mode-local commit identity inside the clone (never the operator's).
- HOLD: push to its own branch only, open the epoch PR as a draft at the
  epoch's first commit, file issues - nothing else.
- NOT HOLD: merge, frozen-path writes, or any credential beyond the loop's
  scoped grant. A diff touching a frozen path (plan section 4) is refused here
  and routed to the outside seat instead.
- DISCARD: the clone goes away only when nothing in it is the only copy of
  anything - clean tree, local head equal to the pushed branch.

The scoped token itself is the owner's reserved act (the plan's filing names the
fine-grained PAT and its allowlist). :func:`validate_grant` checks the grant that
token produces rather than asking for the token, so the build is complete to
that last step instead of parked on it.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .completion_spec import FROZEN_SPEC_PATHS
from .errors import HarnessError
from .osal import run as _osal_run, write_text as _write_text

BRANCH_PREFIX = "iteration/selfimprove-"
DEFAULT_ROOT = "tmp/rsi-epochs"
DEFAULT_BASE = "main"

# Commit identity inside an epoch clone. Attributable to the mode, never to the
# operator whose token created the clone.
EPOCH_IDENTITY_NAME = "Harness RSI Epoch"
EPOCH_IDENTITY_EMAIL = "rsi-epoch@harness.invalid"

# What the clone holds (plan section 5). Stated as data so the receipt records
# the same words the plan rules, and so the grant is checked against the same
# list rather than a second copy of it.
GRANT_REQUIRED: Dict[str, str] = {
    "contents": "write",
    "pull_requests": "write",
    "issues": "write",
}

HELD_CAPABILITIES: Tuple[str, ...] = (
    "contents:write on its iteration branch",
    "pull_requests:create",
    "issues:write",
)
FORBIDDEN_CAPABILITIES: Tuple[str, ...] = (
    "merge",
    "administration",
    "workflows",
    "secrets",
    "frozen_path_write",
)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_REPO_RE = re.compile(r"^[^/\s]+/[^/\s]+$")
# A PR body must never carry a close keyword: the merge belongs to the outside
# seat (plan section 9), so nothing but that seat closes an item.
_CLOSE_KEYWORD_RE = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b\s*:?\s*#\d+", re.IGNORECASE)

Runner = Callable[[Sequence[str], Optional[str]], Any]


def _default_run(argv: Sequence[str], cwd: Optional[str] = None):
    return _osal_run(list(argv), cwd=cwd)


def _output(result: Any) -> str:
    text = getattr(result, "combined", None)
    if text is None:
        text = str(getattr(result, "stdout", "") or "") + str(
            getattr(result, "stderr", "") or "")
    return text.strip()


def _require(result: Any, what: str) -> Any:
    code = getattr(result, "returncode", 1)
    if code != 0:
        detail = _output(result)
        raise HarnessError(f"{what} failed (exit {code})" + (f": {detail}" if detail else ""))
    return result


def _tail(text: str, limit: int = 400) -> str:
    text = text.strip()
    return text if len(text) <= limit else "..." + text[-limit:]


def epoch_slug(epoch: str) -> str:
    """The epoch's directory name. Refused rather than repaired: a slug is data
    other filenames and branch names are built from."""
    slug = str(epoch or "").strip().lower()
    if not _SLUG_RE.match(slug):
        raise HarnessError(
            f"epoch name {epoch!r} is not a slug (lowercase letters, digits and "
            "dashes, at most 63 characters)")
    return slug


def iteration_branch(epoch: str) -> str:
    """``iteration/selfimprove-<epoch>`` - the one branch the clone may push."""
    return BRANCH_PREFIX + epoch_slug(epoch)


def validate_head_sha(head_sha: str) -> str:
    """The epoch pins to a named SHA, so a short or symbolic name is refused."""
    sha = str(head_sha or "").strip().lower()
    if not _SHA_RE.match(sha):
        raise HarnessError(
            f"epoch head {head_sha!r} is not a full 40-character commit SHA")
    return sha


def validate_grant(grant: Mapping[str, Any], *, repo: str) -> Dict[str, Any]:
    """Check the scoped grant the clone runs under (plan section 5).

    ``grant`` is what the owner's fine-grained token produces: ``allowlist``
    (repository names it can reach) and ``permissions`` (name -> level). The
    clone may reach exactly this repo; it may write contents, issues and pull
    requests; it may not merge, administer, touch workflows or secrets, or write
    a frozen path.
    """
    if not isinstance(grant, Mapping):
        raise HarnessError("grant must be a mapping with allowlist and permissions")
    allowlist = grant.get("allowlist")
    if not isinstance(allowlist, (list, tuple)) or not allowlist:
        raise HarnessError("grant.allowlist must name the repositories the token reaches")
    allowed = [str(item).strip() for item in allowlist if str(item).strip()]
    extra = [item for item in allowed if item.lower() != str(repo).strip().lower()]
    if extra:
        raise HarnessError(
            "grant reaches repositories outside the epoch's one repo: "
            + ", ".join(extra))
    if len(allowed) != 1:
        raise HarnessError(
            "grant allowlist must contain exactly " + str(repo) + ", found "
            + str(len(allowed)))
    permissions = grant.get("permissions")
    if not isinstance(permissions, Mapping) or not permissions:
        raise HarnessError("grant.permissions must be a mapping of capability -> level")
    normalised = {str(k).strip().lower(): str(v).strip().lower()
                  for k, v in permissions.items()}
    for forbidden in FORBIDDEN_CAPABILITIES:
        if normalised.get(forbidden, "none") not in ("none", "", "read"):
            raise HarnessError(
                f"grant holds {forbidden}, which the epoch clone must never hold")
    for name, level in GRANT_REQUIRED.items():
        if normalised.get(name, "none") != level:
            raise HarnessError(
                f"grant is missing {name}:{level} (the clone cannot do its own "
                "work without it)")
    unknown = [name for name in normalised
               if name not in GRANT_REQUIRED
               and name not in FORBIDDEN_CAPABILITIES]
    if unknown:
        raise HarnessError(
            "grant carries capabilities the mode does not hold: " + ", ".join(unknown))
    return {"allowlist": allowed, "permissions": normalised}


@dataclass
class EpochWorkspace:
    """One epoch's throwaway clone. Not a live process: a record of where it is
    and what it may do."""

    epoch: str
    head_sha: str
    branch: str
    path: Path
    remote: str
    base: str = DEFAULT_BASE
    pushed: bool = False
    discarded: bool = False
    pr_url: str = ""
    pr_head: str = ""
    grant: Dict[str, Any] = field(default_factory=dict)

    @property
    def slug(self) -> str:
        return self.path.name


def _git(ws: "EpochWorkspace", args: Sequence[str], runner: Optional[Runner] = None):
    run = runner or _default_run
    return run(["git"] + [str(a) for a in args], str(ws.path))


def create_workspace(epoch: str, head_sha: str, *, remote: str,
                     root: str = DEFAULT_ROOT, base: str = DEFAULT_BASE,
                     runner: Optional[Runner] = None) -> EpochWorkspace:
    """Clone the epoch head into a fresh directory and branch from it.

    The clone is ``--no-checkout`` first and then checked out at the named SHA,
    so the workspace is pinned to the epoch head and never inherits whatever the
    remote's default branch has moved to since.
    """
    branch = iteration_branch(epoch)
    sha = validate_head_sha(head_sha)
    slug = epoch_slug(epoch)
    if not str(remote or "").strip():
        raise HarnessError("an epoch workspace needs a remote to clone from")
    root_path = Path(root)
    path = root_path / slug
    if path.exists():
        raise HarnessError(
            f"epoch workspace already exists at {path}: a clone is created fresh "
            "per epoch and never reused (discard it or pick another epoch name)")
    root_path.mkdir(parents=True, exist_ok=True)
    _require((runner or _default_run)(
        ["git", "clone", "--quiet", "--no-checkout", "--", str(remote), str(path)],
        None), f"clone of {remote}")
    ws = EpochWorkspace(epoch=slug, head_sha=sha, branch=branch, path=path,
                        remote=str(remote), base=base)
    _require(_git(ws, ["checkout", "--quiet", "-B", branch, sha], runner),
            f"checkout of {sha}")
    head = _require(_git(ws, ["rev-parse", "HEAD"], runner), "read of the clone head")
    actual = (getattr(head, "stdout", "") or "").strip()
    if actual != sha:
        raise HarnessError(
            f"epoch clone sits at {actual or 'nothing'}, not the named head {sha}")
    _require(_git(ws, ["config", "user.name", EPOCH_IDENTITY_NAME], runner),
            "set of the epoch commit identity")
    _require(_git(ws, ["config", "user.email", EPOCH_IDENTITY_EMAIL], runner),
            "set of the epoch commit email")
    return ws


def _safe_relative(path: str) -> str:
    text = str(path or "").strip().replace("\\", "/")
    if not text:
        raise HarnessError("a committed path must not be empty")
    candidate = Path(text)
    if candidate.is_absolute() or text.startswith("/") or ":" in text.split("/")[0]:
        raise HarnessError(f"committed path {path!r} must be relative to the clone")
    if ".." in candidate.parts:
        raise HarnessError(f"committed path {path!r} escapes the clone")
    if candidate.parts and candidate.parts[0] == ".git":
        raise HarnessError(f"committed path {path!r} writes into .git")
    normalised = "/".join(candidate.parts)
    if normalised in FROZEN_SPEC_PATHS or any(
            normalised == frozen or normalised.startswith(frozen + "/")
            for frozen in FROZEN_SPEC_PATHS):
        raise HarnessError(
            f"committed path {path!r} is in the frozen zone: the clone has no "
            "frozen-path write access (plan section 4)")
    return normalised


def commit_paths(ws: EpochWorkspace, files: Mapping[str, str], message: str, *,
                 runner: Optional[Runner] = None) -> str:
    """Write the given files into the clone and commit them as one change.

    This is how the epoch's first commit exists at all: the draft PR opens at
    that commit, so a workspace that cannot produce one is not an epoch.
    """
    if not files:
        raise HarnessError("a commit needs at least one file")
    text = str(message or "").strip()
    if not text:
        raise HarnessError("a commit needs a message")
    written: List[str] = []
    for raw_path, content in files.items():
        rel = _safe_relative(raw_path)
        target = ws.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_text(target, str(content), newline="\n")
        written.append(rel)
    _require(_git(ws, ["add", "--"] + written, runner), "staging of the epoch change")
    _require(_git(ws, ["commit", "--quiet", "-m", text], runner), "epoch commit")
    head = _require(_git(ws, ["rev-parse", "HEAD"], runner), "read of the epoch commit")
    return (getattr(head, "stdout", "") or "").strip()


def commits_ahead(ws: EpochWorkspace, *, runner: Optional[Runner] = None) -> int:
    """How many commits the iteration branch carries past the epoch head."""
    result = _require(_git(ws, ["rev-list", "--count", f"{ws.head_sha}..{ws.branch}"],
                          runner), "count of epoch commits")
    raw = (getattr(result, "stdout", "") or "").strip()
    try:
        return int(raw or "0")
    except ValueError:
        raise HarnessError(
            f"git reported a non-numeric commit count: {raw!r}") from None


def changed_paths(ws: EpochWorkspace, *, runner: Optional[Runner] = None) -> List[str]:
    result = _require(_git(ws, ["diff", "--name-only", f"{ws.head_sha}..{ws.branch}"],
                          runner), "diff of the epoch branch")
    return [line.strip() for line in (getattr(result, "stdout", "") or "").splitlines()
            if line.strip()]


def frozen_paths_in_diff(ws: EpochWorkspace, *,
                         runner: Optional[Runner] = None) -> List[str]:
    """Frozen-zone paths the epoch branch touches - the loop may not promote it."""
    return [path for path in changed_paths(ws, runner=runner)
            if path in FROZEN_SPEC_PATHS or any(
                path.startswith(frozen + "/") for frozen in FROZEN_SPEC_PATHS)]


def _remote_branch_sha(ws: EpochWorkspace, runner: Optional[Runner] = None) -> str:
    result = _require(_git(ws, ["ls-remote", "--heads", "origin", ws.branch], runner),
                     "read of the remote iteration branch")
    for line in (getattr(result, "stdout", "") or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].endswith(ws.branch):
            return parts[0].strip()
    return ""


def push_iteration_branch(ws: EpochWorkspace, *,
                          runner: Optional[Runner] = None) -> EpochWorkspace:
    """Push the iteration branch, and nothing else.

    The refspec is fixed to ``<branch>:<branch>``: no force, no other branch, no
    tags. Afterwards the remote branch must carry the clone's head - a push that
    reports success while the remote disagrees is not a push.
    """
    if ws.discarded:
        raise HarnessError("the epoch workspace was discarded; nothing left to push")
    _require(_git(ws, ["push", "--quiet", "origin", f"{ws.branch}:{ws.branch}"], runner),
            "push of the iteration branch")
    head = _require(_git(ws, ["rev-parse", "HEAD"], runner), "read of the epoch head")
    local = (getattr(head, "stdout", "") or "").strip()
    remote = _remote_branch_sha(ws, runner)
    if not remote:
        raise HarnessError(f"origin does not carry {ws.branch} after the push")
    if remote != local:
        raise HarnessError(
            f"origin carries {remote} on {ws.branch} but the clone is at {local}: "
            "the epoch's work is not published")
    ws.pushed = True
    return ws


def open_epoch_pr(ws: EpochWorkspace, *, title: str, body_path: str, repo: str,
                  base: Optional[str] = None,
                  runner: Optional[Runner] = None) -> EpochWorkspace:
    """Open the epoch PR as a draft at the epoch's first commit.

    Refusals are the boundary, not friction: no PR before the branch is on
    origin, no PR once the branch carries more than its first commit (the PR
    must show the epoch from its start), no PR whose diff touches a frozen path,
    and no PR body carrying a close keyword - promotion is the outside seat's
    act (plan section 9).
    """
    run = runner or _default_run
    if not _REPO_RE.match(str(repo or "").strip()):
        raise HarnessError(f"repo {repo!r} is not owner/name")
    repo = str(repo).strip()
    heading = str(title or "").strip()
    if not heading:
        raise HarnessError("the epoch PR needs a title")
    body_file = Path(body_path)
    if not body_file.is_file():
        raise HarnessError(f"the epoch PR body file {body_path} does not exist")
    body_text = body_file.read_text(encoding="utf-8")
    if not body_text.strip():
        raise HarnessError("the epoch PR body is empty")
    match = _CLOSE_KEYWORD_RE.search(body_text)
    if match:
        raise HarnessError(
            "the epoch PR body carries a close keyword "
            f"({match.group(0)!r}): merge authority is the outside seat's, so the "
            "loop never closes an item by PR text")
    if not ws.pushed:
        raise HarnessError(
            "the epoch PR opens only after the branch is pushed: the work is "
            "visible on canonical from the start")
    frozen = frozen_paths_in_diff(ws, runner=runner)
    if frozen:
        raise HarnessError(
            "the epoch diff touches frozen paths (" + ", ".join(frozen)
            + "): excluded from loop promotion and routed to the outside seat")
    ahead = commits_ahead(ws, runner=runner)
    if ahead != 1:
        raise HarnessError(
            f"the epoch draft PR opens at the epoch's first commit; the branch "
            f"carries {ahead} commits past {ws.head_sha}")
    existing = run(["gh", "pr", "list", "--repo", repo, "--head", ws.branch,
                    "--state", "open", "--json", "url", "--limit", "1"], None)
    if getattr(existing, "returncode", 1) == 0:
        try:
            rows = json.loads(getattr(existing, "stdout", "") or "[]")
        except ValueError:
            raise HarnessError(
                "gh pr list returned no JSON; refusing to open a second PR blindly"
            ) from None
        if isinstance(rows, list) and rows:
            url = str(rows[0].get("url", "")).strip()
            if url:
                ws.pr_url = url
                ws.pr_head = ws.head_sha
                return ws
    created = run(["gh", "pr", "create", "--draft", "--repo", repo,
                   "--base", str(base or ws.base), "--head", ws.branch,
                   "--title", heading, "--body-file", str(body_file)], None)
    _require(created, "epoch draft PR creation")
    lines = [line.strip() for line in
             (getattr(created, "stdout", "") or "").splitlines() if line.strip()]
    url = lines[-1] if lines else ""
    if not url.startswith("https://"):
        raise HarnessError(
            f"gh pr create did not report a PR URL (got {_tail(url) or 'nothing'})")
    head = _require(_git(ws, ["rev-parse", "HEAD"], runner), "read of the epoch head")
    ws.pr_url = url
    ws.pr_head = (getattr(head, "stdout", "") or "").strip()
    return ws


def _remove_tree(path: Path) -> None:
    """Remove a clone, including git's read-only objects (Windows refuses them).

    A clone is disposable, but only after it is empty of unique work - which the
    caller has already established. Read-only bits are cleared per path and the
    removal retried, rather than reporting a failure the caller cannot act on.
    """

    def _retry(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    shutil.rmtree(path, **{"onexc": _retry} if sys.version_info >= (3, 12)
                  else {"onerror": _retry})


def discard_workspace(ws: EpochWorkspace, *,
                      runner: Optional[Runner] = None) -> Dict[str, Any]:
    """Remove the clone - only when nothing in it is the only copy of anything."""
    if ws.discarded:
        return workspace_receipt(ws)
    if not (ws.path / ".git").exists():
        raise HarnessError(
            f"{ws.path} is not an epoch clone (no .git): refusing to remove it")
    status = _require(_git(ws, ["status", "--porcelain"], runner),
                     "read of the epoch tree state")
    dirty = [line for line in (getattr(status, "stdout", "") or "").splitlines()
             if line.strip()]
    if dirty:
        raise HarnessError(
            f"the epoch clone has uncommitted work ({len(dirty)} path(s)); a clone "
            "is never discarded while it holds the only copy")
    if not ws.pushed:
        raise HarnessError(
            "the epoch clone has never been pushed; a clone is never discarded "
            "while it holds the only copy")
    head = _require(_git(ws, ["rev-parse", "HEAD"], runner), "read of the epoch head")
    local = (getattr(head, "stdout", "") or "").strip()
    remote = _remote_branch_sha(ws, runner)
    if remote != local:
        raise HarnessError(
            f"the clone is at {local} but origin carries {remote or 'nothing'} on "
            f"{ws.branch}: unpushed work is at-risk work")
    _remove_tree(ws.path)
    ws.discarded = True
    return workspace_receipt(ws)


def workspace_receipt(ws: EpochWorkspace) -> Dict[str, Any]:
    """The epoch workspace record, ready to file."""
    return {
        "epoch": ws.epoch,
        "branch": ws.branch,
        "head_sha": ws.head_sha,
        "base": ws.base,
        "path": str(ws.path),
        "remote": ws.remote,
        "pushed": ws.pushed,
        "pr_url": ws.pr_url,
        "pr_head": ws.pr_head,
        "discarded": ws.discarded,
        "held": list(HELD_CAPABILITIES),
        "forbidden": list(FORBIDDEN_CAPABILITIES),
        "grant_checked": bool(ws.grant),
        "grant": ws.grant or None,
    }


def epoch_marker(epoch: str, head_sha: str, branch: str) -> str:
    """Text for the epoch's first commit, so the draft PR is never empty."""
    return (f"RSI epoch {epoch}\n\nhead: {head_sha}\nbranch: {branch}\n"
            "Created by the epoch workspace manager (plan section 5).\n")


def run_epoch_workspace(epoch: str, head_sha: str, *, remote: str,
                        root: str = DEFAULT_ROOT, base: str = DEFAULT_BASE,
                        repo: Optional[str] = None, pr_title: Optional[str] = None,
                        pr_body: Optional[str] = None,
                        first_commit_file: Optional[str] = None,
                        first_commit_message: Optional[str] = None,
                        discard: bool = False,
                        runner: Optional[Runner] = None) -> Dict[str, Any]:
    """Create the epoch workspace, publish its first commit, and discard it.

    The sequence is the plan's: fresh clone from the named SHA, the epoch's first
    commit pushed to the iteration branch, the draft PR opened at that commit,
    then the clone discarded. Discarding is last on purpose - the clone is
    disposable only once the PR shows its work on canonical.
    """
    ws = create_workspace(epoch, head_sha, remote=remote, root=root, base=base,
                          runner=runner)
    try:
        if bool(first_commit_file) != bool(first_commit_message):
            raise HarnessError(
                "--first-commit-file and --first-commit-message go together")
        if first_commit_file:
            commit_paths(ws, {str(first_commit_file): epoch_marker(
                ws.epoch, ws.head_sha, ws.branch)},
                str(first_commit_message), runner=runner)
        push_iteration_branch(ws, runner=runner)
        if repo:
            if not pr_title or not pr_body:
                raise HarnessError(
                    "opening the epoch PR needs --pr-title and --pr-body")
            open_epoch_pr(ws, title=str(pr_title), body_path=str(pr_body),
                          repo=repo, base=base, runner=runner)
        if discard:
            discard_workspace(ws, runner=runner)
    except HarnessError:
        # The clone stays where it is: nothing is deleted on a failed step, so a
        # failed run is inspectable and retryable instead of silently gone.
        raise
    return workspace_receipt(ws)
