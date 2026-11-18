"""#275 L1-L3: the trace packet, the typed decision and the grade line.

The dossier's action 1 asks for these three lessons to be adopted with hermetic
tests; the tests below are those tests. Each class pins one lesson, and the last
one pins the dossier's own non-goals (L8/L9) so a later "parity" change cannot
quietly turn this module into a completion authority.
"""
import json
import unittest

from harness import hul_decision as hd


class ClipMessageTests(unittest.TestCase):
    def test_prose_is_clipped_and_reports_what_it_dropped(self):
        line = hd.clip_message({"role": "worker", "text": "x" * 5000})
        self.assertEqual(len(line["text"]), hd.TRACE_PROSE_CLIP)
        self.assertEqual(line["dropped"], 1000)

    def test_a_short_message_is_untouched(self):
        line = hd.clip_message({"role": "worker", "text": "short"})
        self.assertEqual(line["text"], "short")
        self.assertEqual(line["dropped"], 0)

    def test_a_tool_call_is_one_line_of_at_most_140_chars(self):
        line = hd.clip_message({"role": "worker", "tool": "read_file",
                                "args": "a" * 400})
        self.assertEqual(line["kind"], "tool")
        self.assertLessEqual(len(line["text"]), hd.TRACE_TOOL_LINE)
        self.assertTrue(line["text"].startswith("tool: read_file"))
        self.assertGreater(line["dropped"], 0)

    def test_a_diff_is_summarized_by_file_count_never_content(self):
        line = hd.clip_message({"role": "worker", "diff": "+++secret",
                                "files": ["a.py", "b.py"]})
        self.assertEqual(line["text"], "diff: 2 file(s) changed")
        self.assertNotIn("secret", line["text"])

    def test_a_non_mapping_message_is_refused(self):
        with self.assertRaises(hd.HulDecisionError):
            hd.clip_message("just a string")


class ClipTraceTests(unittest.TestCase):
    def _messages(self, count, size=1000):
        return [{"role": "worker", "text": f"{index}:" + "x" * size}
                for index in range(count)]

    def test_the_trace_stays_within_its_budget(self):
        trace = hd.clip_trace(self._messages(200), budget=20000)
        self.assertLessEqual(trace["chars"], 20000)
        self.assertGreater(trace["omitted"], 0)

    def test_dropped_earlier_turns_are_marked_not_silently_lost(self):
        trace = hd.clip_trace(self._messages(200), budget=20000)
        self.assertIn(hd.OMITTED_MARKER, trace["lines"])

    def test_the_scope_anchor_is_preserved_and_clipped_to_its_own_cap(self):
        trace = hd.clip_trace(self._messages(5), scope_anchor="goal " * 5000)
        self.assertTrue(trace["anchor_preserved"])
        self.assertTrue(trace["lines"][0].startswith("scope: "))
        self.assertEqual(trace["anchor_dropped"], len("goal " * 5000) - hd.SCOPE_ANCHOR_MAX)

    def test_the_newest_messages_are_the_ones_kept(self):
        trace = hd.clip_trace(self._messages(100), budget=5000)
        self.assertIn("99:", trace["text"])
        self.assertNotIn("0:", trace["text"])

    def test_an_impossible_budget_is_refused(self):
        for budget in (0, -1, "lots", None):
            with self.assertRaises(hd.HulDecisionError):
                hd.clip_trace(self._messages(2), budget=budget)

    def test_the_packet_names_its_schema(self):
        self.assertEqual(hd.clip_trace([])["schema"], "hul-trace@1")


