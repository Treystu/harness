"""Fold-parity tests: the Python rollup fold vs the worker's JS fold.

The worker folds accepted bundles into a KV rollup at the edge; the nightly
CI rebuild recomputes authoritatively from D1 with the Python fold. These
tests pin the parity twice: (1) against shared fixture vectors both sides
consume, (2) live, by executing the worker's actual JS through node when
available (skipped cleanly when node is absent, e.g. minimal CI).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.site_aggregate import fold_rollup

_VECTORS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "fixtures", "site_fold_vectors.json")
_WORKER_JS = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "site", "worker", "index.js")


def _cases():
    with open(_VECTORS, encoding="utf-8") as f:
        return json.load(f)["cases"]


def _worker_url():
    r"""file:// URL form of the worker path (ESM on Windows rejects C:\ paths)."""
    return "file:///" + _WORKER_JS.replace("\\", "/").lstrip("/").replace(
        " ", "%20") if os.name == "nt" else "file://" + quote(_WORKER_JS)


class FoldParityPythonTests(unittest.TestCase):
    def test_python_fold_matches_expected_vectors(self):
        for case in _cases():
            with self.subTest(case=case["name"]):
                out = fold_rollup(case["previous"], case["bundle"])
                self.assertEqual(out, case["expected"])

    def test_fold_is_pure_and_chainable(self):
        case = _cases()[0]
        first = fold_rollup(case["previous"], case["bundle"])
        again = fold_rollup(case["previous"], case["bundle"])
        self.assertEqual(first, again)
        chained = fold_rollup(first, case["bundle"])  # idempotent per bundle_id
        self.assertEqual(chained["contributors"], first["contributors"])


class FoldParityWorkerTests(unittest.TestCase):
    """Execute the worker's real foldRollup over the same vectors via node."""

    def setUp(self):
        self.node = shutil.which("node")
        if not self.node:
            self.skipTest("platform: node not available; JS parity asserted in CI")

    def _run_worker_fold(self, previous, bundle):
        harness_js = (
            f"import {{ foldRollup }} from '{_worker_url()}';\n"
            f"const previous = {json.dumps(previous)};\n"
            f"const bundle = {json.dumps(bundle)};\n"
            f"process.stdout.write(JSON.stringify(foldRollup(previous, bundle)));\n")
        with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False) as f:
            f.write(harness_js)
            path = f.name
        try:
            proc = subprocess.run([self.node, path], capture_output=True,
                                  text=True, timeout=30)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        if proc.returncode != 0:
            self.fail(f"worker fold failed: {proc.stderr[-300:]}")
        return json.loads(proc.stdout)

    def test_worker_fold_matches_expected_vectors(self):
        for case in _cases():
            with self.subTest(case=case["name"]):
                out = self._run_worker_fold(case["previous"], case["bundle"])
                self.assertEqual(out, case["expected"])


