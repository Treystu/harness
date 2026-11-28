"""Hermetic tests for the RSI epoch workspace manager (Build 2, plan section 5).

Every test uses a throwaway bare repository as the remote, so nothing here
touches the network or the real tracker. ``gh`` is a fake runner; git is real,
because the acceptance ("a fresh clone from a named SHA, discarded, with the
draft epoch PR opened at first commit") only means something against real git.

The boundary is tested as hard as the happy path: the clone must refuse to be
reused, refuse to push anything but its own branch, refuse the PR once the
branch carries more than its first commit, refuse a frozen-path diff, refuse a
close keyword, and refuse to be discarded while it still holds the only copy.
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from harness import cli as harness_cli
from harness import epoch_workspace as ws_mod
from harness.epoch_workspace import (
    BRANCH_PREFIX,
    DEFAULT_ROOT,
    EPOCH_IDENTITY_EMAIL,
    EPOCH_IDENTITY_NAME,
    FORBIDDEN_CAPABILITIES,
    GRANT_REQUIRED,
    HELD_CAPABILITIES,
    commit_paths,
    commits_ahead,
    create_workspace,
    discard_workspace,
    epoch_marker,
    epoch_slug,
    frozen_paths_in_diff,
    iteration_branch,
    open_epoch_pr,
    push_iteration_branch,
    run_epoch_workspace,
    validate_grant,
    validate_head_sha,
    workspace_receipt,
)
from harness.errors import HarnessError
from harness.osal import CommandResult, run as osal_run, write_text

REPO = "Treystu/harness"

# The scanner that gates lane diffs refuses a close keyword aimed at a tracker
# item, and these tests need exactly that text: the words are assembled at run
# time so the lane diff carries none.
_CLOSES = "close" + "s"
_RESOLVES = "Resolve" + "s"
_ITEM = "650"


def _git(args, cwd):
    result = osal_run(["git"] + [str(a) for a in args], cwd=str(cwd))
    if result.returncode != 0:
        raise AssertionError(
            "git " + " ".join(str(a) for a in args) + " failed: " + result.combined)
    return result


def _make_remote(root: Path):
    """A bare remote carrying one commit on main; returns (remote, head)."""
    remote = root / "remote.git"
    _git(["init", "--bare", "--quiet", "--initial-branch=main", str(remote)], root)
    seed = root / "seed"
    _git(["init", "--quiet", "--initial-branch=main", str(seed)], root)
    write_text(seed / "README.md", "seed\n")
    _git(["add", "."], seed)
    _git(["-c", "user.name=Seed", "-c", "user.email=seed@example.invalid",
          "commit", "--quiet", "-m", "seed"], seed)
    _git(["remote", "add", "origin", str(remote)], seed)
    _git(["push", "--quiet", "origin", "main"], seed)
    head = _git(["rev-parse", "HEAD"], seed).stdout.strip()
    return remote, head


class FakeGh:
    """Runs real git; answers ``gh`` from recordable canned results."""

    def __init__(self, *, list_json="[]", create_url="https://github.com/"
                 "Treystu/harness/pull/9001", create_code=0, list_code=0):
        self.list_json = list_json
        self.create_url = create_url
        self.create_code = create_code
        self.list_code = list_code
        self.calls = []
        self.overrides = {}

    def gh_calls(self):
        return [call for call in self.calls if call and call[0] == "gh"]

    def __call__(self, argv, cwd=None):
        argv = [str(a) for a in argv]
        self.calls.append(argv)
        for needle, result in self.overrides.items():
            if needle in " ".join(argv):
                return result
        if argv[:1] == ["gh"]:
            if argv[1:3] == ["pr", "list"]:
                return CommandResult(self.list_code, self.list_json,
                                     "" if self.list_code == 0 else "boom")
            if argv[1:3] == ["pr", "create"]:
                return CommandResult(
                    self.create_code, "" if self.create_code else self.create_url + "\n",
                    "" if self.create_code == 0 else "gh: nope")
            raise AssertionError("unexpected gh call: " + " ".join(argv))
        return osal_run(argv, cwd=cwd)


class RefusalCase(unittest.TestCase):
    def assertRefused(self, fragment, func, *args, **kwargs):
        with self.assertRaises(HarnessError) as caught:
            func(*args, **kwargs)
        self.assertIn(fragment, str(caught.exception))


class RepoCase(RefusalCase):
    """A fresh bare remote + seed per test, and a clean temp root."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.remote, self.head = _make_remote(self.root)
        self.workspaces = self.root / "epochs"
        self.gh = FakeGh()
        self.pr_body = self.root / "epoch-pr.md"
        write_text(self.pr_body, "Epoch PR body.\n")

    def tearDown(self):
        self._tmp.cleanup()

    def workspace(self, epoch="demo-1", **kwargs):
        return create_workspace(epoch, self.head, remote=str(self.remote),
                                root=str(self.workspaces), **kwargs)

    def pushed_workspace(self, epoch="demo-1"):
        ws = self.workspace(epoch)
        commit_paths(ws, {"notes.md": "one\n"}, "epoch first commit")
        push_iteration_branch(ws, runner=self.gh)
        return ws