class TypedDecisionTests(unittest.TestCase):
    def _run(self, **overrides):
        payload = {"decision": "run", "why": "the tests still fail",
                   "input": {"skill": "fix-tests", "purpose": "required"},
                   "expectedGain": 2, "confidence": 0.8,
                   "evidence": ["pytest: 3 failed"], "declined": ["rewrite"]}
        payload.update(overrides)
        return payload

    def test_a_run_decision_normalises(self):
        decision = hd.validate_decision(self._run())
        self.assertEqual(decision["decision"], "run")
        self.assertEqual(decision["expectedGain"], 2.0)
        self.assertEqual(decision["input"]["skill"], "fix-tests")
        self.assertEqual(decision["evidence"], ["pytest: 3 failed"])
        self.assertEqual(decision["declined"], ["rewrite"])

    def test_a_label_and_prompt_input_is_accepted(self):
        decision = hd.validate_decision(self._run(
            input={"label": "tighten", "prompt": "clip the trace"}))
        self.assertEqual(decision["input"]["label"], "tighten")
        self.assertEqual(decision["input"]["purpose"], "required")

    def test_json_text_is_parsed_because_the_non_hosted_backends_emit_text(self):
        decision = hd.validate_decision(json.dumps(self._run()))
        self.assertEqual(decision["decision"], "run")

    def test_a_stop_decision_carries_no_input(self):
        decision = hd.validate_decision(
            {"decision": "stop", "why": "outcomes verified",
             "expectedGain": 0, "confidence": 0.9})
        self.assertEqual(decision["decision"], "stop")
        self.assertNotIn("input", decision)

    def test_a_stop_that_also_asks_for_work_is_refused(self):
        with self.assertRaises(hd.HulDecisionError) as ctx:
            hd.validate_decision({"decision": "stop", "why": "done",
                                  "input": {"skill": "more"}})
        self.assertIn("stop", str(ctx.exception))

    def test_a_run_without_an_input_is_refused(self):
        with self.assertRaises(hd.HulDecisionError):
            hd.validate_decision({"decision": "run", "why": "because"})

    def test_an_undeclared_key_is_refused(self):
        with self.assertRaises(hd.HulDecisionError) as ctx:
            hd.validate_decision(self._run(next_prompt="do more"))
        self.assertIn("unknown key", str(ctx.exception))

    def test_an_unknown_decision_is_refused(self):
        with self.assertRaises(hd.HulDecisionError):
            hd.validate_decision(self._run(decision="continue"))

    def test_expected_gain_outside_its_range_is_refused(self):
        for gain in (-0.1, hd.MAX_EXPECTED_GAIN + 0.1, "high", True):
            with self.assertRaises(hd.HulDecisionError):
                hd.validate_decision(self._run(expectedGain=gain))

    def test_confidence_outside_its_range_is_refused(self):
        for confidence in (-0.01, 1.01, None, "sure"):
            with self.assertRaises(hd.HulDecisionError):
                hd.validate_decision(self._run(confidence=confidence))

    def test_an_undeclared_input_purpose_is_refused(self):
        with self.assertRaises(hd.HulDecisionError):
            hd.validate_decision(self._run(input={"skill": "s", "purpose": "polish"}))

    def test_a_blank_why_is_refused(self):
        with self.assertRaises(hd.HulDecisionError):
            hd.validate_decision(self._run(why="   "))


class GradeLineTests(unittest.TestCase):
    def _grades(self, **overrides):
        grades = {"spec": 7, "design": 6, "correctness": 4, "quality": 6}
        grades.update(overrides)
        return grades

    def test_a_grade_line_round_trips(self):
        text = hd.format_grade_line(self._grades(), "correctness")
        parsed = hd.parse_grade_line(text + "\nbody of the report")
        self.assertEqual(parsed["grades"], self._grades())
        self.assertEqual(parsed["biggest_gap"], "correctness")

    def test_the_line_is_the_first_line_of_the_report(self):
        with self.assertRaises(hd.HulDecisionError):
            hd.parse_grade_line("I did some work\nGRADES spec=1")

    def test_a_missing_dimension_is_refused_not_defaulted(self):
        with self.assertRaises(hd.HulDecisionError) as ctx:
            hd.parse_grade_line("GRADES spec=5 design=5 correctness=5; biggest gap: x")
        self.assertIn("quality", str(ctx.exception))

    def test_an_undeclared_dimension_is_refused(self):
        with self.assertRaises(hd.HulDecisionError):
            hd.parse_grade_line("GRADES spec=5 design=5 correctness=5 quality=5 "
                                "polish=3; biggest gap: x")

    def test_a_grade_outside_the_band_is_refused(self):
        for bad in ("11", "-1", "high"):
            with self.assertRaises(hd.HulDecisionError):
                hd.parse_grade_line("GRADES spec={} design=5 correctness=5 "
                                    "quality=5; biggest gap: x".format(bad))

    def test_formatting_refuses_an_impossible_grade(self):
        with self.assertRaises(hd.HulDecisionError):
            hd.format_grade_line(self._grades(spec=11), "spec")

    def test_the_lowest_grade_is_the_steering_target(self):
        self.assertEqual(hd.next_grade_target(self._grades()), ("correctness", 4))

    def test_a_tie_climbs_the_ladder_from_the_bottom(self):
        # spec->design->correctness->quality: equal grades steer at the earlier.
        tie = {"spec": 5, "design": 5, "correctness": 5, "quality": 5}
        self.assertEqual(hd.next_grade_target(tie), ("spec", 5))

    def test_a_missing_dimension_cannot_be_steered_at(self):
        with self.assertRaises(hd.HulDecisionError):
            hd.next_grade_target({"spec": 5})


