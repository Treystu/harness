"""#311: deterministic train, export, reload and score for the optional job.

The repo's older train/export suites read `audits/scmessenger/_runs/*`, which
`.gitignore` excludes: an audit artifact that exists on a developer machine and
in no checkout. They keep their guards for the default matrix. This module is
the self-contained exercise the optional job runs -- rows built in-process from
fixed values, a temporary model directory, then the real path: train, export
ONNX + metadata, reload through the enabled scorer, and check the score schema.
"""
import json
import os
import tempfile
import unittest

TASK_TYPES = ("code", "audit", "plan", "chat")
SEAT_ROLES = ("primary", "panel", "judge", "specialist")
EFFORTS = ("none", "low", "high")


def _deps_present():
    try:
        import numpy  # noqa: F401
        import onnx  # noqa: F401
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


needs_train = unittest.skipUnless(
    _deps_present(), "train-time deps (numpy+onnx+onnxruntime) required")


def deterministic_rows(count=30):
    """Fixed rows with a repeating label cycle and no clock or disk input."""
    from harness.local_fit.features import NUMERIC_FEATURES
    from harness.local_fit.schema import SeatRow

    labels = ("unusable", "truncated", "usable_stop")
    rows = []
    for index in range(count):
        features = {
            "task_type": TASK_TYPES[index % len(TASK_TYPES)],
            "seat_role": SEAT_ROLES[index % len(SEAT_ROLES)],
            "reasoning_effort": EFFORTS[index % len(EFFORTS)],
        }
        for position, name in enumerate(NUMERIC_FEATURES):
            features[name] = float((index * 7 + position * 3) % 13)
        rows.append(SeatRow(
            run="fixture-{0:02d}".format(index), seat_index=index,
            features=features, label=labels[index % len(labels)],
            model="fixture/model", task_type=features["task_type"],
            seat_role=features["seat_role"],
        ))
    return rows


class FixtureTests(unittest.TestCase):
    """The fixture itself must be deterministic and shaped for the model."""

    def test_the_fixture_rows_are_deterministic(self):
        first = deterministic_rows(6)
        second = deterministic_rows(6)
        self.assertEqual([row.features for row in first],
                         [row.features for row in second])
        self.assertEqual([row.label for row in first],
                         [row.label for row in second])
        self.assertEqual({row.label for row in first},
                         {"unusable", "truncated", "usable_stop"})


@needs_train
class FeatureShapeTests(unittest.TestCase):
    def test_the_vector_matches_the_declared_length(self):
        from harness.local_fit.features import build_feature_vector, expected_vector_length

        rows = deterministic_rows(3)
        vector = build_feature_vector(rows[0].features, {})
        self.assertEqual(len(vector), expected_vector_length())


@needs_train
class TrainingAndExportTests(unittest.TestCase):
    def test_training_writes_a_model_and_its_metadata(self):
        from harness.local_fit.train import run_pipeline

        rows = deterministic_rows()
        with tempfile.TemporaryDirectory() as directory:
            result = run_pipeline(rows, directory)
            self.assertEqual(result["rows"], len(rows))
            self.assertTrue(os.path.exists(result["model_path"]))
            self.assertTrue(os.path.exists(result["meta_path"]))
            self.assertTrue(result["model_path"].startswith(directory))
            with open(result["meta_path"], encoding="utf-8") as handle:
                meta = json.load(handle)
            self.assertEqual(meta["output_classes"],
                             ["unusable", "truncated", "usable_stop"])
            self.assertEqual(meta["input_dim"], len(meta["feature_order"]))
            self.assertEqual(meta["label_index"]["usable_stop"], 2)

    def test_the_exported_graph_loads_in_onnxruntime(self):
        import numpy as np
        import onnxruntime as ort

        from harness.local_fit.train import build_dataset, compute_stats, run_pipeline

        rows = deterministic_rows()
        with tempfile.TemporaryDirectory() as directory:
            result = run_pipeline(rows, directory)
            stats = compute_stats(rows)
            features, _labels = build_dataset(rows, stats)
            session = ort.InferenceSession(
                result["model_path"], providers=["CPUExecutionProvider"])
            self.assertEqual(session.get_inputs()[0].name, "X")
            logits = session.run(None, {"X": features[:1].astype(np.float32)})[0]
            self.assertEqual(len(logits[0]), 3)
            self.assertTrue(all(float(value) == float(value)
                                for value in logits[0]))


@needs_train
class ReloadAndScoreTests(unittest.TestCase):
    def test_the_enabled_scorer_reloads_the_artifact_and_returns_the_schema(self):
        from harness.local_fit.config import is_enabled, load_scorer
        from harness.local_fit.train import run_pipeline

        rows = deterministic_rows()
        with tempfile.TemporaryDirectory() as directory:
            run_pipeline(rows, directory)
            os.environ["HARNESS_LOCAL_FIT_ENABLE"] = "1"
            os.environ["HARNESS_LOCAL_FIT_MODEL_DIR"] = directory
            try:
                self.assertTrue(is_enabled())
                scorer = load_scorer()
                self.assertIsNotNone(scorer)
                scores = scorer.score(rows[0].features)
            finally:
                os.environ.pop("HARNESS_LOCAL_FIT_ENABLE", None)
                os.environ.pop("HARNESS_LOCAL_FIT_MODEL_DIR", None)
        self.assertEqual(set(scores), {"usable_stop", "truncated", "unusable",
                                       "best_guess"})
        probabilities = {name: scores[name] for name in
                         ("usable_stop", "truncated", "unusable")}
        for value in probabilities.values():
            self.assertIsInstance(value, float)
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)
        self.assertAlmostEqual(sum(probabilities.values()), 1.0, places=5)
        self.assertIn(scores["best_guess"], probabilities)

    def test_the_flag_off_path_stays_inert(self):
        from harness.local_fit.config import is_enabled, load_scorer

        self.assertFalse(is_enabled())
        self.assertIsNone(load_scorer())


if __name__ == "__main__":
    unittest.main()