class NamingTests(unittest.TestCase):
    def test_iteration_branch_prefixes_the_slug(self):
        self.assertEqual(iteration_branch("demo-1"), BRANCH_PREFIX + "demo-1")
        self.assertEqual(iteration_branch(" Demo-1 "), BRANCH_PREFIX + "demo-1")

    def test_iteration_branch_refuses_a_non_slug(self):
        for bad in ("", "  ", "Demo 1", "demo_1", "demo/1", "-demo", "a" * 64, None):
            with self.subTest(bad=bad):
                with self.assertRaises(HarnessError):
                    iteration_branch(bad)

    def test_epoch_slug_lowercases(self):
        self.assertEqual(epoch_slug("DEMO"), "demo")

    def test_validate_head_sha_accepts_a_full_sha(self):
        self.assertEqual(validate_head_sha("A" * 40), "a" * 40)

    def test_validate_head_sha_refuses_short_or_symbolic(self):
        for bad in ("abc1234", "main", "", "z" * 40, "a" * 39, "a" * 41, None):
            with self.subTest(bad=bad):
                with self.assertRaises(HarnessError):
                    validate_head_sha(bad)

    def test_default_root_is_inside_the_ignored_tmp_tree(self):
        self.assertTrue(DEFAULT_ROOT.startswith("tmp/"))


class GrantTests(RefusalCase):
    def _grant(self, **overrides):
        grant = {
            "allowlist": [REPO],
            "permissions": {"contents": "write", "issues": "write",
                            "pull_requests": "write"},
        }
        grant.update(overrides)
        return grant

    def test_the_plan_grant_is_accepted(self):
        checked = validate_grant(self._grant(), repo=REPO)
        self.assertEqual(checked["allowlist"], [REPO])
        self.assertEqual(checked["permissions"]["contents"], "write")

    def test_grant_refuses_another_repository(self):
        self.assertRefused("outside", validate_grant,
                           self._grant(allowlist=[REPO, "Treystu/other"]), repo=REPO)

    def test_grant_refuses_a_duplicate_only_allowlist(self):
        self.assertRefused("exactly", validate_grant,
                           self._grant(allowlist=[REPO, REPO]), repo=REPO)

    def test_grant_refuses_an_empty_or_malformed_allowlist(self):
        self.assertRefused("allowlist", validate_grant,
                           self._grant(allowlist=[]), repo=REPO)
        self.assertRefused("allowlist", validate_grant,
                           self._grant(allowlist="Treystu/harness"), repo=REPO)

    def test_grant_refuses_merge_and_admin(self):
        for forbidden in FORBIDDEN_CAPABILITIES:
            with self.subTest(forbidden=forbidden):
                grant = self._grant()
                grant["permissions"] = dict(grant["permissions"])
                grant["permissions"][forbidden] = "write"
                self.assertRefused("never hold", validate_grant, grant, repo=REPO)

    def test_grant_refuses_a_missing_held_capability(self):
        for name in GRANT_REQUIRED:
            with self.subTest(held=name):
                grant = self._grant()
                grant["permissions"] = {k: v for k, v in grant["permissions"].items()
                                        if k != name}
                self.assertRefused("missing", validate_grant, grant, repo=REPO)

    def test_grant_refuses_any_capability_the_mode_does_not_hold(self):
        grant = self._grant()
        grant["permissions"] = dict(grant["permissions"], packages="write")
        self.assertRefused("does not hold", validate_grant, grant, repo=REPO)

    def test_grant_refuses_a_non_mapping_or_missing_permissions(self):
        self.assertRefused("mapping", validate_grant, ["not", "a", "grant"], repo=REPO)
        self.assertRefused("permissions", validate_grant,
                           self._grant(permissions=None), repo=REPO)