class ReceiptWindowTests(unittest.TestCase):
    def test_only_the_last_eight_are_shown_and_order_is_oldest_first(self):
        receipts = [{"pass": index, "manager_tokens": index, "worker_tokens": 2 * index,
                     "cost": 0.01, "duration": 3.0} for index in range(12)]
        window = hd.receipts_window(receipts)
        self.assertEqual(len(window), hd.RECEIPT_WINDOW)
        self.assertEqual([r["pass"] for r in window], list(range(4, 12)))

    def test_manager_and_worker_spend_stay_separate(self):
        window = hd.receipts_window([{"pass": 1, "manager_tokens": 10,
                                      "worker_tokens": 90, "cost": 0.02,
                                      "duration": 4.0}])
        self.assertEqual(window[0]["manager_tokens"], 10)
        self.assertEqual(window[0]["worker_tokens"], 90)

    def test_an_impossible_limit_is_refused(self):
        for limit in (0, -3, 1.5):
            with self.assertRaises(hd.HulDecisionError):
                hd.receipts_window([], limit=limit)


class NonGoalTests(unittest.TestCase):
    """L8/L9 are the dossier's stated non-goals: parity work must not build them."""

    def test_this_module_is_not_a_completion_authority(self):
        for name in ("is_complete", "mission_done", "is_finished", "judge_complete"):
            self.assertFalse(hasattr(hd, name), name)

    def test_the_completion_gate_is_not_self_assessed(self):
        # A stop decision is recorded with its why/forecast; the module never
        # turns that into "verified", which is the Jev scope gate's authority.
        decision = hd.validate_decision({"decision": "stop", "why": "looks done",
                                         "expectedGain": 0, "confidence": 0.5})
        self.assertNotIn("verified", decision)
        self.assertNotIn("complete", decision)

    def test_the_trace_carries_no_session_handoff(self):
        # L9: the durable mission pack owns survival; this packet is a view.
        trace = hd.clip_trace([{"role": "worker", "text": "x"}])
        self.assertNotIn("resume", trace)
        self.assertNotIn("session", trace)

    def test_validation_error_branches(self):
        with self.assertRaises(hd.HulDecisionError):
            hd.clip_trace("not-a-list")
        with self.assertRaises(hd.HulDecisionError):
            hd._checked_strings("not-a-list", "evidence")
        with self.assertRaises(hd.HulDecisionError):
            hd.validate_decision("{not valid json")
        with self.assertRaises(hd.HulDecisionError):
            hd.validate_decision(["not-a-dict"])
        with self.assertRaises(hd.HulDecisionError):
            hd.validate_decision({"decision": "stop"})
        d_with_read = hd.validate_decision(
            {"decision": "stop", "why": "done", "read": True}
        )
        self.assertTrue(d_with_read["read"])
        with self.assertRaises(hd.HulDecisionError):
            hd.validate_decision(
                {"decision": "run", "why": "go", "input": {"extra": "bad"}}
            )
        with self.assertRaises(hd.HulDecisionError):
            hd.validate_decision(
                {"decision": "run", "why": "go", "input": {"label": "only-label"}}
            )
        with self.assertRaises(hd.HulDecisionError):
            hd.format_grade_line("not-a-dict", "spec")
        with self.assertRaises(hd.HulDecisionError):
            hd.parse_grade_line(123)
        with self.assertRaises(hd.HulDecisionError):
            hd.next_grade_target("not-a-dict")
        with self.assertRaises(hd.HulDecisionError):
            hd.receipts_window("not-a-list")
        with self.assertRaises(hd.HulDecisionError):
            hd.receipts_window(["not-a-dict"])


