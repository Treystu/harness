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