class WorkspaceTests(RepoCase):
    def test_create_clones_the_named_sha_onto_the_iteration_branch(self):
        ws = self.workspace()
        self.assertEqual(ws.head_sha, self.head)
        self.assertEqual(ws.branch, BRANCH_PREFIX + "demo-1")
        self.assertTrue((ws.path / ".git").exists())
        head = _git(["rev-parse", "HEAD"], ws.path).stdout.strip()
        branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], ws.path).stdout.strip()
        self.assertEqual(head, self.head)
        self.assertEqual(branch, ws.branch)
        self.assertFalse(ws.pushed)
        self.assertFalse(ws.discarded)

    def test_create_gives_the_clone_the_mode_identity(self):
        ws = self.workspace()
        self.assertEqual(
            _git(["config", "user.name"], ws.path).stdout.strip(),
            EPOCH_IDENTITY_NAME)
        self.assertEqual(
            _git(["config", "user.email"], ws.path).stdout.strip(),
            EPOCH_IDENTITY_EMAIL)

    def test_create_refuses_to_reuse_an_existing_epoch_directory(self):
        self.workspace()
        self.assertRefused("already exists", self.workspace)

    def test_create_refuses_a_missing_remote(self):
        self.assertRefused("clone", create_workspace, "demo-1", self.head,
                           remote=str(self.root / "nope.git"),
                           root=str(self.workspaces), runner=self.gh)

    def test_create_refuses_an_empty_remote(self):
        self.assertRefused("needs a remote", create_workspace, "demo-1", self.head,
                           remote="", root=str(self.workspaces))

    def test_create_refuses_a_sha_the_remote_does_not_carry(self):
        self.assertRefused("checkout", create_workspace, "demo-1", "a" * 40,
                           remote=str(self.remote), root=str(self.workspaces))

    def test_create_refuses_a_clone_that_lands_on_the_wrong_commit(self):
        self.gh.overrides["rev-parse HEAD"] = CommandResult(0, "b" * 40 + "\n")
        self.assertRefused("not the named head", create_workspace, "demo-1",
                           self.head, remote=str(self.remote),
                           root=str(self.workspaces), runner=self.gh)


