"""Doc-contract tests for Slice 3G (#416, #424, #553, #557, #565).

Pins factual alignment across UI acceptance docs, System One claim status,
measured audit-triage durations + progress output, local ledger inspection
instructions, and canon register mirror arithmetic.
"""
import contextlib
import io
import re
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


class GuiAcceptanceDocsTests(unittest.TestCase):
    """#416: GUI first-use acceptance checklist and serve/auth doc truth."""

    def test_ui_acceptance_doc_covers_ports_auth_pairing_and_recovery(self):
        doc = _read("docs/ui-acceptance.md")
        self.assertIn("127.0.0.1:8765", doc)
        self.assertIn("127.0.0.1:8766", doc)
        self.assertIn("8800", doc)
        self.assertIn("401", doc)
        self.assertIn("200", doc)
        for required in (
            "/api/status",
            "/api/auth/pair/create",
            "/api/auth/pair/redeem",
            "gui-open.url",
            "gui-auth-handoff.txt",
            "harness serve --open",
        ):
            self.assertIn(required, doc, required)

    def test_releasing_doc_separates_static_assets_from_auth_api(self):
        releasing = _read("docs/releasing.md")
        self.assertIn("`401` unauthenticated and `200` with `X-Harness-Auth`", releasing)
        self.assertNotIn("/api/status`, `/api/settings`, `/api/capabilities` all 200", releasing)

    def test_ui_docs_cross_link_acceptance_doc_and_ports(self):
        self.assertIn("ui-acceptance.md", _read("docs/security.md"))
        self.assertIn("ui-acceptance.md", _read("docs/ui-readiness.md"))
        self.assertIn("docs/ui-acceptance.md", _read("README.md"))


class SystemOneClaimAlignmentTests(unittest.TestCase):
    """#424: README and System One integration doc agree on shipped vs deferred."""

    def test_readme_marks_jury_deferred_and_states_group_calibration(self):
        readme = _read("README.md")
        self.assertIn("JEV-P2-jury", readme)
        self.assertIn("deferred", readme.lower())
        self.assertIn("group level", readme.lower())
        self.assertNotIn("and sub-second machine-native\n   jury panels", readme)

    def test_integration_doc_marks_pillar3_and_section33_deferred(self):
        doc = _read("docs/system-one-integration.md")
        self.assertIn("### Pillar 3: Ultra-Lean Machine-Native Jury Panels (Deferred / Not Shipped)", doc)
        self.assertIn("### 3.3 Fast Jury Panel Protocol (Enum-Constrained Consensus — Deferred)", doc)
        self.assertIn("does not guarantee correctness on any single individual answer", doc)


class AuditTriageTimingTests(unittest.TestCase):
    """#553: measured audit runtime, separation of D12, and elapsed progress."""

    def test_stale_two_to_five_minute_claim_removed(self):
        triage_doc = _read("docs/audit-triage.md")
        refresh_py = _read("audits/self/refresh_coverage_baseline.py")
        self.assertNotIn("two to five minutes", triage_doc)
        self.assertNotIn("two to five minutes", refresh_py)
        self.assertNotIn("2-4 min", refresh_py)
        self.assertIn("12m 25s", triage_doc)
        self.assertIn("11m 55s", triage_doc)
        self.assertIn("25 minutes", triage_doc)

    def test_audit_main_streams_elapsed_progress_and_stays_clean(self):
        import audits.self.audit as audit_mod

        with mock.patch.object(audit_mod, "CHECKS", {
            "A": [("A1", "synthetic check", lambda: (1.0, "ok"))]
        }), mock.patch.object(audit_mod, "_compose_audit_jev_policy") as jmock, \
                mock.patch.object(audit_mod.sys, "argv", ["audit.py", "--dim", "A"]):
            jmock.return_value.evaluate_audit_dimensions.return_value = {
                "dimensions": {"A": {"name": "Security", "level": "ok"}},
                "scores": {"A": 10.0},
                "bar_95_pass": True,
                "is_fallback": False,
                "model": "test",
            }
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = audit_mod.main()
        self.assertEqual(rc, 0)
        text = buf.getvalue()
        self.assertIn("[audit] A/A1: synthetic check...", text)
        self.assertRegex(text, r"\[audit\] A/A1: pass \(\d+\.\ds, total \d+\.\ds\)")


class LedgerDocContractTests(unittest.TestCase):
    """#557: docs/ledger.md defines local-only semantics without false repo claims."""

    def test_ledger_doc_contract_for_d_ids(self):
        doc = _read("docs/ledger.md")
        lower = doc.lower()
        export_exists = (ROOT / "docs" / "ledger-export.jsonl").is_file()
        self.assertFalse(
            "readable from the repo" in lower and not export_exists,
            "docs/ledger.md must not claim ledger entries are repo-readable when no export exists",
        )
        self.assertIn("not stored in or", doc)
        self.assertIn("python -m harness.cli ledger tail", doc)
        self.assertIn("D-YYYY-MM-DD-nnn", doc)
        self.assertIn("park", lower)


class RegisterMirrorParityTests(unittest.TestCase):
    """#565: canon mirror wave counts and open/closed arithmetic stay internally consistent."""

    def test_register_mirror_arithmetic_reconciles(self):
        roadmap = _read("docs/jev-roadmap.md")
        start = roadmap.index("<!-- BEGIN REGISTER_MIRROR -->")
        end = roadmap.index("<!-- END REGISTER_MIRROR -->")
        mirror = roadmap[start:end]
        census_m = re.search(
            r"\*\*(\d+)\*\* tracked issue rows appear:\s*\*\*(\d+)\*\* `OPEN` and \*\*(\d+)\*\* `CLOSED`",
            mirror,
        )
        self.assertIsNotNone(census_m)
        total_c, open_c, closed_c = (int(census_m.group(i)) for i in (1, 2, 3))
        self.assertEqual(total_c - closed_c, open_c)

        wave_rows = re.findall(r"^\|\s*(W\d+)\s*-[^|]+\|\s*(\d+)\s*\|\s*(\d+)\s*\|$", mirror, re.M)
        self.assertEqual(len(wave_rows), 11)
        self.assertEqual(sum(int(r[1]) for r in wave_rows), total_c)
        self.assertEqual(sum(int(r[2]) for r in wave_rows), open_c)

        # Every W-section header matches its row count of OPEN entries.
        sections = re.split(r"^### (W\d+) - .* - (\d+) open$", mirror, flags=re.M)
        # sections[1::3] are W0..W10, [2::3] declared opens, [3::3] body
        self.assertEqual(len(sections[1::3]), 11)
        actual_open_total = 0
        actual_row_total = 0
        for wave, decl_open, body in zip(sections[1::3], sections[2::3], sections[3::3]):
            rows = re.findall(r"^\|\s*\[#\d+\][^|]+\|\s*(OPEN|CLOSED)\s*\|", body, re.M)
            opens = sum(1 for st in rows if st == "OPEN")
            self.assertEqual(opens, int(decl_open), f"{wave} header vs row mismatch")
            actual_open_total += opens
            actual_row_total += len(rows)
        self.assertEqual(actual_row_total, total_c)
        self.assertEqual(actual_open_total, open_c)


if __name__ == "__main__":
    unittest.main()
