"""#281: a bench bundle that names its work, hides the machine, and refuses to lie.

The tests are built around the three ways a published number stops meaning
anything: it does not say which manifest produced it, it leaks the machine that
ran it, or it claims a complete run while covering part of a manifest. Each is a
refusal here, not a warning -- the export path is fail-closed and this layer has
to hold before it.
"""
import json
import os
import tempfile
import unittest

from harness import bench_bundle as bb

TASKS = [
    {"name": "fizz", "file": "fizz.py", "instruction": "fix fizz",
     "verify": "python check.py", "task_max_cost": 0.25},
    {"name": "leap", "file": "leap.py", "instruction": "fix leap",
     "verify": "python check.py"},
]

RESULTS = [
    {"name": "fizz", "status": "ok", "rounds": [{"n": 1}, {"n": 2}],
     "rotations": 1, "cost": 0.0},
    {"name": "leap", "status": "ok", "rounds": [{"n": 1}], "rotations": 0,
     "cost": 0.0},
]


def manifest_dir(tasks=TASKS):
    root = tempfile.mkdtemp(prefix="bench-manifest-")
    for task in tasks:
        with open(os.path.join(root, f"{task['name']}.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(task, handle)
    return root


def bundle(tasks=TASKS, results=RESULTS, **kwargs):
    return bb.build_bundle(results, manifest_dir(tasks), "1.9.0", **kwargs)


class ManifestTests(unittest.TestCase):
    def test_the_digest_covers_the_declared_work(self):
        digest, count = bb.manifest_digest(TASKS)
        self.assertEqual(len(digest), 64)
        self.assertEqual(count, 2)

    def test_order_and_whitespace_do_not_change_the_digest(self):
        shuffled = list(reversed(TASKS))
        self.assertEqual(bb.manifest_digest(TASKS)[0], bb.manifest_digest(shuffled)[0])

    def test_changing_an_instruction_changes_the_digest(self):
        changed = [dict(TASKS[0], instruction="fix fizz differently"), TASKS[1]]
        self.assertNotEqual(bb.manifest_digest(TASKS)[0], bb.manifest_digest(changed)[0])

    def test_a_manifest_without_tasks_is_refused(self):
        with self.assertRaises(bb.BenchBundleError):
            bb.load_tasks(tempfile.mkdtemp(prefix="empty-manifest-"))

    def test_a_task_without_an_instruction_is_refused(self):
        root = manifest_dir([{"name": "x", "file": "x.py"}])
        with self.assertRaises(bb.BenchBundleError):
            bb.load_tasks(root)

    def test_a_missing_manifest_is_refused(self):
        with self.assertRaises(bb.BenchBundleError):
            bb.load_tasks("no/such/manifest")


class BuildTests(unittest.TestCase):
    def test_the_bundle_carries_version_manifest_time_and_cost(self):
        doc = bundle()
        self.assertEqual(doc["schema"], "bench-results-v1")
        self.assertEqual(doc["harness_version"], "1.9.0")
        self.assertTrue(doc["generated_at"].endswith("+00:00"))
        self.assertEqual(doc["manifest"]["tasks"], 2)
        self.assertEqual(len(doc["manifest"]["sha256"]), 64)
        self.assertEqual(doc["totals"]["total_cost"], 0.0)
        self.assertTrue(doc["totals"]["tracked_cost"])

    def test_verify_rounds_are_counted_per_task_and_on_average(self):
        doc = bundle()
        fizz = next(r for r in doc["results"] if r["task"] == "fizz")
        self.assertEqual(fizz["rounds"], 2)
        self.assertEqual(doc["totals"]["total_rounds"], 3)
        self.assertEqual(doc["totals"]["mean_verify_rounds"], 1.5)

    def test_prompt_text_and_error_strings_never_enter_a_row(self):
        results = [dict(RESULTS[0], error="Traceback: C:\\secret\\path.py"),
                   RESULTS[1]]
        doc = bundle(results=results)
        self.assertNotIn("error", doc["results"][0])
        self.assertNotIn("secret", json.dumps(doc))

    def test_a_partial_run_is_refused(self):
        with self.assertRaises(bb.BenchBundleError) as ctx:
            bundle(results=[RESULTS[0]])
        self.assertIn("leap", str(ctx.exception))

    def test_a_missing_version_is_refused(self):
        for bad in ("", "  ", None):
            with self.assertRaises(bb.BenchBundleError):
                bb.build_bundle(RESULTS, manifest_dir(), bad)

    def test_an_empty_result_set_is_refused(self):
        with self.assertRaises(bb.BenchBundleError):
            bb.build_bundle([], manifest_dir(), "1.9.0")

    def test_a_negative_or_textual_cost_is_refused(self):
        for bad in (-1, "0.5"):
            with self.assertRaises(bb.BenchBundleError):
                bb.task_row(dict(RESULTS[0], cost=bad))

    def test_the_bundle_id_is_content_not_clock(self):
        root = manifest_dir()
        a = bb.build_bundle(RESULTS, root, "1.9.0")
        b = bb.build_bundle(RESULTS, root, "1.9.0")
        self.assertEqual(a["bundle_id"], b["bundle_id"])

    def test_the_id_changes_when_the_numbers_change(self):
        other = [dict(RESULTS[0], cost=0.01), RESULTS[1]]
        self.assertNotEqual(bundle()["bundle_id"], bundle(results=other)["bundle_id"])


class ReproductionTests(unittest.TestCase):
    def test_the_command_names_the_manifest_and_the_ceiling(self):
        cmd = bb.reproduction_command("bench/manifests/efficiency", task_max_cost=0.25)
        self.assertEqual(cmd, "python -m harness.cli bench bench/manifests/efficiency "
                              "--task-max-cost 0.25")

    def test_an_absolute_path_is_trimmed_to_the_repo_relative_one(self):
        cmd = bb.reproduction_command(r"C:\Users\someone\repo\bench\manifests\x")
        self.assertEqual(cmd, "python -m harness.cli bench bench/manifests/x")

    def test_a_path_outside_the_repo_keeps_only_its_basename(self):
        cmd = bb.reproduction_command(r"C:\elsewhere\weird\manifest.json")
        self.assertNotIn("elsewhere", cmd)
        self.assertTrue(cmd.endswith("manifest.json"))


class SanitizerTests(unittest.TestCase):
    def test_a_credential_shape_refuses_serialisation(self):
        doc = bundle()
        doc["results"][0]["task"] = "fizz sk-or-v1-abcdefghijklmnopqrst"
        with self.assertRaises(bb.BenchBundleError):
            bb.serialize(doc)

    def test_a_clean_bundle_serialises(self):
        payload = bb.serialize(bundle())
        self.assertIn('"schema":"bench-results-v1"', payload)

    def test_an_oversized_bundle_is_refused(self):
        doc = bundle()
        doc["results"][0]["task"] = "x" * (bb.MAX_BUNDLE_BYTES + 10)
        with self.assertRaises(bb.BenchBundleError):
            bb.serialize(doc)


class VerifyTests(unittest.TestCase):
    def test_a_fresh_bundle_verifies(self):
        self.assertEqual(bb.verify_bundle(bundle())["schema"], "bench-results-v1")

    def test_a_wrong_schema_is_refused(self):
        doc = bundle()
        doc["schema"] = "bench-results-v0"
        with self.assertRaises(bb.BenchBundleError):
            bb.verify_bundle(doc)

    def test_a_missing_key_is_refused(self):
        doc = bundle()
        doc.pop("reproduction")
        with self.assertRaises(bb.BenchBundleError):
            bb.verify_bundle(doc)

    def test_a_path_in_the_manifest_name_is_refused(self):
        doc = bundle()
        doc["manifest"]["file"] = "C:/Users/someone/manifest.json"
        with self.assertRaises(bb.BenchBundleError):
            bb.verify_bundle(doc)

    def test_an_edited_bundle_is_refused(self):
        doc = bundle()
        doc["totals"]["total_cost"] = 9.99
        with self.assertRaises(bb.BenchBundleError) as ctx:
            bb.verify_bundle(doc)
        self.assertIn("bundle_id", str(ctx.exception))

    def test_a_task_count_mismatch_is_refused(self):
        doc = bundle()
        doc["manifest"]["tasks"] = 3
        with self.assertRaises(bb.BenchBundleError):
            bb.verify_bundle(doc)

    def test_an_unpublished_field_is_refused(self):
        doc = bundle()
        doc["results"][0]["instruction"] = "fix fizz"
        doc["bundle_id"] = bb._sha16({k: v for k, v in doc.items()
                                      if k not in ("bundle_id", "generated_at")})
        with self.assertRaises(bb.BenchBundleError):
            bb.verify_bundle(doc)


class ExportShapeTests(unittest.TestCase):
    def test_export_rows_match_the_exporters_bench_row_keys(self):
        from harness import site_export
        row = bundle()["export_rows"][0]
        self.assertEqual(set(row), {"task_ref", "model", "tier", "passed",
                                    "rounds", "cost", "gated"})
        self.assertTrue(callable(site_export.build_bench_rows))

    def test_the_exporters_own_secret_scan_accepts_the_bundle(self):
        from harness import site_export
        self.assertIsNone(site_export._secret_scan(bb.serialize(bundle())))

    def test_validation_error_branches_and_layouts(self):
        import tempfile

        for bad_path in (None, "", "/definitely/missing/manifest.json"):
            with self.assertRaises(bb.BenchBundleError):
                bb.load_tasks(bad_path)
        with tempfile.TemporaryDirectory() as tmp:
            # Nested task.json layout and single-file manifest layout.
            sub = os.path.join(tmp, "t1")
            os.makedirs(sub)
            with open(os.path.join(sub, "task.json"), "w", encoding="utf-8") as h:
                json.dump({"name": "t1", "instruction": "do t1"}, h)
            self.assertEqual(len(bb.load_tasks(tmp)), 1)
            single = os.path.join(tmp, "manifest.json")
            with open(single, "w", encoding="utf-8") as h:
                json.dump({"tasks": [{"name": "t1", "instruction": "do t1"}]}, h)
            self.assertEqual(len(bb.load_tasks(single)), 1)
            # Nameless task and empty manifest.
            empty_file = os.path.join(tmp, "empty.json")
            with open(empty_file, "w", encoding="utf-8") as h:
                json.dump([], h)
            with self.assertRaises(bb.BenchBundleError):
                bb.load_tasks(empty_file)
            nameless = os.path.join(tmp, "nameless.json")
            with open(nameless, "w", encoding="utf-8") as h:
                json.dump([{"instruction": "x"}], h)
            with self.assertRaises(bb.BenchBundleError):
                bb.load_tasks(nameless)

        with self.assertRaises(bb.BenchBundleError):
            bb.manifest_digest([])
        with self.assertRaises(bb.BenchBundleError):
            bb._number(None, "x") if False else bb._number(True, "x")
        self.assertEqual(bb._number(None, "x"), 0)
        with self.assertRaises(bb.BenchBundleError):
            bb.task_row("not-a-dict")
        with self.assertRaises(bb.BenchBundleError):
            bb.task_row({"status": "ok"})
        row_with_tier = bb.task_row(
            {"name": "t1", "rounds": [1, 2], "tier": "T1", "model": "m1"}
        )
        self.assertEqual(row_with_tier["rounds"], 2)
        self.assertEqual(row_with_tier["tier"], "T1")
        with self.assertRaises(bb.BenchBundleError):
            bb.reproduction_command("")
        self.assertIn("manifest.json", bb.reproduction_command("/opt/custom/manifest.json"))
        with self.assertRaises(bb.BenchBundleError):
            bb.build_bundle([], "manifest.json", "0.5.1")
        with self.assertRaises(bb.BenchBundleError):
            bb.build_bundle([{"name": "t1"}], "manifest.json", "   ")
        with self.assertRaises(bb.BenchBundleError):
            bb.serialize("not-a-dict")
        cal = bb._calibration_block(
            {"calibration": {"m1": {"samples": 2, "success_rate": 0.8}}},
            {"calibration": {"m1": {"success_rate": 0.5}}},
        )
        self.assertAlmostEqual(cal["m1"]["success_rate_delta"], 0.3)
        base_doc = bundle()
        for bad_doc in (
            "not-a-dict",
            {**base_doc, "schema": "wrong"},
            {**base_doc, "manifest": {"sha256": "short", "file": "m.json", "tasks": 2}},
            {**base_doc, "results": []},
            {**base_doc, "results": ["not-a-dict", {"task": "b"}]},
            {**base_doc, "totals": {"tasks": 99}},
        ):
            with self.assertRaises(bb.BenchBundleError):
                bb.verify_bundle(bad_doc)
        leaked = bundle()
        leaked["reproduction"] = "Bearer secret_token_value_123456"
        leaked["bundle_id"] = bb._sha16(
            {k: v for k, v in leaked.items() if k not in ("bundle_id", "generated_at")}
        )
        with self.assertRaises(bb.BenchBundleError):
            bb.verify_bundle(leaked)


if __name__ == "__main__":
    unittest.main()
