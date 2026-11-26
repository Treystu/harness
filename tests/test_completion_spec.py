"""Hermetic tests for the RSI completion spec (Build 1, plan section 3).

The spec is frozen data: these tests pin that it validates, that every P5
completion element maps to a bar, that the recorded Build 0 census reproduces
the bar run that epoch recorded, and that the runner and CLI stay read-only.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock

from harness import cli as harness_cli
from harness import completion_spec as spec_mod
from harness.completion_spec import (
    BAR_CLASSES,
    P5_ELEMENTS,
    SPEC_PATH,
    frozen_paths_touched,
    load_census,
    load_spec,
    run_spec,
    run_spec_file,
    validate_spec,
)
from harness.errors import HarnessError

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD0_CENSUS = REPO_ROOT / "packs" / "completion_spec.build0-census.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _green_census() -> dict:
    """A census where every bar can pass, built from the recorded one's shape."""
    census = load_census(str(BUILD0_CENSUS))
    green = deepcopy(census)
    for row in green["inventory"]["issues"]:
        row["state"] = "closed"
    for row in green["inventory"]["nonissue"]:
        row["state"] = "closed"
    green["inventory"]["closures"] = {
        "recorded": True,
        "items": [{"id": "#1", "evidence_class": "merged_fix"}],
    }
    green["pulls"]["open"] = []
    green["worktrees"] = {"recorded": True, "dirty": []}
    green["judgment"]["artifact_bar"]["runs"] = [{
        "combined": 97.5,
        "axes": {
            "correctness": 95,
            "completeness": 100,
            "executability": 95,
            "safety": 95,
            "currency": 95,
        },
        "probes": "proven",
    }] * 2
    green["judgment"]["phase_bar"] = {
        "recorded": True,
        "min_score": 85,
        "phases": {"JEV-P1": {"score": 96.0, "bar_pass": True}},
        "hard_gates": {"pr_merged": True},
    }
    green["judgment"]["change_set"] = {"present": True, "judged": True}
    for key in green["behavior"]["surfaces"]:
        green["behavior"]["surfaces"][key] = {"state": "pass"}
    green["behavior"]["never_defer"] = {"state": "pass"}
    green["census"]["unification"] = {"closed": True}
    green["census"]["self_claims"] = {"recorded": True, "total": 12, "verified": 12}
    green["checks_16_5"] = {
        "recorded": True,
        "checks": [{"id": "16.5.1", "state": "pass"}],
    }
    return green


class SpecFileTests(unittest.TestCase):
    def test_the_repo_spec_loads_and_covers_five_classes(self):
        spec = load_spec(str(REPO_ROOT))
        self.assertEqual(spec["id"], "harness-rsi-completion-spec")
        self.assertTrue(spec["frozen"])
        classes = {bar["class"] for bar in spec["bars"]}
        self.assertEqual(classes, set(BAR_CLASSES))

    def test_every_bar_carries_the_required_evidence_fields(self):
        spec = load_spec(str(REPO_ROOT))
        for bar in spec["bars"]:
            for field in ("id", "class", "check", "threshold", "evidence_type",
                          "evidence_surface"):
                self.assertTrue(str(bar.get(field) or "").strip(),
                                f"{bar.get('id')} missing {field}")

    def test_every_p5_element_maps_to_a_bar(self):
        spec = load_spec(str(REPO_ROOT))
        mapped = {bar.get("p5_element") for bar in spec["bars"]}
        for element in P5_ELEMENTS:
            self.assertIn(element, mapped, f"P5 element {element} has no bar")

    def test_unknown_check_refuses_the_whole_spec(self):
        raw = json.loads((REPO_ROOT / SPEC_PATH).read_text(encoding="utf-8"))
        raw["bars"][0]["check"] = "no_such_check"
        with self.assertRaises(HarnessError):
            validate_spec(raw)

    def test_duplicate_bar_id_refuses_the_spec(self):
        raw = json.loads((REPO_ROOT / SPEC_PATH).read_text(encoding="utf-8"))
        raw["bars"][1]["id"] = raw["bars"][0]["id"]
        with self.assertRaises(HarnessError):
            validate_spec(raw)

    def test_a_writable_spec_is_refused(self):
        raw = json.loads((REPO_ROOT / SPEC_PATH).read_text(encoding="utf-8"))
        raw["frozen"] = False
        with self.assertRaises(HarnessError):
            validate_spec(raw)

    def test_an_unmapped_p5_element_refuses_the_spec(self):
        raw = json.loads((REPO_ROOT / SPEC_PATH).read_text(encoding="utf-8"))
        for bar in raw["bars"]:
            if bar.get("p5_element") == "p5.checks.section_16_5":
                bar["p5_element"] = "p5.elsewhere"
        with self.assertRaises(HarnessError):
            validate_spec(raw)

    def test_frozen_path_matching_normalises_separators(self):
        self.assertEqual(
            frozen_paths_touched([".\\harness\\jev_policy.py", "docs/x.md"]),
            ["harness/jev_policy.py"])
        self.assertEqual(frozen_paths_touched(["docs/x.md"]), [])