class DeclinedCandidateLedgerTests(unittest.TestCase):
    """L4: a declined candidate is remembered, and needs new evidence to return."""

    def _decision(self, **kw):
        base = {"decision": "run", "why": "needs the parser first",
                "input": {"skill": "parser"}, "expectedGain": 2,
                "confidence": 0.8, "evidence": ["trace: parse failed"]}
        base.update(kw)
        return base

    def test_ledger_records_reason_and_evidence(self):
        from harness.hul_decision import declined_candidates
        ledger = declined_candidates([self._decision(declined=["rewrite-module"])])
        self.assertEqual(list(ledger), ["rewrite-module"])
        self.assertEqual(ledger["rewrite-module"][0]["why"], "needs the parser first")
        self.assertEqual(ledger["rewrite-module"][0]["evidence"], ["trace: parse failed"])

    def test_repeated_decline_accumulates_history(self):
        from harness.hul_decision import declined_candidates
        ledger = declined_candidates([
            self._decision(declined=["rewrite-module"], why="too broad"),
            self._decision(declined=["rewrite-module"], why="still too broad"),
        ])
        self.assertEqual([e["why"] for e in ledger["rewrite-module"]],
                         ["too broad", "still too broad"])

    def test_reproposal_needs_new_evidence(self):
        from harness.hul_decision import declined_candidates, may_repropose
        ledger = declined_candidates([self._decision(declined=["rewrite-module"])])
        refused = may_repropose("rewrite-module", ledger=ledger)
        self.assertFalse(refused["allowed"])
        self.assertEqual(refused["reason"], "declined_without_new_evidence")
        allowed = may_repropose("rewrite-module", ledger=ledger,
                                new_evidence=["trace: parser now passes"])
        self.assertTrue(allowed["allowed"])
        self.assertEqual(allowed["reason"], "new_evidence")
        self.assertTrue(may_repropose("other", ledger=ledger)["allowed"])


class CostPerGainFloorTests(unittest.TestCase):
    """L5: a run must buy forecast per unit spend; a stop is never trapped."""

    def _run(self, gain):
        return {"decision": "run", "why": "one more pass",
                "input": {"label": "pass", "prompt": "continue the pass"},
                "expectedGain": gain, "confidence": 0.7}

    def test_run_below_floor_is_refused(self):
        from harness.hul_decision import admissible_run
        out = admissible_run(self._run(1), cost=10.0, max_cost_per_gain=1.0)
        self.assertFalse(out["allowed"])
        self.assertEqual(out["reason"], "below_cost_per_gain_floor")

    def test_run_at_floor_is_admitted(self):
        from harness.hul_decision import admissible_run
        out = admissible_run(self._run(1), cost=1.0, max_cost_per_gain=1.0)
        self.assertTrue(out["allowed"])
        self.assertAlmostEqual(out["cost_per_gain"], 1.0)

    def test_zero_expected_gain_is_never_admissible(self):
        from harness.hul_decision import admissible_run
        out = admissible_run(self._run(0), cost=0.0, max_cost_per_gain=0.0)
        self.assertFalse(out["allowed"])
        self.assertEqual(out["reason"], "no_expected_gain")

    def test_stop_is_always_admissible(self):
        from harness.hul_decision import admissible_run
        out = admissible_run({"decision": "stop", "why": "done", "expectedGain": 0},
                             cost=99.0, max_cost_per_gain=99.0)
        self.assertTrue(out["allowed"])
        self.assertEqual(out["reason"], "stop_spends_nothing")


