"""#280: the first rung moves on evidence, and an unusable structured sample rotates.

The issue's own numbers are the fixtures: the declared head succeeded 1/3 on the
structured class while a challenger is measured well above it. What the tests
insist on is the discipline around that promotion -- no data means the declared
ladder, thin data cannot move the head, a struck model is never promoted, a tie
keeps the declared order, and rotation is counted per sample with its own reason
rather than hidden in a binary failure count.
"""
import json
import unittest

from harness import first_rung as fr


def report(**rows):
    return {"calibration": rows}


def row(success, samples, structured=True, unusable=0):
    key = "structured_success_rate" if structured else "success_rate"
    key_n = "structured_samples" if structured else "samples"
    out = {key: success, key_n: samples}
    if unusable:
        out["unusable_outputs"] = unusable
    return out


POOL = ["openrouter/free", "cheap/paid-a", "strong/paid-b"]


class FallbackTests(unittest.TestCase):
    def test_no_report_at_all_keeps_the_declared_ladder(self):
        spec = fr.choose_first_rung(POOL, None)
        self.assertEqual(spec["source"], "declared")
        self.assertEqual(spec["first"], POOL[0])
        self.assertEqual(spec["order"], POOL)
        self.assertIn("no recorded calibration", spec["reasons"][0])

    def test_an_empty_calibration_block_keeps_the_declared_ladder(self):
        spec = fr.choose_first_rung(POOL, {"calibration": {}})
        self.assertEqual(spec["source"], "declared")
        self.assertEqual(spec["order"], POOL)

    def test_models_with_no_samples_count_as_no_history(self):
        rep = report(**{"cheap/paid-a": {"structured_success_rate": 0.9,
                                        "structured_samples": 0}})
        self.assertFalse(fr.has_calibration(rep, POOL))
        self.assertEqual(fr.choose_first_rung(POOL, rep)["source"], "declared")

    def test_a_single_model_pool_is_its_own_answer(self):
        spec = fr.choose_first_rung(["only/model"], report(**{"only/model": row(0.9, 9)}))
        self.assertEqual(spec["first"], "only/model")
        self.assertIn("only declared model", spec["reasons"][0])

    def test_an_empty_pool_is_refused(self):
        for bad in ([], None, ["", None]):
            with self.assertRaises(fr.FirstRungError):
                fr.choose_first_rung(bad)


class PromotionTests(unittest.TestCase):
    def test_a_strong_measured_challenger_takes_the_first_rung(self):
        rep = report(**{"openrouter/free": row(0.333, 12),
                        "cheap/paid-a": row(0.9, 12)})
        spec = fr.choose_first_rung(POOL, rep)
        self.assertEqual(spec["first"], "cheap/paid-a")
        self.assertEqual(spec["source"], "calibration")
        self.assertEqual(spec["order"][0], "cheap/paid-a")
        self.assertEqual(spec["order"][1:], ["openrouter/free", "strong/paid-b"])
        self.assertIn("promoted", spec["reasons"][0])

    def test_the_margin_decides_a_close_race(self):
        rep = report(**{"openrouter/free": row(0.80, 10),
                        "cheap/paid-a": row(0.85, 10)})
        self.assertEqual(fr.choose_first_rung(POOL, rep)["first"], POOL[0])
        self.assertEqual(fr.choose_first_rung(POOL, rep, margin=0.02)["first"],
                         "cheap/paid-a")

    def test_a_tie_keeps_the_declared_head(self):
        rep = report(**{"openrouter/free": row(0.8, 10), "cheap/paid-a": row(0.8, 10)})
        spec = fr.choose_first_rung(POOL, rep)
        self.assertEqual(spec["first"], POOL[0])
        self.assertIn("kept", spec["reasons"][0])

    def test_thin_data_cannot_move_the_head(self):
        rep = report(**{"openrouter/free": row(0.0, 1), "cheap/paid-a": row(1.0, 1)})
        spec = fr.choose_first_rung(POOL, rep)
        self.assertEqual(spec["first"], POOL[0])
        self.assertIn("below the", spec["reasons"][0])

    def test_a_struck_model_is_never_promoted(self):
        rep = report(**{"openrouter/free": row(0.5, 10),
                        "cheap/paid-a": row(0.99, 10, unusable=2)})
        spec = fr.choose_first_rung(POOL, rep)
        self.assertEqual(spec["first"], POOL[0])
        self.assertFalse(spec["candidates"][1]["promotable"])

    def test_an_unmeasured_head_loses_to_a_measured_challenger(self):
        rep = report(**{"cheap/paid-a": row(0.95, 20)})
        spec = fr.choose_first_rung(POOL, rep)
        self.assertEqual(spec["first"], "cheap/paid-a")
        self.assertIn("unmeasured", spec["reasons"][-1])

    def test_an_unknown_calibration_row_is_ignored(self):
        rep = report(**{"not/in/the/pool": row(0.99, 50)})
        spec = fr.choose_first_rung(POOL, rep)
        self.assertEqual(spec["first"], POOL[0])
        self.assertEqual(spec["source"], "declared")

    def test_the_success_rate_must_be_numeric(self):
        rep = report(**{"openrouter/free": {"structured_success_rate": "high",
                                            "structured_samples": 9}})
        self.assertFalse(fr.calibration_for(rep, "openrouter/free")["present"])

    def test_a_bad_floor_or_margin_is_refused(self):
        for kwargs in ({"min_samples": 0}, {"margin": -0.1}):
            with self.assertRaises(fr.FirstRungError):
                fr.choose_first_rung(POOL, None, **kwargs)

    def test_the_spec_is_deterministic(self):
        rep = report(**{"openrouter/free": row(0.333, 12),
                        "cheap/paid-a": row(0.9, 12)})
        self.assertEqual(fr.choose_first_rung(POOL, rep), fr.choose_first_rung(POOL, rep))

    def test_a_code_class_uses_the_unstructured_fields(self):
        rep = report(**{"openrouter/free": row(0.4, 8, structured=False),
                        "cheap/paid-a": row(0.9, 8, structured=False)})
        spec = fr.choose_first_rung(POOL, rep, task="code")
        self.assertEqual(spec["first"], "cheap/paid-a")

    def test_route_reasons_refuses_a_spec_without_any(self):
        with self.assertRaises(fr.FirstRungError):
            fr.route_reasons({"first": POOL[0], "reasons": []})

    def test_route_reasons_prints_what_was_decided(self):
        spec = fr.choose_first_rung(POOL, None)
        self.assertEqual(fr.route_reasons(spec), spec["reasons"])