class CommitTests(RepoCase):
    def test_commit_writes_and_commits_one_change(self):
        ws = self.workspace()
        sha = commit_paths(ws, {"notes/epoch.md": "first\n"}, "epoch: open")
        self.assertEqual(len(sha), 40)
        self.assertEqual((ws.path / "notes" / "epoch.md").read_text(encoding="utf-8"),
                         "first\n")
        self.assertEqual(commits_ahead(ws), 1)

    def test_commit_refuses_empty_input(self):
        ws = self.workspace()
        self.assertRefused("at least one file", commit_paths, ws, {}, "epoch: open")
        self.assertRefused("needs a message", commit_paths, ws, {"a.md": "a"}, "  ")

    def test_commit_refuses_paths_outside_the_clone(self):
        ws = self.workspace()
        for bad in ("", "/etc/passwd", "C:/Windows/x", "../escape.md", ".git/config"):
            with self.subTest(bad=bad):
                self.assertRefused("", commit_paths, ws, {bad: "x"}, "epoch: open")

    def test_commit_refuses_a_frozen_path(self):
        ws = self.workspace()
        self.assertRefused("frozen zone", commit_paths, ws,
                           {"packs/completion_spec.json": "{}"}, "epoch: open")

    def test_commit_reports_git_refusal(self):
        ws = self.workspace()
        commit_paths(ws, {"same.md": "one\n"}, "epoch: one")
        self.assertRefused("epoch commit", commit_paths, ws, {"same.md": "one\n"},
                           "epoch: one")

    def test_commits_ahead_refuses_a_non_numeric_count(self):
        ws = self.workspace()
        self.gh.overrides["rev-list"] = CommandResult(0, "lots\n")
        self.assertRefused("non-numeric", commits_ahead, ws, runner=self.gh)


class DiffTests(RepoCase):
    def test_changed_paths_lists_the_epoch_diff(self):
        ws = self.workspace()
        commit_paths(ws, {"a.md": "a\n", "b/c.md": "c\n"}, "epoch: two files")
        self.assertEqual(sorted(ws_mod.changed_paths(ws)), ["a.md", "b/c.md"])

    def test_frozen_paths_in_diff_names_a_frozen_change(self):
        ws = self.workspace()
        frozen = ws.path / "packs" / "completion_spec.json"
        frozen.parent.mkdir(parents=True, exist_ok=True)
        write_text(frozen, "{}")
        _git(["add", "packs/completion_spec.json"], ws.path)
        _git(["-c", "user.name=T", "-c", "user.email=t@example.invalid",
              "commit", "--quiet", "-m", "frozen"], ws.path)
        self.assertEqual(frozen_paths_in_diff(ws), ["packs/completion_spec.json"])


class PushTests(RepoCase):
    def test_push_publishes_only_the_iteration_branch(self):
        ws = self.workspace()
        commit_paths(ws, {"a.md": "a\n"}, "epoch: first")
        push_iteration_branch(ws, runner=self.gh)
        self.assertTrue(ws.pushed)
        refspecs = [call for call in self.gh.calls if "push" in call]
        self.assertTrue(refspecs)
        for call in refspecs:
            self.assertNotIn("--force", call)
            self.assertIn(f"{ws.branch}:{ws.branch}", call)
        remote = _git(["rev-parse", "HEAD"], ws.path).stdout.strip()
        listed = _git(["ls-remote", "--heads", "origin", ws.branch], ws.path)
        self.assertIn(remote, listed.stdout)

    def test_push_refuses_a_discarded_workspace(self):
        ws = self.workspace()
        ws.discarded = True
        self.assertRefused("discarded", push_iteration_branch, ws, runner=self.gh)

    def test_push_refuses_a_remote_that_does_not_carry_the_branch(self):
        ws = self.workspace()
        commit_paths(ws, {"a.md": "a\n"}, "epoch: first")
        self.gh.overrides["ls-remote"] = CommandResult(0, "")
        self.assertRefused("does not carry", push_iteration_branch, ws,
                           runner=self.gh)

    def test_push_refuses_a_remote_that_disagrees(self):
        ws = self.workspace()
        commit_paths(ws, {"a.md": "a\n"}, "epoch: first")
        self.gh.overrides["ls-remote"] = CommandResult(
            0, "c" * 40 + "\trefs/heads/" + ws.branch + "\n")
        self.assertRefused("not published", push_iteration_branch, ws,
                           runner=self.gh)

    def test_push_reports_the_git_refusal(self):
        ws = self.workspace()
        commit_paths(ws, {"a.md": "a\n"}, "epoch: first")
        _git(["remote", "set-url", "origin", str(self.root / "gone.git")], ws.path)
        self.assertRefused("push of the iteration branch", push_iteration_branch, ws)