class Build0DryRunTests(unittest.TestCase):
    """The recorded census must reproduce the bar run Build 0 recorded."""

    @classmethod
    def setUpClass(cls):
        cls.board = run_spec_file(str(REPO_ROOT), str(BUILD0_CENSUS))
        cls.by_id = {bar["id"]: bar for bar in cls.board["bars"]}

    def test_class_states_match_the_build0_receipt(self):
        states = {name: self.board["classes"][name]["state"] for name in BAR_CLASSES}
        self.assertEqual(states, {
            "STATE": "red",
            "RAIL": "green",
            "JUDGMENT": "red",
            "BEHAVIOR": "red",
            "CENSUS": "red",
        })

    def test_rail_is_green_at_the_epoch_head(self):
        self.assertEqual(self.by_id["RAIL-BATTERY"]["state"], "green")
        self.assertEqual(self.by_id["RAIL-DEBT"]["state"], "green")

    def test_state_names_the_open_obligations_and_pulls(self):
        obligations = self.by_id["STATE-OPEN-OBLIGATIONS"]
        self.assertEqual(obligations["state"], "red")
        self.assertEqual(obligations["observed"]["open"], 29)
        self.assertEqual(len(obligations["observed"]["operator_hold"]), 5)
        self.assertEqual(self.by_id["STATE-OPEN-PRS"]["state"], "red")
        self.assertEqual(self.by_id["STATE-OPEN-PRS"]["observed"]["open"], 3)

    def test_issue_and_nonissue_rows_reconcile(self):
        self.assertEqual(self.by_id["STATE-ISSUE-ROWS"]["state"], "green")
        self.assertEqual(self.by_id["STATE-NONISSUE-ROWS"]["state"], "green")

    def test_judgment_house_instrument_is_red_on_the_recorded_scores(self):
        bar = self.by_id["JUDGMENT-HOUSE-INSTRUMENT"]
        self.assertEqual(bar["state"], "red")
        self.assertIn("combined 62.5", bar["detail"])
        self.assertIn("modal axis 60.0", bar["detail"])
        self.assertEqual(self.by_id["JUDGMENT-PROBES"]["state"], "green")

    def test_behavior_legs_split_exactly_as_recorded(self):
        self.assertEqual(self.by_id["BEHAVIOR-CLI"]["state"], "green")
        self.assertEqual(self.by_id["BEHAVIOR-MCP"]["state"], "green")
        self.assertEqual(self.by_id["BEHAVIOR-GUI"]["state"], "not_run")
        self.assertEqual(self.by_id["BEHAVIOR-STUDIO"]["state"], "not_run")
        self.assertEqual(self.by_id["BEHAVIOR-NEVER-DEFER"]["state"], "not_run")

    def test_census_bar_is_red_on_the_unrun_unification_census(self):
        self.assertEqual(self.by_id["CENSUS-UNIFICATION"]["state"], "red")
        self.assertEqual(self.by_id["CENSUS-PLAN-OF-RECORD"]["state"], "green")

    def test_summary_reports_passed_against_full_total_with_zero_credit(self):
        summary = self.board["summary"]
        self.assertEqual(summary["total"], 21)
        self.assertEqual(summary["passed"], 9)
        self.assertEqual(summary["verdict"], "red")
        self.assertEqual(summary["label"], "FULL")
        self.assertEqual(summary["credit"], 0)
        self.assertEqual(sorted(summary["red_bars"]), sorted([
            "STATE-OPEN-OBLIGATIONS",
            "STATE-OPEN-PRS",
            "JUDGMENT-HOUSE-INSTRUMENT",
            "CENSUS-UNIFICATION",
        ]))

    def test_element_coverage_lists_the_bars_per_p5_element(self):
        coverage = self.board["element_coverage"]
        self.assertEqual(sorted(coverage), sorted(P5_ELEMENTS))
        for element, bars in coverage.items():
            self.assertTrue(bars, f"{element} uncovered")

    def test_running_the_spec_does_not_modify_the_spec_or_census(self):
        spec_file = REPO_ROOT / SPEC_PATH
        before = (_sha256(spec_file), _sha256(BUILD0_CENSUS))
        run_spec_file(str(REPO_ROOT), str(BUILD0_CENSUS))
        after = (_sha256(spec_file), _sha256(BUILD0_CENSUS))
        self.assertEqual(before, after)