class RotationTests(unittest.TestCase):
    def test_one_unusable_structured_sample_rotates_by_default(self):
        rot = fr.StructuredRotation()
        entry = rot.record("openrouter/free", ok=False,
                           reason="structured_output_unparseable")
        self.assertTrue(entry["rotates_out"])
        self.assertEqual(entry["sample"], 1)
        self.assertTrue(rot.rotates_out("openrouter/free"))

    def test_the_limit_is_configurable(self):
        rot = fr.StructuredRotation(limit=2)
        self.assertFalse(rot.record("m", False,
                                    reason="structured_output_empty")["rotates_out"])
        self.assertTrue(rot.record("m", False,
                                   reason="structured_output_empty")["rotates_out"])

    def test_a_clean_structured_response_resets_the_streak(self):
        rot = fr.StructuredRotation(limit=2)
        rot.record("m", False, reason="structured_output_missing_fields")
        rot.record("m", True)
        entry = rot.record("m", False, reason="structured_output_missing_fields")
        self.assertFalse(entry["rotates_out"])
        self.assertEqual(rot.streak("m"), 1)

    def test_a_success_clears_a_previous_rotation(self):
        rot = fr.StructuredRotation()
        rot.record("m", False, reason="structured_output_unparseable")
        rot.record("m", True)
        self.assertFalse(rot.rotates_out("m"))

    def test_the_reason_must_be_a_known_structured_reason(self):
        rot = fr.StructuredRotation()
        with self.assertRaises(fr.FirstRungError):
            rot.record("m", False, reason="timeout")

    def test_an_unknown_limit_is_refused(self):
        for bad in (0, -1, True, 1.5, "1"):
            with self.assertRaises(fr.FirstRungError):
                fr.StructuredRotation(limit=bad)

    def test_eligible_never_empties_the_pool(self):
        rot = fr.StructuredRotation()
        rot.record("a", False, reason="structured_output_unparseable")
        rot.record("b", False, reason="structured_output_unparseable")
        self.assertEqual(rot.eligible(["a", "b"]), ["b"])

    def test_a_rotation_is_recorded_with_its_own_reason(self):
        rot = fr.StructuredRotation()
        rot.record("openrouter/free", False,
                   reason="structured_output_unparseable")
        lines = rot.reasons()
        self.assertEqual(len(lines), 1)
        self.assertIn("structured_output_unparseable", lines[0])
        self.assertIn("1/1 sample", lines[0])

    def test_the_records_serialise_for_the_ledger(self):
        rot = fr.StructuredRotation()
        rot.record("m", False, reason="structured_output_empty")
        rows = json.loads(rot.to_json())
        self.assertEqual(rows[0]["reason"], "structured_output_empty")
        self.assertTrue(rows[0]["rotates_out"])

    def test_rotation_composes_with_the_first_rung(self):
        rep = report(**{"openrouter/free": row(0.333, 12),
                        "cheap/paid-a": row(0.9, 12)})
        rot = fr.StructuredRotation()
        rot.record("cheap/paid-a", False, reason="structured_output_unparseable")
        spec = fr.choose_first_rung(POOL, rep)
        self.assertEqual(rot.eligible(spec["order"]), ["openrouter/free", "strong/paid-b"])


if __name__ == "__main__":
    unittest.main()
