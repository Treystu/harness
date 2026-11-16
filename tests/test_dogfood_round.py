"""#277: a dogfood report that cannot be filed incomplete.

Round 1's failure was not a bug in the product -- it was a report that did not
exist. These tests pin the four rules #277 sets so that failure cannot recur: all
four surfaces, a note on every item, a disposition on every finding, and a
one-line verdict per surface. They also pin the one honest third outcome, "not
exercised", with its reason carried into the verdict rather than quietly counted
as clean.
"""
import json
import tempfile
import unittest

from harness import dogfood as df


def _pack(**overrides):
    surfaces = {
        "cli": [{"item": "help", "status": "exercised", "note": "rc=0"}],
        "gui": [{"item": "launch", "status": "not_exercised",
                 "note": "no desktop session on this lane"}],
        "mcp": [{"item": "tools", "status": "not_exercised",
                 "note": "no MCP client registered"}],
        "website": [{"item": "pages", "status": "not_exercised",
                     "note": "no preview host"}],
    }
    surfaces.update(overrides)
    return {"round": "2026-11-14-laptop", "surfaces": surfaces}


class PackShapeTests(unittest.TestCase):
    def test_a_full_pack_normalises(self):
        pack = df.validate_pack(_pack())
        self.assertEqual(sorted(pack["surfaces"]), sorted(df.SURFACES))

    def test_a_missing_surface_is_refused_by_name(self):
        payload = _pack()
        payload["surfaces"].pop("mcp")
        with self.assertRaises(df.DogfoodError) as ctx:
            df.validate_pack(payload)
        self.assertIn("mcp", str(ctx.exception))

    def test_an_unknown_surface_is_refused(self):
        with self.assertRaises(df.DogfoodError):
            df.validate_pack(_pack(email=[{"item": "inbox", "status": "exercised",
                                           "note": "x"}]))

    def test_an_empty_surface_is_refused(self):
        with self.assertRaises(df.DogfoodError):
            df.validate_pack(_pack(cli=[]))

    def test_a_blank_round_id_is_refused(self):
        payload = _pack()
        payload["round"] = "   "
        with self.assertRaises(df.DogfoodError):
            df.validate_pack(payload)


class SilenceTests(unittest.TestCase):
    def test_an_item_without_a_note_is_refused(self):
        with self.assertRaises(df.DogfoodError) as ctx:
            df.validate_pack(_pack(cli=[{"item": "help", "status": "exercised",
                                         "note": ""}]))
        self.assertIn("note", str(ctx.exception))

    def test_an_item_without_a_name_is_refused(self):
        with self.assertRaises(df.DogfoodError):
            df.validate_pack(_pack(cli=[{"status": "exercised", "note": "rc=0"}]))

    def test_an_unknown_status_is_refused(self):
        with self.assertRaises(df.DogfoodError):
            df.validate_pack(_pack(cli=[{"item": "help", "status": "ok",
                                         "note": "rc=0"}]))

    def test_a_not_exercised_item_must_give_its_reason(self):
        with self.assertRaises(df.DogfoodError):
            df.validate_pack(_pack(gui=[{"item": "launch",
                                         "status": "not_exercised", "note": " "}]))


class FindingTests(unittest.TestCase):
    def _finding(self, **overrides):
        finding = {"text": "python -m harness exits 1", "severity": "low",
                   "issue": 501}
        finding.update(overrides)
        return finding

    def test_a_filed_finding_carries_its_issue_and_severity(self):
        item = df.check_item({"item": "module entry", "status": "finding",
                              "note": "measured rc=1",
                              "finding": self._finding()})
        self.assertEqual(item["finding"]["issue"], 501)
        self.assertEqual(item["finding"]["severity"], "low")

    def test_a_finding_with_no_disposition_is_refused(self):
        finding = self._finding()
        finding.pop("issue")
        with self.assertRaises(df.DogfoodError) as ctx:
            df.check_item({"item": "x", "status": "finding", "note": "seen",
                           "finding": finding})
        self.assertIn("no disposition", str(ctx.exception))

    def test_a_finding_cannot_be_both_filed_and_fixed(self):
        with self.assertRaises(df.DogfoodError):
            df.check_item({"item": "x", "status": "finding", "note": "seen",
                           "finding": self._finding(fixed="commit abc123")})

    def test_a_fixed_finding_names_the_fix(self):
        finding = self._finding()
        finding.pop("issue")
        finding["fixed"] = "added __main__.py with a test"
        item = df.check_item({"item": "x", "status": "finding",
                              "note": "seen", "finding": finding})
        self.assertIn("__main__", item["finding"]["fixed"])

    def test_an_issue_reference_must_be_a_number(self):
        for bad in ("501", True, 0, -3):
            with self.assertRaises(df.DogfoodError):
                df.check_item({"item": "x", "status": "finding", "note": "seen",
                               "finding": self._finding(issue=bad)})

    def test_an_undeclared_severity_is_refused(self):
        for bad in ("critical", "info", None):
            with self.assertRaises(df.DogfoodError):
                df.check_item({"item": "x", "status": "finding", "note": "seen",
                               "finding": self._finding(severity=bad)})

    def test_a_finding_on_a_non_finding_item_is_refused(self):
        with self.assertRaises(df.DogfoodError):
            df.check_item({"item": "x", "status": "exercised", "note": "clean",
                           "finding": self._finding()})