class GreenAndPartialTests(unittest.TestCase):
    def test_a_fully_green_census_earns_credit(self):
        spec = load_spec(str(REPO_ROOT))
        board = run_spec(spec, _green_census())
        self.assertEqual(board["summary"]["verdict"], "green")
        self.assertEqual(board["summary"]["credit"], 1)
        self.assertEqual(board["summary"]["passed"], board["summary"]["total"])
        self.assertEqual({name: board["classes"][name]["state"] for name in BAR_CLASSES},
                         {name: "green" for name in BAR_CLASSES})

    def test_a_composite_of_exactly_100_is_a_red_flag(self):
        spec = load_spec(str(REPO_ROOT))
        census = _green_census()
        for run in census["judgment"]["artifact_bar"]["runs"]:
            run["combined"] = 100
        board = run_spec(spec, census)
        bar = {row["id"]: row for row in board["bars"]}["JUDGMENT-HOUSE-INSTRUMENT"]
        self.assertEqual(bar["state"], "red")
        self.assertIn("red flag", bar["detail"])

    def test_a_single_run_cannot_satisfy_the_threshold(self):
        spec = load_spec(str(REPO_ROOT))
        census = _green_census()
        runs = census["judgment"]["artifact_bar"]["runs"]
        census["judgment"]["artifact_bar"]["runs"] = runs[:1]
        board = run_spec(spec, census)
        bar = {row["id"]: row for row in board["bars"]}["JUDGMENT-HOUSE-INSTRUMENT"]
        self.assertEqual(bar["state"], "red")

    def test_an_axis_below_the_floor_fails(self):
        spec = load_spec(str(REPO_ROOT))
        census = _green_census()
        for run in census["judgment"]["artifact_bar"]["runs"]:
            run["axes"]["safety"] = 35
        board = run_spec(spec, census)
        bar = {row["id"]: row for row in board["bars"]}["JUDGMENT-HOUSE-INSTRUMENT"]
        self.assertEqual(bar["state"], "red")
        self.assertIn("axis below floor: safety", bar["detail"])

    def test_a_class_with_no_census_section_is_partial_and_earns_no_credit(self):
        spec = load_spec(str(REPO_ROOT))
        census = _green_census()
        census.pop("behavior")
        board = run_spec(spec, census)
        self.assertEqual(board["summary"]["label"], "PARTIAL")
        self.assertEqual(board["summary"]["credit"], 0)
        self.assertEqual(board["classes"]["BEHAVIOR"]["state"], "red")
        self.assertIn("BEHAVIOR", board["summary"]["partial_classes"])