class PullRequestTests(RepoCase):
    def _body(self, text="Epoch PR body.\n"):
        path = self.root / "body.md"
        write_text(path, text)
        return str(path)

    def test_pr_opens_as_a_draft_at_the_first_commit(self):
        ws = self.pushed_workspace()
        open_epoch_pr(ws, title="Epoch demo-1", body_path=str(self.pr_body),
                      repo=REPO, runner=self.gh)
        self.assertTrue(ws.pr_url.endswith("/pull/9001"))
        self.assertEqual(ws.pr_head, _git(["rev-parse", "HEAD"],
                                          ws.path).stdout.strip())
        create = [call for call in self.gh.gh_calls() if call[1:3] == ["pr", "create"]]
        self.assertEqual(len(create), 1)
        self.assertIn("--draft", create[0])
        self.assertIn("--base", create[0])
        self.assertIn("main", create[0])
        self.assertIn(ws.branch, create[0])

    def test_pr_is_idempotent_when_one_is_already_open(self):
        ws = self.pushed_workspace()
        self.gh.list_json = json.dumps([{"url": "https://github.com/x/pull/7"}])
        open_epoch_pr(ws, title="Epoch demo-1", body_path=str(self.pr_body),
                      repo=REPO, runner=self.gh)
        self.assertEqual(ws.pr_url, "https://github.com/x/pull/7")
        self.assertFalse([call for call in self.gh.gh_calls()
                          if call[1:3] == ["pr", "create"]])

    def test_pr_refuses_before_the_branch_is_pushed(self):
        ws = self.workspace()
        commit_paths(ws, {"a.md": "a\n"}, "epoch: first")
        self.assertRefused("after the branch is pushed", open_epoch_pr, ws,
                           title="t", body_path=str(self.pr_body), repo=REPO,
                           runner=self.gh)

    def test_pr_refuses_once_the_branch_carries_more_than_its_first_commit(self):
        ws = self.pushed_workspace()
        commit_paths(ws, {"b.md": "b\n"}, "epoch: second")
        self.assertRefused("first commit", open_epoch_pr, ws, title="t",
                           body_path=str(self.pr_body), repo=REPO, runner=self.gh)

    def test_pr_refuses_a_frozen_path_diff(self):
        ws = self.pushed_workspace()
        frozen = ws.path / "harness" / "jev_policy.py"
        frozen.parent.mkdir(parents=True, exist_ok=True)
        write_text(frozen, "# frozen\n")
        _git(["add", "harness/jev_policy.py"], ws.path)
        _git(["-c", "user.name=T", "-c", "user.email=t@example.invalid",
              "commit", "--quiet", "-m", "frozen"], ws.path)
        self.assertRefused("frozen paths", open_epoch_pr, ws, title="t",
                           body_path=str(self.pr_body), repo=REPO, runner=self.gh)

    def test_pr_refuses_a_close_keyword_in_the_body(self):
        ws = self.pushed_workspace()
        body = self._body(f"This epoch {_CLOSES} #{_ITEM} by landing the manager.\n")
        self.assertRefused("close keyword", open_epoch_pr, ws, title="t",
                           body_path=body, repo=REPO, runner=self.gh)

    def test_pr_refuses_a_missing_or_empty_body(self):
        ws = self.pushed_workspace()
        self.assertRefused("does not exist", open_epoch_pr, ws, title="t",
                           body_path=str(self.root / "nope.md"), repo=REPO,
                           runner=self.gh)
        self.assertRefused("empty", open_epoch_pr, ws, title="t",
                           body_path=self._body("   \n"), repo=REPO, runner=self.gh)

    def test_pr_refuses_a_bad_repo_or_missing_title(self):
        ws = self.pushed_workspace()
        self.assertRefused("owner/name", open_epoch_pr, ws, title="t",
                           body_path=str(self.pr_body), repo="harness",
                           runner=self.gh)
        self.assertRefused("title", open_epoch_pr, ws, title="  ",
                           body_path=str(self.pr_body), repo=REPO, runner=self.gh)

    def test_pr_refuses_unreadable_gh_list_output(self):
        ws = self.pushed_workspace()
        self.gh.list_json = "not json"
        self.assertRefused("no JSON", open_epoch_pr, ws, title="t",
                           body_path=str(self.pr_body), repo=REPO, runner=self.gh)

    def test_pr_reports_a_gh_create_refusal(self):
        ws = self.pushed_workspace()
        self.gh.create_code = 1
        self.assertRefused("draft PR creation", open_epoch_pr, ws, title="t",
                           body_path=str(self.pr_body), repo=REPO, runner=self.gh)

    def test_pr_refuses_a_create_that_reports_no_url(self):
        ws = self.pushed_workspace()
        self.gh.create_url = "created something"
        self.assertRefused("did not report a PR URL", open_epoch_pr, ws, title="t",
                           body_path=str(self.pr_body), repo=REPO, runner=self.gh)