class PhaseBudgetTests(unittest.TestCase):
    """L6: only the terminal phase may draw on the mission's remaining budget."""

    def test_non_terminal_phase_is_capped(self):
        from harness.hul_decision import phase_budget
        out = phase_budget("build", phase_spent=5, mission_spent=5,
                           total_budget=100, per_phase_cap=20)
        self.assertEqual(out["cap"], 20.0)
        self.assertEqual(out["remaining"], 15.0)
        self.assertFalse(out["unlocked"])

    def test_cumulative_spend_does_not_refuse_a_fresh_phase(self):
        # #579 defect 1: `spent` read as phase spend refused build before it
        # started. The single number means mission spend, so a fresh phase
        # still has its whole cap.
        from harness.hul_decision import phase_budget
        out = phase_budget("build", spent=20, total_budget=100, per_phase_cap=20)
        self.assertEqual(out["remaining"], 20.0)

    def test_a_phase_cannot_exceed_the_mission_room(self):
        # The other half of the same defect: phase spend alone hid earlier
        # phases, so a phase could spend into a mission that was nearly gone.
        from harness.hul_decision import phase_budget
        out = phase_budget("build", phase_spent=0, mission_spent=95,
                           total_budget=100, per_phase_cap=20)
        self.assertEqual(out["remaining"], 5.0)

    def test_one_number_and_two_numbers_together_are_refused(self):
        from harness.hul_decision import HulDecisionError, phase_budget
        with self.assertRaises(HulDecisionError):
            phase_budget("build", spent=5, mission_spent=5,
                         total_budget=100, per_phase_cap=20)
        with self.assertRaises(HulDecisionError):
            phase_budget("build", spent=5, phase_spent=5,
                         total_budget=100, per_phase_cap=20)

    def test_terminal_phase_unlocks_the_remainder(self):
        from harness.hul_decision import phase_budget
        out = phase_budget("terminal", spent=5, total_budget=100, per_phase_cap=20)
        self.assertEqual(out["cap"], 100.0)
        self.assertEqual(out["remaining"], 95.0)
        self.assertTrue(out["unlocked"])

    def test_exhausted_budget_reports_zero_not_negative(self):
        from harness.hul_decision import phase_budget
        self.assertEqual(phase_budget("verify", phase_spent=50, mission_spent=50,
                                      total_budget=100,
                                      per_phase_cap=20)["remaining"], 0.0)

    def test_unknown_phase_is_refused(self):
        from harness.hul_decision import HulDecisionError, phase_budget
        with self.assertRaises(HulDecisionError):
            phase_budget("someday", spent=0, total_budget=1, per_phase_cap=1)


class SubagentBoundaryTests(unittest.TestCase):
    """L11: a subagent cannot be handed work outside its declared namespaces."""

    def test_input_inside_the_boundary_is_admitted(self):
        from harness.hul_decision import subagent_scope
        out = subagent_scope({"decision": "run", "why": "w",
                              "input": {"skill": "parser"}, "expectedGain": 1},
                             may_read=["parser"], may_write=["parser"])
        self.assertTrue(out["allowed"])

    def test_input_outside_the_boundary_is_refused(self):
        from harness.hul_decision import subagent_scope
        out = subagent_scope({"decision": "run", "why": "w",
                              "input": {"skill": "deploy"}, "expectedGain": 1},
                             may_read=["parser"], may_write=["parser"])
        self.assertFalse(out["allowed"])
        self.assertEqual(out["reason"], "outside_write_scope")

    def test_scope_is_read_from_the_validated_input(self):
        # #579 defect 2: the raw payload was checked, so a name the validator
        # trims was compared untrimmed and refused as outside the boundary.
        from harness.hul_decision import subagent_scope
        out = subagent_scope({"decision": "run", "why": "w",
                              "input": {"skill": " parser "}, "expectedGain": 1},
                             may_read=["parser"], may_write=["parser"])
        self.assertTrue(out["allowed"])
        self.assertEqual(out["target"], "parser")

    def test_a_json_string_decision_is_scoped_the_same_way(self):
        from harness.hul_decision import subagent_scope
        payload = json.dumps({"decision": "run", "why": "w",
                              "input": {"label": " deploy ", "prompt": "p"},
                              "expectedGain": 1})
        refused = subagent_scope(payload, may_read=["parser"], may_write=["parser"])
        self.assertFalse(refused["allowed"])
        self.assertEqual(refused["reason"], "outside_write_scope")
        self.assertEqual(refused["target"], "deploy")

    def test_empty_boundary_is_a_declaration_error(self):
        from harness.hul_decision import HulDecisionError, subagent_scope
        with self.assertRaises(HulDecisionError):
            subagent_scope({"decision": "run", "why": "w",
                            "input": {"skill": "parser"}, "expectedGain": 1},
                           may_read=[], may_write=["parser"])


