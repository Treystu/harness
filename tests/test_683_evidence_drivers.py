"""Pins for the archived lane gate drivers (#683 findings 56, 57, 61-64).

These receipts were produced by one-off drivers under ``evidence/lane-sessions``.
The drivers are not imported by the product, so nothing else in the suite would
notice if one went back to the reversed gate order, to a decision-signal key the
policy never returns, or to a head copied from another act. This module reads
the committed sources and receipts and asserts the four properties the findings
named.
"""
import ast
import hashlib
import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERGEANT = ROOT / "evidence" / "lane-sessions" / "sergeant-2026-11-19"
W2 = ROOT / "evidence" / "lane-sessions" / "w2-2026-11-20"
LANES = (SERGEANT, W2)


def gate_drivers():
    for lane in LANES:
        for path in sorted(lane.glob("gates_*.py")):
            yield path


def _calls(tree, name):
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr == name:
                out.append(node)
            elif isinstance(fn, ast.Name) and fn.id == name:
                out.append(node)
    return out


def _string_constants(tree):
    return "\n".join(
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str))


class GateOrderTests(unittest.TestCase):
    def test_lucas_gate_runs_before_the_jev_decision(self):
        checked = []
        for path in gate_drivers():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            lucas = _calls(tree, "run_typed_track")
            jev = _calls(tree, "evaluate_decision")
            if not lucas or not jev:
                continue
            checked.append(path)
            self.assertLess(
                min(node.lineno for node in lucas),
                min(node.lineno for node in jev),
                f"{path.relative_to(ROOT)} calls the Jev decision before Lucas Gate")
        self.assertGreaterEqual(len(checked), 30)


class DecisionSignalTests(unittest.TestCase):
    """The policy returns disposition_lead / advances_goal / is_destructive."""

    UNRETURNED = re.compile(
        r"verdict\.get\(\s*['\"](lead|advanced|destructive)['\"]\s*\)")

    def test_no_driver_reads_a_key_the_policy_does_not_return(self):
        for path in gate_drivers():
            text = path.read_text(encoding="utf-8")
            match = self.UNRETURNED.search(text)
            self.assertIsNone(
                match, f"{path.relative_to(ROOT)} reads a never-returned key")

    def test_the_policy_owner_returns_the_names_the_drivers_read(self):
        source = (ROOT / "harness" / "jev_packs.py").read_text(encoding="utf-8")
        for key in ("disposition_lead", "advances_goal", "is_destructive"):
            self.assertIn(f'"{key}"', source)


class HeadBindingTests(unittest.TestCase):
    META_HEAD = re.compile(r'"head":\s*"([0-9a-f]{40})"')

    def test_each_receipt_head_is_named_in_the_act_it_assesses(self):
        checked = 0
        for path in gate_drivers():
            text = path.read_text(encoding="utf-8")
            found = self.META_HEAD.search(text)
            if not found:
                continue
            head = found.group(1)
            tree = ast.parse(text)
            checked += 1
            self.assertIn(
                head, _string_constants(tree),
                f"{path.relative_to(ROOT)} records a head its act text never names")
        self.assertGreaterEqual(checked, 18)


class RerunPollTests(unittest.TestCase):
    def test_rerun_415_polls_the_result_subroute(self):
        text = (W2 / "rerun_415.py").read_text(encoding="utf-8")
        self.assertIn('/api/runs/" + run_id + "/result"', text)
        self.assertNotRegex(text, r'req\("/api/runs/" \+ run_id\)')


class Turn15ReceiptTests(unittest.TestCase):
    """Finding 64: the receipt must hash the committed filings, not drafts."""

    ITEMS = {
        "413-head-currency": "413-head-currency-t15.md",
        "295-status-15": "295-status-15.md",
    }

    def test_receipt_hashes_the_committed_filings(self):
        receipt = json.loads(
            (W2 / "gates-turn15-r2.json").read_text(encoding="utf-8"))
        for key, name in self.ITEMS.items():
            committed = hashlib.sha256(
                (W2 / "filings" / name).read_bytes()).hexdigest()
            self.assertEqual(
                receipt[key]["lucas"]["artifact_sha256"], committed,
                f"{key} receipt does not cover the committed filing")
            self.assertEqual(receipt[key]["lucas"]["status"], "pass")

    def test_receipt_carries_the_signals_it_recorded(self):
        receipt = json.loads(
            (W2 / "gates-turn15-r2.json").read_text(encoding="utf-8"))
        for key in self.ITEMS:
            jev = receipt[key]["product_jev"]
            self.assertIsNotNone(jev["lead"], f"{key} lead was discarded")
            self.assertIsNotNone(jev["destructive"], f"{key} destructive was discarded")
        self.assertRegex(receipt["_meta"]["head_under_test"], r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