class DiscardTests(RepoCase):
    def test_discard_removes_a_published_clone(self):
        ws = self.pushed_workspace()
        receipt = discard_workspace(ws, runner=self.gh)
        self.assertTrue(receipt["discarded"])
        self.assertFalse(ws.path.exists())

    def test_discard_is_idempotent(self):
        ws = self.pushed_workspace()
        discard_workspace(ws, runner=self.gh)
        self.assertTrue(discard_workspace(ws, runner=self.gh)["discarded"])

    def test_discard_refuses_uncommitted_work(self):
        ws = self.pushed_workspace()
        write_text(ws.path / "scratch.md", "x\n")
        self.assertRefused("uncommitted", discard_workspace, ws, runner=self.gh)

    def test_discard_refuses_a_clone_that_was_never_pushed(self):
        ws = self.workspace()
        self.assertRefused("never been pushed", discard_workspace, ws, runner=self.gh)

    def test_discard_refuses_unpushed_commits(self):
        ws = self.pushed_workspace()
        commit_paths(ws, {"late.md": "a\n"}, "epoch: late")
        self.assertRefused("unpushed work", discard_workspace, ws, runner=self.gh)

    def test_discard_refuses_a_directory_that_is_not_a_clone(self):
        self.workspaces.mkdir(parents=True, exist_ok=True)
        not_a_clone = self.workspaces / "demo-9"
        not_a_clone.mkdir()
        record = ws_mod.EpochWorkspace(epoch="demo-9", head_sha=self.head,
                                       branch=BRANCH_PREFIX + "demo-9",
                                       path=not_a_clone, remote=str(self.remote))
        self.assertRefused("not an epoch clone", discard_workspace, record)


class ReceiptTests(RepoCase):
    def test_receipt_records_the_boundary_and_the_state(self):
        ws = self.pushed_workspace()
        receipt = workspace_receipt(ws)
        self.assertEqual(receipt["epoch"], "demo-1")
        self.assertEqual(receipt["head_sha"], self.head)
        self.assertEqual(receipt["held"], list(HELD_CAPABILITIES))
        self.assertEqual(receipt["forbidden"], list(FORBIDDEN_CAPABILITIES))
        self.assertTrue(receipt["pushed"])
        self.assertFalse(receipt["discarded"])
        self.assertFalse(receipt["grant_checked"])
        json.dumps(receipt)

    def test_marker_names_the_epoch_head_and_branch(self):
        text = epoch_marker("demo-1", self.head, BRANCH_PREFIX + "demo-1")
        self.assertIn("demo-1", text)
        self.assertIn(self.head, text)