class CancellationRecordTests(unittest.TestCase):
    """L12: a cancel leaves a record the next seat can resume from."""

    GRADES = {"spec": 7, "design": 9, "correctness": 6, "quality": 8}

    def test_record_carries_phase_grades_and_next_target(self):
        from harness.hul_decision import cancellation_record
        out = cancellation_record(phase="build", grades=self.GRADES,
                                  cancelled_at="2026-11-17T05:00:00Z")
        self.assertTrue(out["resumable"])
        self.assertEqual(out["phase"], "build")
        self.assertEqual(out["next_grade_target"], ("correctness", 6))
        self.assertEqual(out["receipts"], [])

    def test_record_carries_declines_and_scope_anchor(self):
        from harness.hul_decision import cancellation_record
        out = cancellation_record(
            phase="build", grades=self.GRADES,
            cancelled_at="2026-11-17T05:00:00Z",
            decisions=[{"decision": "run", "why": "too broad",
                        "input": {"skill": "rewrite"}, "expectedGain": 1,
                        "declined": ["rewrite-everything"]}],
            scope_anchor="ship the parser fix")
        self.assertIn("rewrite-everything", out["declined"])
        self.assertEqual(out["scope_anchor"], "ship the parser fix")

    def test_record_without_grades_is_refused(self):
        from harness.hul_decision import HulDecisionError, cancellation_record
        with self.assertRaises(HulDecisionError):
            cancellation_record(phase="build", grades={},
                                cancelled_at="2026-11-17T05:00:00Z")

