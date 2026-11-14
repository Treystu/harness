"""#522: priced-but-pathless Fireworks rows are pathless, not absent.

A pack row whose ``path`` is null by design (its snapshot cell is not
``confirmed:``) used to be keyed in the endpoints map by its DISPLAY NAME.
That made a priced model report as "not found in fireworks endpoints pack"
and pushed display names into the direct pool's rate table. Now only a real
dispatch path keys ``endpoints``; a priced-but-pathless row is still priced
and still reported -- via ``pathless``, not as absent.

All hermetic: the committed pack on disk plus one synthetic temp pack and a
canned transport. No network, no live pricing calls.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from harness.config import FIREWORKS_MODEL_PREFIX
from harness.endpoint_pricing import load_fireworks_endpoints
from harness.errors import HarnessError
from harness.spend import SpendGovernor
from tests._fake import FakeTransport


def _synthetic_pack():
    """One routed row plus one pathless row, as plain pack JSON."""
    return {
        "schema": 1,
        "source": "test",
        "captured": "",
        "models": [
            {"name": "Routed Model", "input": 1.0, "cached_input": 0.1,
             "output": 2.0, "slug": "routed-model",
             "path": "accounts/fireworks/models/routed-model"},
            {"name": "Unconfirmed Model", "input": 1.0, "cached_input": 0.1,
             "output": 2.0, "slug": "unconfirmed-model", "path": None},
        ],
    }


class PathlessLoaderTests(unittest.TestCase):
    def test_pathless_rows_are_never_keyed_by_display_name(self):
        # Committed pack: no display name may appear as an endpoint key.
        pack = load_fireworks_endpoints()
        names = {row["name"] for row in pack["models"]}
        for key in pack["endpoints"]:
            self.assertNotIn(key, names,
                             f"display name {key!r} must never key endpoints")
        # Synthetic pack: the pathless row's name keys nothing.
        with tempfile.TemporaryDirectory() as tmp:
            pack_path = Path(tmp) / "fw.json"
            pack_path.write_text(json.dumps(_synthetic_pack()),
                                 encoding="utf-8")
            synth = load_fireworks_endpoints(pack_path=pack_path)
        self.assertEqual(set(synth["endpoints"]),
                         {"accounts/fireworks/models/routed-model"})
        self.assertNotIn("Unconfirmed Model", synth["endpoints"])

    def test_pathless_rows_are_still_priced_and_reported(self):
        # Every model row still loads an offer (pathless rows stay priced),
        # and every pathless slug maps to its display name for reporting.
        pack = load_fireworks_endpoints()
        self.assertEqual(len(pack["offers"]), len(pack["models"]))
        self.assertEqual(pack["pathless"]["glm-5p2"], "GLM 5.2")
        by_slug = {row["slug"]: row for row in pack["models"]}
        for slug in pack["pathless"]:
            self.assertIsNone(by_slug[slug]["path"],
                              f"{slug} is reported pathless but has a path")

    def test_every_endpoint_key_is_a_dispatch_path(self):
        pack = load_fireworks_endpoints()
        self.assertTrue(pack["endpoints"], "the committed pack routes something")
        for key in pack["endpoints"]:
            self.assertTrue(key.startswith(FIREWORKS_MODEL_PREFIX),
                            f"{key!r} is not a dispatch path")

    def test_no_row_silently_vanishes(self):
        pack = load_fireworks_endpoints()
        self.assertEqual(len(pack["endpoints"]) + len(pack["pathless"]),
                         len(pack["models"]))


class PathlessPricingTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.gov = SpendGovernor(
            FakeTransport(), "sk-test",
            byok_prefixes_path=os.path.join(self.dir.name, "byok.json"))

    def tearDown(self):
        self.dir.cleanup()

    def test_pathless_row_says_pathless_not_not_found(self):
        mid = "accounts/fireworks/models/glm-5p2"
        with self.assertRaises(HarnessError) as ctx:
            self.gov.fetch_pricing([mid])
        msg = str(ctx.exception)
        self.assertIn(
            "is priced in the fireworks endpoints pack as 'GLM 5.2'", msg)
        self.assertIn("confirm slug 'glm-5p2'", msg)
        self.assertIn("fireworks-price-snapshot.md", msg)
        self.assertNotIn("not found in fireworks endpoints pack", msg)

    def test_unknown_id_keeps_the_not_found_message(self):
        with self.assertRaises(HarnessError) as ctx:
            self.gov.fetch_pricing(
                ["accounts/fireworks/models/nope-not-priced"])
        self.assertIn("not found in fireworks endpoints pack",
                      str(ctx.exception))

    def test_routable_model_prices_from_the_committed_pack(self):
        mid = "accounts/fireworks/models/deepseek-v4p1-flash"
        prompt, completion = self.gov.fetch_pricing([mid])[mid]
        self.assertAlmostEqual(prompt, 0.3 / 1_000_000)
        self.assertAlmostEqual(completion, 1.2 / 1_000_000)


if __name__ == "__main__":
    unittest.main()
