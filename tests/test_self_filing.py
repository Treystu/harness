"""Hermetic tests for the RSI self-filing transport (Build 3, plan section 6).

The transport is exercised against an in-memory tracker that behaves like the
API this module talks to: it stores bodies verbatim, returns them on read, and
can be told to return a tampered body so the read-back refusal is proven rather
than assumed. No network, no token.

The three properties are tested as hard as the happy path: attribution (no
filing without the seat tag and epoch SHA), append-only (no edit/delete/close
verb exists and the transport refuses one), and read-back (a mismatch is an
error, not a warning).
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from harness import cli as harness_cli
from harness import self_filing as mod
from harness.errors import HarnessError
from harness.osal import CommandResult, write_text
from harness.self_filing import (
    ALLOWED_OPERATIONS,
    CLOSURE_CLASSES,
    DEFAULT_LEDGER,
    PACKAGE_CLASSES,
    REFUSED_OPERATIONS,
    SEAT_TAG,
    Filing,
    GhTransport,
    LoopLedger,
    Transport,
    assert_attributed,
    can_close,
    file_package,
    file_receipt,
    file_test_epoch,
    render_package,
    render_receipt,
    seat_lines,
    verify_readback,
)

SHA = "b4b06b6ea5f15159019a44b92dbefaec46d8b92f"
REPO = "Treystu/harness"


class FakeTracker(Transport):
    """An in-memory tracker: verbatim bodies, sequential ids, tamperable reads."""

    def __init__(self):
        self.comments = {}
        self.issues = {}
        self.calls = []
        self.next_id = 1000
        self.next_issue = 700
        self.tamper = None

    def _perform(self, operation, **kwargs):
        self.calls.append((operation, kwargs))
        if operation == "comment_create":
            self.next_id += 1
            self.comments[self.next_id] = kwargs["body"]
            return {"id": self.next_id,
                    "html_url": f"https://github.com/{REPO}/issues/"
                                f"{kwargs['number']}#issuecomment-{self.next_id}"}
        if operation == "issue_create":
            self.next_issue += 1
            self.issues[self.next_issue] = {"title": kwargs["title"],
                                            "body": kwargs["body"]}
            return {"number": self.next_issue,
                    "html_url": f"https://github.com/{REPO}/issues/{self.next_issue}"}
        if operation == "read":
            path = kwargs["path"]
            if path.startswith(f"repos/{REPO}/issues/comments/"):
                ident = int(path.rsplit("/", 1)[1])
                return {"body": self.tamper if self.tamper is not None
                        else self.comments.get(ident, "")}
            ident = int(path.rsplit("/", 1)[1])
            return {"body": self.tamper if self.tamper is not None
                    else (self.issues.get(ident) or {}).get("body", "")}
        raise AssertionError("unexpected operation " + operation)


def package(**overrides):
    base = {
        "id": "rsi-pkg-0001",
        "class": "defect",
        "title": "STATE bar reads a stale census",
        "bar": "STATE-OPEN-OBLIGATIONS",
        "evidence": ["issues: 32 open at 8d6fbd5d", "nonissue: 2 open"],
    }
    base.update(overrides)
    return base


def receipt(**overrides):
    base = {
        "epoch": "test-20261126",
        "epoch_sha": SHA,
        "bars": {"passed": 9, "total": 21, "credit": 0, "red": ["STATE-A", "CENSUS-B"]},
        "rail": "green",
        "packages_opened": 1,
        "packages_closed": 0,
        "spend_usd": 0.0,
    }
    base.update(overrides)
    return base


class AttributionTests(unittest.TestCase):
    def test_seat_lines_name_the_seat_and_the_epoch_sha(self):
        text = seat_lines(SEAT_TAG, SHA)
        self.assertIn(f"seat: {SEAT_TAG}", text)
        self.assertIn(f"epoch_sha: {SHA}", text)

    def test_attribution_accepts_a_correct_body(self):
        body = "x\nseat: rsi-epoch\nepoch_sha: " + SHA + "\n"
        self.assertIs(assert_attributed(body, SEAT_TAG, SHA), body)

    def test_attribution_refuses_a_missing_seat_or_sha(self):
        with self.assertRaises(HarnessError):
            assert_attributed("body", "", SHA)
        with self.assertRaises(HarnessError):
            assert_attributed("body", SEAT_TAG, "")
        with self.assertRaises(HarnessError):
            assert_attributed("body\nseat: other\nepoch_sha: " + SHA, SEAT_TAG, SHA)
        with self.assertRaises(HarnessError):
            assert_attributed("body\nseat: rsi-epoch\nepoch_sha: " + "a" * 40,
                              SEAT_TAG, SHA)


class PackageRenderTests(unittest.TestCase):
    def test_package_names_its_class_bar_and_quoted_evidence(self):
        body = render_package(package(), epoch="test-20261126", epoch_sha=SHA)
        self.assertIn("### PACKAGE rsi-pkg-0001 - defect", body)
        self.assertIn(f"seat: {SEAT_TAG}", body)
        self.assertIn(f"epoch_sha: {SHA}", body)
        self.assertIn("epoch: test-20261126", body)
        self.assertIn("**Bar:** STATE-OPEN-OBLIGATIONS", body)
        self.assertIn("> issues: 32 open at 8d6fbd5d", body)
        self.assertIn("standing", body)

    def test_every_package_class_renders(self):
        for kind in PACKAGE_CLASSES:
            with self.subTest(kind=kind):
                self.assertIn(kind, render_package(package(**{"class": kind}),
                                                   epoch_sha=SHA))

    def test_package_refuses_a_foreign_class(self):
        with self.assertRaises(HarnessError):
            render_package(package(**{"class": "chore"}), epoch_sha=SHA)

    def test_package_refuses_missing_fields(self):
        for key in ("id", "title", "class", "bar", "evidence"):
            with self.subTest(key=key):
                broken = package()
                broken.pop(key)
                with self.assertRaises(HarnessError):
                    render_package(broken, epoch_sha=SHA)

    def test_package_refuses_empty_fields_or_unquoted_evidence(self):
        with self.assertRaises(HarnessError):
            render_package(package(title="  "), epoch_sha=SHA)
        with self.assertRaises(HarnessError):
            render_package(package(evidence=[]), epoch_sha=SHA)
        with self.assertRaises(HarnessError):
            render_package(package(evidence=["  "]), epoch_sha=SHA)

    def test_package_refuses_a_non_mapping(self):
        with self.assertRaises(HarnessError):
            render_package("not a package", epoch_sha=SHA)


class ReceiptRenderTests(unittest.TestCase):
    def test_receipt_reports_bars_against_full_total(self):
        body = render_receipt(receipt(), epoch="test-20261126")
        self.assertIn("### RECEIPT test-20261126", body)
        self.assertIn("bars: 9/21 (credit 0)", body)
        self.assertIn("red: STATE-A, CENSUS-B", body)
        self.assertIn("rail: green", body)
        self.assertIn("packages opened: 1", body)
        self.assertIn("spend: $0.00", body)
        self.assertIn(f"epoch_sha: {SHA}", body)

    def test_receipt_names_no_red_bars_as_none(self):
        body = render_receipt(receipt(bars={"passed": 21, "total": 21,
                                            "credit": 1, "red": []}))
        self.assertIn("red: none", body)

    def test_receipt_refuses_a_bad_sha_or_impossible_counts(self):
        with self.assertRaises(HarnessError):
            render_receipt(receipt(epoch_sha="main"))
        with self.assertRaises(HarnessError):
            render_receipt(receipt(bars={"passed": 22, "total": 21}))
        with self.assertRaises(HarnessError):
            render_receipt(receipt(bars={"passed": -1, "total": 21}))

    def test_receipt_refuses_missing_fields_and_non_mappings(self):
        for key in ("epoch_sha", "bars", "rail"):
            with self.subTest(key=key):
                broken = receipt()
                broken.pop(key)
                with self.assertRaises(HarnessError):
                    render_receipt(broken)
        with self.assertRaises(HarnessError):
            render_receipt("not a receipt")
        with self.assertRaises(HarnessError):
            render_receipt(receipt(bars="9/21"))


class AppendOnlyTests(unittest.TestCase):
    def test_only_create_and_read_are_allowed(self):
        self.assertEqual(set(ALLOWED_OPERATIONS),
                         {"issue_create", "comment_create", "read"})

    def test_every_mutating_operation_is_refused(self):
        transport = FakeTracker()
        for operation in REFUSED_OPERATIONS:
            with self.subTest(operation=operation):
                with self.assertRaises(HarnessError) as caught:
                    transport.call(operation, repo=REPO)
                self.assertIn("append-only", str(caught.exception))

    def test_an_unknown_operation_is_refused(self):
        with self.assertRaises(HarnessError):
            FakeTracker().call("issue_relabel", repo=REPO)

    def test_the_module_exposes_no_edit_or_delete_helper(self):
        for name in ("edit_comment", "delete_comment", "close_issue", "edit_issue"):
            self.assertFalse(hasattr(mod, name), name)

    def test_the_base_transport_requires_an_implementation(self):
        transport = Transport()
        for operation in ALLOWED_OPERATIONS:
            with self.subTest(operation=operation):
                with self.assertRaises(NotImplementedError):
                    transport.call(operation)


class FilingTests(unittest.TestCase):
    def setUp(self):
        self.tracker = FakeTracker()
        self.bus = 295

    def test_package_files_as_a_bus_comment_and_verifies(self):
        filing = file_package(self.tracker, REPO, package(), epoch="test-20261126",
                              epoch_sha=SHA, bus=self.bus)
        self.assertTrue(filing.verified)
        self.assertEqual(filing.kind, "package")
        self.assertIn(filing.comment_id, self.tracker.comments)
        self.assertIn("#issuecomment-", filing.url)

    def test_package_files_as_an_issue_when_no_bus_is_configured(self):
        filing = file_package(self.tracker, REPO, package(), epoch="test-20261126",
                              epoch_sha=SHA)
        self.assertTrue(filing.verified)
        self.assertEqual(filing.number, 701)
        self.assertIn("STATE-OPEN-OBLIGATIONS", self.tracker.issues[701]["body"])
        title = self.tracker.issues[701]["title"]
        self.assertIn(f"[{SEAT_TAG}] defect rsi-pkg-0001", title)

    def test_receipt_files_as_a_bus_comment_and_verifies(self):
        filing = file_receipt(self.tracker, REPO, receipt(), epoch="test-20261126",
                              bus=self.bus)
        self.assertTrue(filing.verified)
        self.assertEqual(filing.key, "test-20261126")

    def test_read_back_refuses_a_tampered_body(self):
        self.tracker.tamper = "something else"
        with self.assertRaises(HarnessError) as caught:
            file_receipt(self.tracker, REPO, receipt(), epoch="test-20261126",
                         bus=self.bus)
        self.assertIn("read-back mismatch", str(caught.exception))
        self.assertFalse(self.tracker.comments == {})

    def test_read_back_refuses_a_filing_with_no_target(self):
        with self.assertRaises(HarnessError):
            verify_readback(self.tracker, REPO, Filing(kind="package", key="k",
                                                       body="b"))

    def test_read_back_refuses_a_non_record(self):
        with mock.patch.object(self.tracker, "_perform",
                               return_value=[]):
            with self.assertRaises(HarnessError):
                verify_readback(self.tracker, REPO,
                                Filing(kind="package", key="k", body="b",
                                       comment_id=1))

    def test_filing_records_the_seat_and_epoch(self):
        filing = file_package(self.tracker, REPO, package(), epoch="test-20261126",
                              epoch_sha=SHA, bus=self.bus)
        body = self.tracker.comments[filing.comment_id]
        self.assertIn(f"seat: {SEAT_TAG}", body)
        self.assertIn(f"epoch_sha: {SHA}", body)
        self.assertIn("epoch: test-20261126", body)


class GhTransportTests(unittest.TestCase):
    def test_issue_create_posts_json_through_gh_api(self):
        calls = []

        def runner(argv, cwd=None, input_text=None):
            calls.append((argv, input_text))
            return CommandResult(0, json.dumps({"number": 12,
                                                "html_url": "https://x/12"}))

        transport = GhTransport(runner)
        row = transport.call("issue_create", repo=REPO, title="t", body="b")
        self.assertEqual(row["number"], 12)
        self.assertEqual(calls[0][0][:2], ["gh", "api"])
        self.assertIn("--input", calls[0][0])
        self.assertEqual(json.loads(calls[0][1])["body"], "b")

    def test_comment_create_targets_the_bus_issue(self):
        calls = []

        def runner(argv, cwd=None, input_text=None):
            calls.append(argv)
            return CommandResult(0, json.dumps({"id": 5, "html_url": "https://x/5"}))

        GhTransport(runner).call("comment_create", repo=REPO, number=295, body="b")
        self.assertIn(f"repos/{REPO}/issues/295/comments", calls[0])

    def test_read_gets_the_record(self):
        def runner(argv, cwd=None, input_text=None):
            return CommandResult(0, json.dumps({"body": "b"}))

        self.assertEqual(GhTransport(runner).call("read", path="repos/x")["body"], "b")

    def test_gh_failure_is_reported_with_its_text(self):
        def runner(argv, cwd=None, input_text=None):
            return CommandResult(1, "", "HTTP 403: no write access")

        with self.assertRaises(HarnessError) as caught:
            GhTransport(runner).call("comment_create", repo=REPO, number=295,
                                     body="b")
        self.assertIn("403", str(caught.exception))

    def test_non_json_output_is_refused(self):
        def runner(argv, cwd=None, input_text=None):
            return CommandResult(0, "not json")

        with self.assertRaises(HarnessError):
            GhTransport(runner).call("read", path="repos/x")


class LedgerAndClosureTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "ledger.json"
        self.ledger = LoopLedger(str(self.path))

    def tearDown(self):
        self._tmp.cleanup()

    def test_an_item_the_loop_opened_may_close_with_evidence(self):
        self.ledger.record(Filing(kind="package", key="rsi-pkg-1", body="b"),
                           epoch="e")
        for evidence in ("merged_fix", "measured_result", "disposition"):
            with self.subTest(evidence=evidence):
                self.assertTrue(can_close(self.ledger, "rsi-pkg-1", evidence)["allowed"])

    def test_an_item_the_loop_did_not_open_is_refused(self):
        verdict = can_close(self.ledger, "someone-elses-item", "merged_fix")
        self.assertFalse(verdict["allowed"])
        self.assertIn("did not open", verdict["reason"])

    def test_operator_hold_is_named_never_closed(self):
        self.ledger.record(Filing(kind="package", key="rsi-pkg-1", body="b"),
                           epoch="e")
        verdict = can_close(self.ledger, "rsi-pkg-1", "operator_hold")
        self.assertFalse(verdict["allowed"])
        self.assertIn("operator-held", verdict["reason"])

    def test_an_unknown_closure_class_is_refused(self):
        verdict = can_close(self.ledger, "rsi-pkg-1", "because-i-said-so")
        self.assertFalse(verdict["allowed"])
        self.assertIn("not a closure class", verdict["reason"])
        self.assertEqual(CLOSURE_CLASSES[0], "merged_fix")

    def test_the_ledger_round_trips(self):
        self.ledger.record(Filing(kind="package", key="k1", body="b", verified=True),
                           epoch="e")
        self.ledger.save()
        again = LoopLedger(str(self.path))
        self.assertTrue(again.owns("k1"))
        self.assertEqual(again.items[0]["epoch"], "e")

    def test_the_ledger_refuses_a_corrupt_file(self):
        write_text(self.path, "{oops")
        with self.assertRaises(HarnessError):
            LoopLedger(str(self.path))

    def test_the_default_ledger_lives_in_the_ignored_tmp_tree(self):
        self.assertTrue(DEFAULT_LEDGER.startswith("tmp/"))


class TestEpochTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ledger_path = str(Path(self._tmp.name) / "ledger.json")
        self.tracker = FakeTracker()

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_acceptance_act_files_both_records_and_reads_them_back(self):
        result = file_test_epoch(self.tracker, REPO, epoch="test-20261126",
                                 epoch_sha=SHA, bus=295, package=package(),
                                 receipt=receipt(), ledger_path=self.ledger_path)
        self.assertTrue(result["verified"])
        self.assertEqual(result["package"]["kind"], "package")
        self.assertEqual(result["receipt"]["kind"], "receipt")
        self.assertTrue(Path(result["ledger"]).is_file())
        posts = [call for call in self.tracker.calls if call[0] == "comment_create"]
        self.assertEqual(len(posts), 2)
        for _, kwargs in posts:
            self.assertIn(f"seat: {SEAT_TAG}", kwargs["body"])
            self.assertIn(f"epoch_sha: {SHA}", kwargs["body"])
        self.assertFalse([call for call in self.tracker.calls
                          if call[0] in REFUSED_OPERATIONS])

    def test_the_acceptance_act_refuses_a_symbolic_sha(self):
        with self.assertRaises(HarnessError):
            file_test_epoch(self.tracker, REPO, epoch="e", epoch_sha="main",
                            bus=295, package=package(), receipt=receipt(),
                            ledger_path=self.ledger_path)

    def test_the_acceptance_act_records_both_items_in_the_ledger(self):
        file_test_epoch(self.tracker, REPO, epoch="test-20261126", epoch_sha=SHA,
                        bus=295, package=package(), receipt=receipt(),
                        ledger_path=self.ledger_path)
        ledger = LoopLedger(self.ledger_path)
        self.assertTrue(ledger.owns("rsi-pkg-0001"))
        self.assertTrue(ledger.owns("test-20261126"))
        self.assertTrue(all(item["verified"] for item in ledger.items))


class SelfFilingCliTests(unittest.TestCase):
    def tearDown(self):
        from harness import output, render
        output.QUIET = False
        render.set_color_enabled(True)

    def _run(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            harness_cli.main(argv)
        return stdout.getvalue(), stderr.getvalue()

    def test_cli_dry_run_renders_both_records_without_filing(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / "package.json"
            rec = Path(tmp) / "receipt.json"
            write_text(pkg, json.dumps(package()))
            write_text(rec, json.dumps(receipt()))
            out, _ = self._run(["self-filing", "--repo", REPO, "--bus", "295",
                                "--epoch", "test-20261126", "--epoch-sha", SHA,
                                "--package", str(pkg), "--receipt", str(rec),
                                "--dry-run", "--json"])
        preview = json.loads(out)
        self.assertEqual(preview["seat"], SEAT_TAG)
        self.assertIn("### PACKAGE rsi-pkg-0001", preview["package"])
        self.assertIn("### RECEIPT test-20261126", preview["receipt"])

    def test_cli_refuses_a_bad_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / "package.json"
            rec = Path(tmp) / "receipt.json"
            write_text(pkg, json.dumps(package()))
            write_text(rec, json.dumps(receipt()))
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises((HarnessError, SystemExit)):
                    harness_cli.main(["self-filing", "--repo", REPO, "--bus",
                                      "295", "--epoch", "e", "--epoch-sha", "main",
                                      "--package", str(pkg),
                                      "--receipt", str(rec), "--dry-run"])


if __name__ == "__main__":
    unittest.main()
