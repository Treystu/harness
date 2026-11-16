"""#283: the handler inventory is taken from the code, and every route has a test.

Written for an Electron main process that does not exist; the issue's own
dependency clause says to rescope to the equivalent server-side handlers and
record the disposition rather than invent a layer to test. So these tests pin
three things:

* the route table is **derived from `harness/server.py`**, not hand-listed --
  a new route with no test shows up as a failure rather than as silence;
* match semantics match the server's (exact, then longest prefix, then nothing);
* the rescope disposition is recorded where a reader will find it.
"""
import os
import unittest

from harness import api_inventory as inv
from harness import server as ui_server

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_SOURCE = os.path.join(REPO, "harness", "server.py")


class InventoryShapeTests(unittest.TestCase):
    def setUp(self):
        self.inv = inv.inventory(SERVER_SOURCE)

    def test_the_inventory_comes_from_the_shipped_handler_source(self):
        self.assertEqual(self.inv["source"], "server.py")
        self.assertGreaterEqual(len(self.inv["routes"]), 40)

    def test_both_verb_blocks_are_parsed(self):
        self.assertIn("GET", self.inv["counts"])
        self.assertIn("POST", self.inv["counts"])
        self.assertGreaterEqual(self.inv["counts"]["GET"], 25)
        self.assertGreaterEqual(self.inv["counts"]["POST"], 10)

    def test_known_routes_are_present(self):
        for path in ("/api/status", "/api/missions", "/api/ledger/verify"):
            self.assertIn(path, self.inv["by_method"]["GET"])
        for path in ("/api/chat", "/api/driver/step", "/api/intake"):
            self.assertIn(path, self.inv["by_method"]["POST"])

    def test_no_route_is_declared_twice(self):
        keys = [(r["method"], r["path"]) for r in self.inv["routes"]]
        self.assertEqual(len(keys), len(set(keys)))

    def test_the_prefix_route_is_kept(self):
        self.assertIn("/site/", self.inv["by_method"]["GET"])

    def test_the_dynamic_run_subresource_is_inventoried(self):
        self.assertIn("/api/runs/<run_id>/cancel", self.inv["by_method"]["POST"])

    def test_an_unknown_source_is_refused_not_silently_empty(self):
        with self.assertRaises(inv.InventoryError):
            inv.parse_routes("def hello():\n    pass\n")


class MatchTests(unittest.TestCase):
    def setUp(self):
        self.routes = inv.inventory(SERVER_SOURCE)["routes"]

    def test_an_exact_route_matches(self):
        self.assertEqual(inv.match(self.routes, "GET", "/api/status")["path"],
                         "/api/status")

    def test_methods_do_not_cross(self):
        self.assertIsNone(inv.match(self.routes, "PUT", "/api/status"))

    def test_a_post_only_route_is_unknown_to_get(self):
        self.assertIsNone(inv.match(self.routes, "GET", "/api/intake"))

    def test_a_prefix_route_covers_its_children(self):
        hit = inv.match(self.routes, "GET", "/site/index.html")
        self.assertEqual(hit["path"], "/site/")

    def test_an_unknown_path_has_no_route(self):
        self.assertIsNone(inv.match(self.routes, "GET", "/api/definitely-not-a-route"))


class RescopeTests(unittest.TestCase):
    def test_the_disposition_is_recorded(self):
        self.assertIn("No Electron main process exists", inv.RESCOPE)

    def test_no_electron_main_process_exists_in_the_repo(self):
        # The claim behind the rescope, measured rather than asserted.
        for name in ("main.js", "preload.js", "electron-builder.json"):
            self.assertFalse(os.path.exists(os.path.join(REPO, name)), name)
        self.assertTrue(os.path.exists(os.path.join(REPO, "tests", "ui",
                                                    "package.json")))


class CoverageGateTests(unittest.TestCase):
    def test_every_route_has_at_least_one_behaviour_test(self):
        routes = inv.inventory(SERVER_SOURCE)["routes"]
        report = inv.coverage(routes, os.path.join(REPO, "tests"))
        self.assertEqual(report["uncovered"], [],
                         "routes with no test and no declared reason")
        self.assertGreaterEqual(len(report["covered"]), 40)

    def test_the_gate_refuses_an_undeclared_uncovered_route(self):
        routes = [{"method": "GET", "path": "/api/never-tested", "kind": "exact"}]
        with self.assertRaises(inv.InventoryError):
            inv.coverage_gate(routes, os.path.join(REPO, "tests"))

    def test_the_gate_accepts_a_declared_exemption(self):
        routes = [{"method": "GET", "path": "/api/never-tested", "kind": "exact"}]
        report = inv.coverage_gate(
            routes, os.path.join(REPO, "tests"),
            exemptions={"/api/never-tested": "declared for this test"})
        self.assertEqual(report["uncovered"], ["/api/never-tested"])

    def test_the_handler_class_is_the_one_we_inventoried(self):
        self.assertTrue(hasattr(ui_server, "UiRequestHandler"))
        self.assertTrue(hasattr(ui_server.UiRequestHandler, "do_GET"))
        self.assertTrue(hasattr(ui_server.UiRequestHandler, "do_POST"))


if __name__ == "__main__":
    unittest.main()