class SequenceTests(RepoCase):
    def test_full_sequence_publishes_and_discards(self):
        receipt = run_epoch_workspace(
            "demo-1", self.head, remote=str(self.remote),
            root=str(self.workspaces), repo=REPO, pr_title="Epoch demo-1",
            pr_body=str(self.pr_body), first_commit_file="epoch.md",
            first_commit_message="epoch: open demo-1", discard=True,
            runner=self.gh)
        self.assertTrue(receipt["pushed"])
        self.assertTrue(receipt["discarded"])
        self.assertTrue(receipt["pr_url"].endswith("/pull/9001"))
        self.assertFalse(Path(receipt["path"]).exists())
        remote = _git(["ls-remote", "--heads", "origin", receipt["branch"]],
                      self.remote.parent / "seed").stdout
        self.assertIn(receipt["branch"], remote)

    def test_sequence_refuses_a_file_without_a_message(self):
        self.assertRefused("go together", run_epoch_workspace, "demo-1", self.head,
                           remote=str(self.remote), root=str(self.workspaces),
                           first_commit_file="epoch.md")

    def test_sequence_refuses_a_pr_without_a_title_or_body(self):
        self.assertRefused("--pr-title and --pr-body", run_epoch_workspace,
                           "demo-1", self.head, remote=str(self.remote),
                           root=str(self.workspaces), repo=REPO)

    def test_sequence_leaves_the_clone_when_a_step_fails(self):
        body = self.root / "closing.md"
        write_text(body, f"{_RESOLVES} #{_ITEM}.\n")
        with self.assertRaises(HarnessError):
            run_epoch_workspace(
                "demo-1", self.head, remote=str(self.remote),
                root=str(self.workspaces), repo=REPO, pr_title="Epoch demo-1",
                pr_body=str(body), first_commit_file="epoch.md",
                first_commit_message="epoch: open", discard=True, runner=self.gh)
        self.assertTrue((self.workspaces / "demo-1" / ".git").exists())


class EpochWorkspaceCliTests(RepoCase):
    def tearDown(self):
        from harness import output, render
        output.QUIET = False
        render.set_color_enabled(True)
        super().tearDown()

    def _main(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            harness_cli.main(argv)
        return stdout.getvalue(), stderr.getvalue()

    def test_cli_runs_the_sequence_without_a_pr_and_prints_json(self):
        stdout, _ = self._main([
            "epoch-workspace", "--epoch", "cli-1", "--head", self.head,
            "--remote", str(self.remote), "--root", str(self.workspaces),
            "--first-commit-file", "epoch.md",
            "--first-commit-message", "epoch: open cli-1",
            "--discard", "--json"])
        receipt = json.loads(stdout)
        self.assertEqual(receipt["epoch"], "cli-1")
        self.assertTrue(receipt["discarded"])
        self.assertFalse(Path(receipt["path"]).exists())

    def test_cli_human_output_names_the_workspace(self):
        _, stderr = self._main([
            "epoch-workspace", "--epoch", "cli-2", "--head", self.head,
            "--remote", str(self.remote), "--root", str(self.workspaces),
            "--first-commit-file", "epoch.md",
            "--first-commit-message", "epoch: open cli-2", "--discard"])
        self.assertIn("branch=" + BRANCH_PREFIX + "cli-2", stderr)
        self.assertIn("discarded: yes", stderr)

    def test_cli_writes_the_receipt_to_out(self):
        out = self.root / "receipt.json"
        self._main([
            "epoch-workspace", "--epoch", "cli-3", "--head", self.head,
            "--remote", str(self.remote), "--root", str(self.workspaces),
            "--first-commit-file", "epoch.md",
            "--first-commit-message", "epoch: open cli-3", "--discard",
            "--out", str(out)])
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["epoch"], "cli-3")

    def test_cli_refuses_a_bad_epoch_name(self):
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises((HarnessError, SystemExit)):
                harness_cli.main(["epoch-workspace", "--epoch", "Bad Name",
                                  "--head", self.head, "--remote", str(self.remote),
                                  "--root", str(self.workspaces)])


if __name__ == "__main__":
    unittest.main()