class CompletionSpecCliTests(unittest.TestCase):
    def tearDown(self):
        # --quiet is process-global output state (harness/output.py QUIET) set by
        # apply_output_flags; a test that leaves it True silences eprint for every
        # test that runs after it.
        from harness import output, render
        output.QUIET = False
        render.set_color_enabled(True)

    def test_cli_runs_the_build0_census_and_prints_the_board(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            harness_cli.main(["completion-spec", "--repo-root", str(REPO_ROOT),
                              "--census", str(BUILD0_CENSUS), "--json"])
        board = json.loads(stdout.getvalue())
        self.assertEqual(board["summary"]["total"], 21)
        self.assertEqual(board["summary"]["credit"], 0)

    def test_cli_require_green_refuses_a_red_board(self):
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises((HarnessError, SystemExit)):
                harness_cli.main(["completion-spec", "--repo-root", str(REPO_ROOT),
                                  "--census", str(BUILD0_CENSUS),
                                  "--require-green"])

    def test_cli_human_summary_names_the_red_bars(self):
        stderr = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(stderr):
            harness_cli.main(["completion-spec", "--repo-root", str(REPO_ROOT),
                              "--census", str(BUILD0_CENSUS)])
        self.assertIn("STATE: red", stderr.getvalue())
        self.assertIn("RAIL: green", stderr.getvalue())
        self.assertIn("STATE-OPEN-OBLIGATIONS", stderr.getvalue())

    def test_cli_writes_the_board_to_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "board.json"
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                harness_cli.main(["completion-spec", "--repo-root", str(REPO_ROOT),
                                  "--census", str(BUILD0_CENSUS),
                                  "--out", str(out)])
            board = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(board["summary"]["total"], 21)

    def test_cli_refuses_a_missing_census(self):
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises((HarnessError, SystemExit)):
                harness_cli.main(["completion-spec", "--repo-root", str(REPO_ROOT),
                                  "--census", "no-such-census.json"])


def _check(name: str, census: dict, threshold: dict | None = None) -> dict:
    bar = {"threshold": threshold or {}, "surface_key": (threshold or {}).get("surface_key")}
    return spec_mod.CHECKS[name](census, bar)


class CheckBranchTests(unittest.TestCase):
    """Every check's refusal path: absent sections never invent a pass."""

    def test_every_check_returns_not_run_on_an_empty_census(self):
        for name in spec_mod.CHECKS:
            outcome = _check(name, {}, {"canonical": "x", "census_view": "y",
                                        "surface_key": "cli"})
            self.assertEqual(outcome["state"], "not_run", name)

    def test_an_inventory_without_any_row_list_is_not_run(self):
        outcome = _check("open_obligations_zero", {"inventory": {"other": 1}})
        self.assertEqual(outcome["state"], "not_run")

    def test_operator_held_rows_are_counted_and_named_but_never_obligations(self):
        census = {"inventory": {"issues": [
            {"number": 1, "state": "open", "operator_hold": True}]}}
        outcome = _check("open_obligations_zero", census)
        self.assertEqual(outcome["state"], "green")
        self.assertEqual(outcome["observed"]["operator_hold"], ["#1"])

    def test_a_row_with_neither_id_nor_number_is_labelled(self):
        census = {"inventory": {"nonissue": [{"state": "open"}]}}
        outcome = _check("open_obligations_zero", census)
        self.assertEqual(outcome["observed"]["open_ids"], ["?"])

    def test_issue_reconciliation_without_counts_is_not_run(self):
        census = {"inventory": {"issues": [], "reconciliation": {"issues": {}}}}
        self.assertEqual(_check("issue_rows_reconciled", census)["state"], "not_run")

    def test_issue_reconciliation_with_an_unexplained_difference_is_red(self):
        census = {"inventory": {"issues": [{"number": 1}], "reconciliation": {
            "issues": {"api_count": 1, "register_open": 2,
                       "receipted_closures": 0, "unexplained": ["#9"]}}}}
        outcome = _check("issue_rows_reconciled", census)
        self.assertEqual(outcome["state"], "red")
        self.assertIn("does not reconcile", outcome["detail"])

    def test_a_list_shorter_than_the_api_count_is_red(self):
        census = {"inventory": {"issues": [], "reconciliation": {
            "issues": {"api_count": 2, "register_open": 2,
                       "receipted_closures": 0, "unexplained": []}}}}
        self.assertEqual(_check("issue_rows_reconciled", census)["state"], "red")

    def test_nonissue_reconciliation_without_a_count_is_not_run(self):
        census = {"inventory": {"nonissue": [], "reconciliation": {"nonissue": {}}}}
        self.assertEqual(_check("nonissue_rows_reconciled", census)["state"], "not_run")

    def test_nonissue_rows_that_disagree_with_the_register_are_red(self):
        census = {"inventory": {"nonissue": [], "reconciliation": {
            "nonissue": {"register_open": 2, "unexplained": []}}}}
        self.assertEqual(_check("nonissue_rows_reconciled", census)["state"], "red")

    def test_an_unclassified_closure_is_red(self):
        census = {"inventory": {"closures": {"recorded": True, "items": [
            {"id": "#7", "evidence_class": "vibes"}]}}}
        outcome = _check("closures_carry_evidence_class", census)
        self.assertEqual(outcome["state"], "red")
        self.assertIn("#7", outcome["detail"])

    def test_an_empty_recorded_closure_log_is_green(self):
        census = {"inventory": {"closures": {"recorded": True, "items": []}}}
        self.assertEqual(_check("closures_carry_evidence_class", census)["state"], "green")

    def test_register_checks_with_no_check_is_red(self):
        census = {"checks_16_5": {"recorded": True, "checks": []}}
        self.assertEqual(_check("register_checks_16_5_pass", census)["state"], "red")

    def test_a_failing_register_check_is_red(self):
        census = {"checks_16_5": {"recorded": True, "checks": [
            {"id": "16.5.2", "state": "fail"}]}}
        outcome = _check("register_checks_16_5_pass", census)
        self.assertEqual(outcome["state"], "red")
        self.assertIn("16.5.2", outcome["detail"])

    def test_dirty_worktrees_are_red(self):
        census = {"worktrees": {"recorded": True, "dirty": ["lane/x"]}}
        outcome = _check("unpushed_work_zero", census)
        self.assertEqual(outcome["state"], "red")
        self.assertIn("lane/x", outcome["detail"])

    def test_a_rail_without_contexts_is_not_run(self):
        self.assertEqual(_check("rail_green_or_labelled_interim", {"rail": {}})["state"],
                         "not_run")

    def test_a_red_rail_without_interim_is_red(self):
        census = {"rail": {"contexts": [{"name": "audit", "state": "failure"}]}}
        outcome = _check("rail_green_or_labelled_interim", census)
        self.assertEqual(outcome["state"], "red")
        self.assertIn("audit", outcome["detail"])

    def test_a_labelled_local_interim_with_a_debt_entry_is_green(self):
        census = {"rail": {
            "contexts": [{"name": "audit", "state": "failure"}],
            "interim": {"labelled_local": True,
                        "debt_entry": {"head": "abc", "command": "x", "result": "y"}}}}
        self.assertEqual(_check("rail_green_or_labelled_interim", census)["state"], "green")

    def test_unlabelled_or_incomplete_debt_entries_are_red(self):
        for entry in ("not-a-dict", {}, {"head": "a", "command": "b", "result": "c"},
                      {"head": "a", "command": "b", "result": "c",
                       "labelled_local": True, "extra": 1}):
            census = {"rail": {"debt": [entry]}}
            outcome = _check("rail_debt_current", census)
            if entry.get("labelled_local") if isinstance(entry, dict) else False:
                self.assertEqual(outcome["state"], "green", entry)
            else:
                self.assertEqual(outcome["state"], "red", entry)

    def test_a_run_without_a_combined_score_is_red(self):
        census = {"judgment": {"artifact_bar": {"runs": [{"axes": {}}] * 2}}}
        outcome = _check("judgment_bar_pass", census, {"runs_min": 2})
        self.assertEqual(outcome["state"], "red")
        self.assertIn("combined score missing", outcome["detail"])

    def test_non_numeric_axis_ratings_do_not_invent_a_modal_axis(self):
        census = {"judgment": {"artifact_bar": {"runs": [
            {"combined": 96, "axes": {"a": "high"}}] * 2}}}
        outcome = _check("judgment_bar_pass", census, {"runs_min": 2})
        self.assertEqual(outcome["state"], "red")
        self.assertIn("no axis ratings recorded", outcome["detail"])

    def test_an_unproven_probe_axis_is_red(self):
        census = {"judgment": {"artifact_bar": {"runs": [{"probes": "at_risk"}]}}}
        self.assertEqual(_check("probes_axis_judged", census)["state"], "red")

    def test_a_run_with_no_probe_axis_is_not_run(self):
        census = {"judgment": {"artifact_bar": {"runs": []}}}
        self.assertEqual(_check("probes_axis_judged", census)["state"], "not_run")

    def test_a_phase_bar_with_no_phase_is_red(self):
        census = {"judgment": {"phase_bar": {"recorded": True, "phases": {}}}}
        self.assertEqual(_check("phase_bar_pass", census)["state"], "red")

    def test_a_phase_that_is_unscored_or_below_the_bar_is_red(self):
        census = {"judgment": {"phase_bar": {
            "recorded": True, "hard_gates": {"pr_merged": True},
            "phases": {"A": {}, "B": {"score": 10, "bar_pass": True}}}}}
        outcome = _check("phase_bar_pass", census)
        self.assertEqual(outcome["state"], "red")
        self.assertIn("A: no score", outcome["detail"])
        self.assertIn("B: 10.0", outcome["detail"])

    def test_a_phase_bar_without_recorded_hard_gates_cannot_pass(self):
        census = {"judgment": {"phase_bar": {"recorded": True, "phases": {
            "A": {"score": 96, "bar_pass": True}}}}}
        outcome = _check("phase_bar_pass", census)
        self.assertEqual(outcome["state"], "red")
        self.assertIn("hard gates not recorded", outcome["detail"])

    def test_a_present_but_unjudged_change_set_is_red(self):
        census = {"judgment": {"change_set": {"present": True, "judged": False}}}
        self.assertEqual(_check("epoch_change_set_judged", census)["state"], "red")

    def test_a_failed_surface_drive_is_red(self):
        census = {"behavior": {"surfaces": {"gui": {"state": "fail"}}}}
        outcome = _check("surface_passed", census, {"surface_key": "gui"})
        self.assertEqual(outcome["state"], "red")
        self.assertIn("gui", outcome["detail"])

    def test_a_surface_bar_with_no_key_is_not_run(self):
        census = {"behavior": {"surfaces": {"gui": {"state": "pass"}}}}
        self.assertEqual(_check("surface_passed", census)["state"], "not_run")

    def test_a_never_defer_drive_that_did_not_complete_is_red(self):
        census = {"behavior": {"never_defer": {"state": "fail"}}}
        self.assertEqual(_check("never_defer_proven", census)["state"], "red")

    def test_an_empty_self_claims_set_is_red(self):
        census = {"census": {"self_claims": {"recorded": True, "total": 0,
                                              "verified": 0}}}
        self.assertEqual(_check("self_claims_verified", census)["state"], "red")

    def test_partially_verified_self_claims_are_red(self):
        census = {"census": {"self_claims": {"recorded": True, "total": 4,
                                              "verified": 3}}}
        outcome = _check("self_claims_verified", census)
        self.assertEqual(outcome["state"], "red")
        self.assertIn("3 of 4", outcome["detail"])

    def test_self_claim_counts_that_do_not_parse_are_not_run(self):
        census = {"census": {"self_claims": {"recorded": True}}}
        self.assertEqual(_check("self_claims_verified", census)["state"], "not_run")

    def test_a_second_ordering_home_fails_the_plan_of_record_bar(self):
        threshold = {"canonical": "docs/jev-roadmap.md", "census_view": "#295"}
        for block in (
            {"canonical": "elsewhere.md", "census_view": "#295",
             "single_home": True, "generated": True},
            {"canonical": "docs/jev-roadmap.md", "census_view": "#400",
             "single_home": True, "generated": True},
            {"canonical": "docs/jev-roadmap.md", "census_view": "#295",
             "single_home": False, "generated": True},
            {"canonical": "docs/jev-roadmap.md", "census_view": "#295",
             "single_home": True, "generated": False},
        ):
            outcome = _check("plan_of_record_single_home",
                             {"plan_of_record": block}, threshold)
            self.assertEqual(outcome["state"], "red", block)


class LoaderRefusalTests(unittest.TestCase):
    def test_a_census_that_is_not_an_object_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "census.json"
            path.write_text("[1, 2]", encoding="utf-8")
            with self.assertRaises(HarnessError):
                load_census(str(path))

    def test_invalid_json_is_refused_for_both_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            with self.assertRaises(HarnessError):
                load_census(str(bad))
            with self.assertRaises(HarnessError):
                load_spec(str(REPO_ROOT), str(bad))

    def test_run_spec_file_requires_a_census_path(self):
        with self.assertRaises(HarnessError):
            run_spec_file(str(REPO_ROOT), "")

    def test_validate_refuses_non_objects_and_missing_ids(self):
        for bad in ([], {"bars": []}, {"id": "x"}, {"id": "x", "frozen": True,
                                                         "bars": ["nope"]}):
            with self.assertRaises(HarnessError):
                validate_spec(bad)

    def test_validate_refuses_unknown_class_and_empty_threshold(self):
        raw = json.loads((REPO_ROOT / SPEC_PATH).read_text(encoding="utf-8"))
        for mutate in (lambda b: b.update({"class": "VIBES"}),
                       lambda b: b.update({"threshold": {}})):
            broken = deepcopy(raw)
            mutate(broken["bars"][0])
            with self.assertRaises(HarnessError):
                validate_spec(broken)

    def test_validate_refuses_a_surface_check_without_a_key(self):
        raw = json.loads((REPO_ROOT / SPEC_PATH).read_text(encoding="utf-8"))
        for bar in raw["bars"]:
            if bar["check"] == "surface_passed":
                bar.pop("surface_key", None)
                break
        with self.assertRaises(HarnessError):
            validate_spec(raw)

    def test_validate_refuses_a_bar_missing_a_required_field(self):
        raw = json.loads((REPO_ROOT / SPEC_PATH).read_text(encoding="utf-8"))
        raw["bars"][0].pop("evidence_surface")
        with self.assertRaises(HarnessError):
            validate_spec(raw)


class RegistryOwnershipTests(unittest.TestCase):
    def test_every_registered_check_is_callable(self):
        for name, fn in spec_mod.CHECKS.items():
            self.assertTrue(callable(fn), name)

    def test_phase_bar_threshold_tracks_the_jev_completion_owner(self):
        spec = load_spec(str(REPO_ROOT))
        bar = {row["id"]: row for row in spec["bars"]}["JUDGMENT-PHASE-BAR"]
        self.assertEqual(bar["threshold"]["min_score"],
                         "jev_completion.PHASE_COMPLETE_MIN_SCORE")
        from harness.jev_completion import PHASE_COMPLETE_MIN_SCORE
        self.assertEqual(PHASE_COMPLETE_MIN_SCORE, 85.0)

    def test_unknown_bar_never_invents_a_pass(self):
        spec = load_spec(str(REPO_ROOT))
        census = load_census(str(BUILD0_CENSUS))
        census.pop("rail")
        board = run_spec(spec, census)
        rail = [row for row in board["bars"] if row["class"] == "RAIL"]
        self.assertEqual({row["state"] for row in rail}, {"not_run"})
        self.assertEqual(board["summary"]["credit"], 0)

    def test_validate_spec_is_what_load_spec_calls(self):
        with mock.patch.object(spec_mod, "validate_spec", wraps=spec_mod.validate_spec) as spy:
            load_spec(str(REPO_ROOT))
        self.assertTrue(spy.called)