class VerdictTests(unittest.TestCase):
    def test_a_clean_surface_says_no_findings_explicitly(self):
        verdict, blockers = df.surface_verdict(
            "cli", [df.check_item({"item": "help", "status": "exercised",
                                   "note": "rc=0"})])
        self.assertEqual(verdict, "clean - no findings")
        self.assertEqual(blockers, [])

    def test_a_surface_with_filed_issues_names_them(self):
        verdict, _ = df.surface_verdict(
            "cli", [df.check_item({"item": "x", "status": "finding", "note": "n",
                                   "finding": {"text": "t", "severity": "low",
                                               "issue": 501}})])
        self.assertEqual(verdict, "issues filed (#501)")

    def test_a_surface_with_a_fixed_finding_does_not_claim_clean(self):
        verdict, _ = df.surface_verdict(
            "cli", [df.check_item({"item": "x", "status": "finding", "note": "n",
                                   "finding": {"text": "t", "severity": "low",
                                               "fixed": "commit abc"}})])
        self.assertIn("fixed in round", verdict)

    def test_a_not_exercised_surface_is_a_blocker_with_its_reason(self):
        verdict, blockers = df.surface_verdict(
            "gui", [df.check_item({"item": "launch", "status": "not_exercised",
                                   "note": "no desktop session"})])
        self.assertIn("not exercised", verdict)
        self.assertIn("no desktop session", verdict)
        self.assertEqual(blockers, ["launch"])

    def test_an_unknown_surface_cannot_have_a_verdict(self):
        with self.assertRaises(df.DogfoodError):
            df.surface_verdict("email", [])


class RenderTests(unittest.TestCase):
    def test_the_report_has_one_section_and_a_verdict_table(self):
        text = df.render_report(_pack())
        for surface in df.SURFACES:
            self.assertIn("## {}".format(surface.upper()), text)
        self.assertIn("## Verdicts", text)
        self.assertIn("| gui | not exercised", text)

    def test_every_surface_verdict_appears_in_the_table(self):
        text = df.render_report(_pack())
        table = text.split("## Verdicts", 1)[1]
        for surface in df.SURFACES:
            self.assertIn("| {} |".format(surface), table)

    def test_a_not_exercised_item_renders_as_such(self):
        self.assertIn("NOT EXERCISED", df.render_report(_pack()))

    def test_a_finding_renders_with_its_severity_and_issue(self):
        payload = _pack(cli=[{"item": "module entry", "status": "finding",
                              "note": "measured",
                              "finding": {"text": "no __main__", "severity": "low",
                                          "issue": 501}}])
        text = df.render_report(payload)
        self.assertIn("FINDING (low, issue #501)", text)
        self.assertIn("no __main__", text)

    def test_rendering_refuses_an_incomplete_pack(self):
        payload = _pack()
        payload["surfaces"].pop("website")
        with self.assertRaises(df.DogfoodError):
            df.render_report(payload)

    def test_a_pack_loads_from_disk_and_a_bad_file_is_refused(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as handle:
            json.dump(_pack(), handle)
            path = handle.name
        self.assertEqual(df.load_pack(path)["round"], "2026-11-14-laptop")
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as bad:
            bad.write("[1, 2, 3]")
            bad_path = bad.name
        with self.assertRaises(df.DogfoodError):
            df.load_pack(bad_path)


if __name__ == "__main__":
    unittest.main()
