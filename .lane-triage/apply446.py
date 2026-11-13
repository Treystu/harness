import pathlib

eco = pathlib.Path("tests/test_economics_cli.py")
src = eco.read_text(encoding="utf-8")

old_imports = ("import io\nimport json\nimport os\nimport tempfile\nimport unittest\n"
               "from contextlib import redirect_stderr, redirect_stdout\nfrom unittest import mock")
new_imports = ("import io\nimport json\nimport os\nimport tempfile\nimport unittest\n"
               "from contextlib import redirect_stderr, redirect_stdout\n"
               "from datetime import datetime, timezone\nfrom unittest import mock")
assert src.count(old_imports) == 1, "import anchor"
src = src.replace(old_imports, new_imports)

old_test = '''    def test_check_fresh_emits_tier_snapshot_freshness(self):
        from harness.cli import _cmd_economics
        opts = build_parser().parse_args(["economics", "--check-fresh", "--json"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            _cmd_economics(opts, mock.Mock())
        payload = json.loads(buf.getvalue())
        self.assertTrue(payload["ok"])
        self.assertIn("age_days", payload)
'''
new_test = '''    def test_check_fresh_emits_tier_snapshot_freshness(self):
        """The check-fresh face emits the freshness payload for a fresh snapshot.

        #446: this assertion used to read the shipped snapshot's wall-clock
        age, so the hermetic suite went red the day the committed artifact
        aged out (2026-11-01) on every head, main included. The contract under
        test is the CLI wiring: payload shape plus the exit-on-stale path. A
        fixture snapshot captured now is pinned here, so the test cannot time
        bomb. Shipped-data currency belongs to the scheduled rankings
        workflow; tests/test_routing_table.py pins the committed artifact's
        shape without comparing it to the clock.
        """
        from harness.cli import _cmd_economics
        opts = build_parser().parse_args(["economics", "--check-fresh", "--json"])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "tiers.snapshot.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({
                    "schema": 1,
                    "captured_at": datetime.now(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"),
                    "max_age_days": 14,
                    "tiers": {},
                }, fh)
            buf = io.StringIO()
            with mock.patch("harness.routing_table.TIERS_SNAPSHOT_PATH", path), \
                    redirect_stdout(buf):
                _cmd_economics(opts, mock.Mock())
        payload = json.loads(buf.getvalue())
        self.assertTrue(payload["ok"])
        self.assertIn("age_days", payload)
        self.assertLess(payload["age_days"], 1.0)
'''
assert src.count(old_test) == 1, "test anchor"
src = src.replace(old_test, new_test)
eco.write_text(src, encoding="utf-8")
print("economics test re-scoped")

rt = pathlib.Path("tests/test_routing_table.py")
rsrc = rt.read_text(encoding="utf-8")
old_head = ('"""Unit tests for task-to-model routing table and OpenRouter floor price controls (#PR-Cost-1)."""\n'
            'import unittest')
new_head = ('"""Unit tests for task-to-model routing table and OpenRouter floor price controls (#PR-Cost-1)."""\n'
            'import json\nimport unittest')
assert rsrc.count(old_head) == 1, "routing import anchor"
rsrc = rsrc.replace(old_head, new_head)

anchor = "    def test_task_class_routing_and_reversible_trial_mode(self):"
new_method = '''    def test_shipped_tier_snapshot_shape_is_deterministic(self):
        """The committed artifact parses and carries a valid timestamp (#446).

        Currency is not asserted here - that is the scheduled rankings job's
        data check, and comparing against the wall clock inside the hermetic
        suite is what made every head red on 2026-11-01. This pins the shape
        and the timestamp's validity so a malformed or timestamp-less
        snapshot fails immediately instead of only when the window expires.
        """
        from datetime import datetime
        from harness.routing_table import TIERS_SNAPSHOT_PATH, load_tier_snapshot

        with open(TIERS_SNAPSHOT_PATH, encoding="utf-8") as fh:
            raw = json.load(fh)
        snap = load_tier_snapshot()
        self.assertEqual(snap["source"], "snapshot")
        self.assertEqual(snap["schema"], 1)
        captured = snap["captured_at"]
        self.assertTrue(captured, "captured_at is empty")
        parsed = datetime.fromisoformat(
            captured[:-1] + "+00:00" if captured.endswith("Z") else captured)
        self.assertIsNotNone(parsed.tzinfo)
        self.assertGreater(int(snap["max_age_days"]), 0)
        for tier in ("T0", "T1", "T2", "T3"):
            self.assertTrue(snap["tiers"][tier], f"{tier} has no models")
        self.assertTrue(raw.get("price_table"), "price_table is empty")
        for model_id, entry in raw["price_table"].items():
            self.assertIsInstance(model_id, str)
            self.assertGreaterEqual(float(entry["prompt_per_token"]), 0.0)
            self.assertGreaterEqual(float(entry["completion_per_token"]), 0.0)

''' + anchor
assert rsrc.count(anchor) == 1, "routing test anchor"
rsrc = rsrc.replace(anchor, new_method)
rt.write_text(rsrc, encoding="utf-8")
print("shipped-snapshot shape test added")