class WorkerValidationParityTests(unittest.TestCase):
    """The worker's essential validate/floor mirrors must match the Python
    contract on the vectors that matter (refusals + floor scan order)."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("platform: node not available; JS parity asserted in CI")

    def _eval(self, expr):
        path = tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False)
        path.write(
            f"import {{ validateBundle, tierFloorForGoal }} from "
            f"'{_worker_url()}';\n"
            f"process.stdout.write(JSON.stringify({expr}));\n")
        path.close()
        try:
            proc = subprocess.run([shutil.which("node"), path.name],
                                  capture_output=True, text=True, timeout=30)
        finally:
            os.unlink(path.name)
        self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
        return json.loads(proc.stdout)

    def test_worker_accepts_valid_bundle_shape(self):
        bundle = {
            "schema": "site-bundle-v1", "bundle_id": "0123456789abcdef",
            "consent": {"schema": "site-consent-v1",
                        "accepted_at": "2026-09-21T00:00:00Z",
                        "surface": "test"},
            "chain": {"verified_claim": True, "head_hash": "h", "entries": 1},
            "runs": [{"run_id": "r", "task_ref": "t", "lane": "bench",
                      "outcome": "pass", "cost": 0.0, "gated": True}],
        }
        self.assertIsNone(self._eval(f"validateBundle({json.dumps(bundle)})"))

    def test_worker_refuses_consentless_and_secrets(self):
        bundle = {"schema": "site-bundle-v1", "bundle_id": "0123456789abcdef",
                  "runs": []}
        err = self._eval(f"validateBundle({json.dumps(bundle)})")
        self.assertIn("consent", err)
        bundle["consent"] = {"schema": "site-consent-v1",
                             "accepted_at": "x", "surface": "y"}
        bundle["chain"] = {"verified_claim": True, "head_hash": "h"}
        bundle["runs"] = []
        bundle["capabilities"] = [{"model": "sk-or-v1-0123456789abcdef0123"}]
        err = self._eval(f"validateBundle({json.dumps(bundle)})")
        self.assertIn("credential", err)

    def test_worker_floor_scan_order_matches_python(self):
        cases = {
            "fix a typo in the comment": "T0",
            "fix the race in the token bucket": "T2",
            "design the architecture for the protocol": "T3",
            "implement a retry queue": "T1",
            "": "T0",
        }
        for goal, expected in cases.items():
            with self.subTest(goal=goal):
                got = self._eval(f"tierFloorForGoal({json.dumps(goal)})")
                self.assertEqual(got, expected)


class WorkerSystemOneRouteTests(unittest.TestCase):
    """#420: Cloudflare Worker uses the documented TypeSafe System One contract."""

    PACK = {
        "id": "site-demo-ladder",
        "rungs": [
            {"rung_id": "r0", "tier": "T0", "model": "declared-by-operator",
             "cost_class": "free", "guidance": ["typo", "rename"]},
            {"rung_id": "r1", "tier": "T1", "model": "declared-by-operator",
             "cost_class": "cheap", "guidance": ["implement", "fix"]},
            {"rung_id": "r2", "tier": "T2", "model": "declared-by-operator",
             "cost_class": "moderate", "observed_success": 0.91, "samples": 11,
             "guidance": ["concurrency", "invariant"]},
        ],
    }

    def setUp(self):
        self.node = shutil.which("node")
        if not self.node:
            self.skipTest("platform: node not available; JS worker asserted in CI")

    def _run_js(self, script_body):
        with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False) as f:
            f.write(script_body)
            path = f.name
        try:
            proc = subprocess.run([self.node, path],
                                  capture_output=True, text=True, timeout=30)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
        return json.loads(proc.stdout)

    def _run_handle_route(self, body, *, env_cfg=None, initial_kv=None,
                          fetch_script="throw new Error('unexpected fetch')"):
        env_cfg = env_cfg or {}
        initial_kv = initial_kv or {}
        script = f"""
import {{ handleRoute, CANONICAL_JEV_ENDPOINT }} from '{_worker_url()}';
const kv = new Map(Object.entries({json.dumps(initial_kv)}));
const puts = [];
const fetches = [];
const env = {{
  ROLLUP: {{
    async get(key, mode) {{
      const v = kv.get(key);
      if (v === undefined) return null;
      return mode === "json" ? JSON.parse(v) : v;
    }},
    async put(key, val, opts) {{
      puts.push({{ key, val: JSON.parse(val), opts }});
      kv.set(key, val);
    }},
  }},
  ROUTE_LIMIT: {{ async limit() {{ return {{ success: true }}; }} }},
  ROUTE_DAILY_BUDGET: "200",
  ...{json.dumps(env_cfg)},
}};
const request = new Request("https://bench.example/api/route", {{
  method: "POST",
  headers: {{ "content-type": "application/json", "cf-connecting-ip": "1.2.3.4" }},
  body: JSON.stringify({json.dumps(body)}),
}});
const fetchFn = async (url, init) => {{
  fetches.push({{
    url,
    method: init.method,
    headers: init.headers,
    body: JSON.parse(init.body),
  }});
  {fetch_script}
}};
const res = await handleRoute(request, env, fetchFn);
const out = await res.json();
process.stdout.write(JSON.stringify({{
  status: res.status,
  out,
  fetches,
  puts,
  kvKeys: [...kv.keys()],
  canonicalEndpoint: CANONICAL_JEV_ENDPOINT,
}}));
"""
        return self._run_js(script)

    def test_contract_fixture_and_wrangler_alignment(self):
        from harness.jev import _validate_questions
        from harness.route_pack import route_question_pack
        wrangler_path = os.path.join(
            os.path.dirname(_WORKER_JS), "wrangler.toml")
        with open(wrangler_path, encoding="utf-8") as f:
            wrangler_text = f.read()
        self.assertIn("https://api.typesafe.ai/v1/systemone", wrangler_text)

        out = self._run_js(
            f"import {{ buildRouteRequest, CANONICAL_JEV_ENDPOINT }} from '{_worker_url()}';\n"
            f"const req = buildRouteRequest('fix typo', {json.dumps(self.PACK)}, 'jev-1.14.0');\n"
            f"process.stdout.write(JSON.stringify({{ req, endpoint: CANONICAL_JEV_ENDPOINT }}));\n"
        )
        self.assertEqual(out["endpoint"], "https://api.typesafe.ai/v1/systemone")
        req = out["req"]
        self.assertEqual(req["model"], "jev-1.14.0")
        self.assertEqual(req["state"], {"goal": "fix typo", "pack_id": "site-demo-ladder"})
        self.assertNotIn("messages", req)
        self.assertEqual(
            set(req["questions"]["rung"]["criteria"].keys()),
            {"r0", "r1", "r2"},
        )
        py_questions = route_question_pack(self.PACK)
        self.assertEqual(req["questions"], py_questions)
        _validate_questions(req["questions"])  # exact TypeSafe schema gate

    def test_valid_system_one_choice_selects_rung_marks_live_and_caches(self):
        goal = "implement a retry queue"
        # Reference System One Choice payload shape
        resp_body = {
            "answers": {
                "rung": {"type": "choice", "choice": "r2", "confidence": 0.92},
            },
            "usage": {"input_tokens": 120, "output_tokens": 12},
        }
        first = self._run_handle_route(
            {"goal": goal, "pack": self.PACK},
            env_cfg={"JEV_KEY": "jev-secret-token", "JEV_MODEL": "jev-1.14.0"},
            fetch_script=(
                f"return new Response(JSON.stringify({json.dumps(resp_body)}), "
                "{ status: 200, headers: { 'content-type': 'application/json' } });"
            ),
        )
        self.assertEqual(first["status"], 200)
        self.assertEqual(len(first["fetches"]), 1)
        sent = first["fetches"][0]
        self.assertEqual(sent["url"], "https://api.typesafe.ai/v1/systemone")
        self.assertEqual(sent["headers"]["authorization"], "Bearer jev-secret-token")
        self.assertEqual(sent["headers"]["content-type"], "application/json")
        self.assertEqual(sent["body"]["state"]["goal"], goal)
        self.assertEqual(sent["body"]["questions"]["rung"]["type"], "choice")
        self.assertFalse(first["out"]["is_fallback"])
        self.assertEqual(first["out"]["route"]["rung_id"], "r2")
        self.assertEqual(first["out"]["route"]["tier"], "T2")

        # Live validated decision IS cached for repeat calls without another fetch.
        route_puts = [p for p in first["puts"] if p["key"].startswith("route:")]
        self.assertEqual(len(route_puts), 1)
        cached_kv = {route_puts[0]["key"]: json.dumps(route_puts[0]["val"])}
        second = self._run_handle_route(
            {"goal": goal, "pack": self.PACK},
            env_cfg={"JEV_KEY": "jev-secret-token"},
            initial_kv=cached_kv,
        )
        self.assertEqual(second["status"], 200)
        self.assertEqual(len(second["fetches"]), 0)
        self.assertFalse(second["out"]["is_fallback"])
        self.assertEqual(second["out"]["route"]["rung_id"], "r2")

    def test_invalid_or_error_responses_fall_back_and_never_cache_as_live(self):
        goal = "fix the race in the token bucket"
        bad_cases = [
            ("missing_key", {}, "throw new Error('no fetch')", "credentials"),
            ("non_2xx", {"JEV_KEY": "k"}, "return new Response('err', { status: 502 });", "HTTP 502"),
            ("malformed_json", {"JEV_KEY": "k"}, "return new Response('{bad', { status: 200 });", "transport"),
            ("missing_answers", {"JEV_KEY": "k"}, "return new Response('{}', { status: 200 });", "missing"),
            ("wrong_answer_type", {"JEV_KEY": "k"},
             'return new Response(JSON.stringify({ answers: { rung: { type: "noul", noul: 0.9 } } }), { status: 200 });',
             "type invalid"),
            ("undeclared_choice", {"JEV_KEY": "k"},
             'return new Response(JSON.stringify({ answers: { rung: { type: "choice", choice: "gpt-99" } } }), { status: 200 });',
             "out-of-ladder"),
            ("openai_choices_ignored", {"JEV_KEY": "k"},
             'return new Response(JSON.stringify({ choices: [{ message: { content: \'{"choice":"r0"}\' } }] }), { status: 200 });',
             "missing"),
        ]
        for name, cfg, script, substr in bad_cases:
            with self.subTest(case=name):
                res = self._run_handle_route(
                    {"goal": goal, "pack": self.PACK},
                    env_cfg=cfg,
                    fetch_script=script,
                )
                self.assertEqual(res["status"], 200)
                self.assertTrue(res["out"]["is_fallback"], res["out"])
                self.assertIn(substr, " ".join(res["out"].get("reasons") or []))
                self.assertIn(res["out"]["route"]["rung_id"], {"r0", "r1", "r2"})
                route_puts = [p for p in res["puts"] if p["key"].startswith("route:")]
                self.assertEqual(route_puts, [], f"{name} must never cache fallback into KV")

    def test_poisoned_fallback_in_kv_is_never_served_as_live(self):
        goal = "fix a typo in the comment"
        key_res = self._run_js(
            f"""
const enc = new TextEncoder().encode({json.dumps(goal)} + "|" + JSON.stringify({json.dumps(self.PACK)}));
const digest = await crypto.subtle.digest("SHA-256", enc);
const hex = [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, "0")).join("");
process.stdout.write(JSON.stringify("route:" + hex));
"""
        )
        poisoned = {
            key_res: json.dumps({
                "status": "ok",
                "route": {"rung_id": "r0", "tier": "T0"},
                "is_fallback": True,
                "reasons": ["stale fallback"],
            }),
        }
        live_resp = {"answers": {"rung": {"type": "choice", "choice": "r0"}}}
        res = self._run_handle_route(
            {"goal": goal, "pack": self.PACK},
            env_cfg={"JEV_KEY": "k"},
            initial_kv=poisoned,
            fetch_script=f"return new Response(JSON.stringify({json.dumps(live_resp)}), {{ status: 200 }});",
        )
        self.assertEqual(len(res["fetches"]), 1)
        self.assertFalse(res["out"]["is_fallback"])


if __name__ == "__main__":
    unittest.main()