class HulDossierRefusalPathTests(unittest.TestCase):
    """Every added refusal/edge line must be executed (D12: changed lines).

    These are the branches the positive-path tests above do not reach: type
    refusals, invalid floors, the read-scope half of the subagent boundary, the
    string-decision input path, receipts pass-through and the cancellation
    refusals. They exist because a coverage gate measures them, and because an
    unexecuted refusal is a refusal nobody has seen work.
    """

    def test_declined_candidates_refuses_non_sequence(self):
        from harness.hul_decision import HulDecisionError, declined_candidates
        with self.assertRaises(HulDecisionError):
            declined_candidates("not-a-list")
        self.assertEqual(declined_candidates(None), {})

    def test_may_repropose_refuses_non_mapping_ledger(self):
        from harness.hul_decision import HulDecisionError, may_repropose
        with self.assertRaises(HulDecisionError):
            may_repropose("x", ledger=["nope"])

    def test_may_repropose_reports_prior_reasons(self):
        from harness.hul_decision import declined_candidates, may_repropose
        ledger = declined_candidates([{"decision": "run", "why": "too broad",
                                       "input": {"skill": "s"}, "expectedGain": 1,
                                       "declined": ["wide"]}])
        out = may_repropose("wide", ledger=ledger)
        self.assertEqual(out["prior_reasons"], ["too broad"])

    def test_admissible_run_refuses_invalid_arguments(self):
        from harness.hul_decision import HulDecisionError, admissible_run
        run = {"decision": "run", "why": "w", "input": {"skill": "s"},
               "expectedGain": 1}
        with self.assertRaises(HulDecisionError):
            admissible_run(run, cost=1, max_cost_per_gain=-1)
        with self.assertRaises(HulDecisionError):
            admissible_run(run, cost=1, max_cost_per_gain=1, min_expected_gain=-1)
        with self.assertRaises(HulDecisionError):
            admissible_run(run, cost=-1, max_cost_per_gain=1)

    def test_admissible_run_min_expected_gain_gate(self):
        from harness.hul_decision import admissible_run
        run = {"decision": "run", "why": "w", "input": {"skill": "s"},
               "expectedGain": 1}
        out = admissible_run(run, cost=1, max_cost_per_gain=1, min_expected_gain=2)
        self.assertFalse(out["allowed"])
        self.assertEqual(out["reason"], "below_min_expected_gain")

    def test_admissible_run_zero_cost_has_unbounded_ratio(self):
        from harness.hul_decision import admissible_run
        run = {"decision": "run", "why": "w", "input": {"skill": "s"},
               "expectedGain": 1}
        out = admissible_run(run, cost=0, max_cost_per_gain=5)
        self.assertTrue(out["allowed"])
        self.assertEqual(out["cost_per_gain"], float("inf"))

    def test_phase_budget_refuses_negative_spend(self):
        from harness.hul_decision import HulDecisionError, phase_budget
        with self.assertRaises(HulDecisionError):
            phase_budget("build", spent=-1, total_budget=10, per_phase_cap=5)

    def test_phase_cap_never_exceeds_total_budget(self):
        from harness.hul_decision import phase_budget
        out = phase_budget("survey", spent=0, total_budget=10, per_phase_cap=50)
        self.assertEqual(out["cap"], 10.0)
        self.assertFalse(out["unlocked"])

    def test_subagent_read_scope_is_enforced_separately(self):
        from harness.hul_decision import subagent_scope
        out = subagent_scope({"decision": "run", "why": "w", "read": True,
                              "input": {"skill": "parser"}, "expectedGain": 1},
                             may_read=["reader"], may_write=["parser"])
        self.assertFalse(out["allowed"])
        self.assertEqual(out["reason"], "outside_read_scope")

    def test_subagent_accepts_a_json_string_decision(self):
        from harness.hul_decision import subagent_scope
        out = subagent_scope('{"decision": "run", "why": "w", '
                             '"input": {"skill": "parser"}, "expectedGain": 1}',
                             may_read=["parser"], may_write=["parser"])
        self.assertTrue(out["allowed"])

    def test_subagent_stop_is_always_within_boundary(self):
        from harness.hul_decision import subagent_scope
        out = subagent_scope({"decision": "stop", "why": "done"},
                             may_read=["parser"], may_write=["parser"])
        self.assertTrue(out["allowed"])
        self.assertEqual(out["reason"], "stop_touches_nothing")

    def test_cancellation_refuses_unknown_phase_and_missing_stamp(self):
        from harness.hul_decision import HulDecisionError, cancellation_record
        grades = {"spec": 1, "design": 1, "correctness": 1, "quality": 1}
        with self.assertRaises(HulDecisionError):
            cancellation_record(phase="someday", grades=grades,
                                cancelled_at="2026-11-17T05:00:00Z")
        with self.assertRaises(HulDecisionError):
            cancellation_record(phase="build", grades=grades, cancelled_at="")

    def test_cancellation_carries_the_receipt_window(self):
        from harness.hul_decision import cancellation_record
        grades = {"spec": 9, "design": 9, "correctness": 9, "quality": 9}
        out = cancellation_record(
            phase="verify", grades=grades, cancelled_at="2026-11-17T05:00:00Z",
            receipts=[{"kind": "attempt", "model": "m", "tokens": 10,
                       "cost": 0.1, "duration": 1.5}])
        self.assertEqual(len(out["receipts"]), 1)
        self.assertEqual(out["next_grade_target"], ("spec", 9))

if __name__ == "__main__":
    unittest.main()
