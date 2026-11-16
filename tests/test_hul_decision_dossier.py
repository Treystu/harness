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


if __name__ == "__main__":
    unittest.main()
