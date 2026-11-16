"""#290: the triage runbook's distinguishing checks, executable.

The failure this row addresses is that an environment break and a code defect look
identical, so the runbook has to hand an operator a command with a verdict -- and
that verdict has to be right in both directions, or the runbook sends people to
fix a machine that was fine. These tests drive every verdict through injected
resolvers and environment mappings, then check the runbook still names each
check and both expected outcomes, and that its drop list has not drifted from
R13's.
"""
import json
import os
import re
import tempfile
import unittest
from unittest import mock

from harness import triage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "docs", "audit-triage.md")


def probe(name, **kwargs):
    return triage.PROBES[name](**kwargs)


class PythonProbeTests(unittest.TestCase):
    def test_a_resolvable_interpreter_with_the_alias_is_ok(self):
        result = probe("python", env={}, resolve=lambda: "/usr/bin/python3",
                       which=lambda name: "/usr/bin/python")
        self.assertEqual(result["verdict"], "ok")

    def test_a_missing_bare_alias_is_environment_broken(self):
        result = probe("python", env={}, resolve=lambda: "/usr/bin/python3",
                       which=lambda name: None)
        self.assertEqual(result["verdict"], "env-broken")
        self.assertIn("no `python` on PATH", result["detail"])

    def test_no_interpreter_at_all_is_environment_broken(self):
        def boom():
            raise RuntimeError("no Python interpreter found")

        result = probe("python", env={}, resolve=boom, which=lambda name: None)
        self.assertEqual(result["verdict"], "env-broken")
        self.assertIn("no interpreter resolved", result["detail"])

    def test_the_harness_python_override_counts_as_an_alias(self):
        result = probe("python", env={"HARNESS_PYTHON": "/opt/py"},
                       resolve=lambda: "/opt/py", which=lambda name: None)
        self.assertEqual(result["verdict"], "ok")

    def test_both_worlds_are_stated(self):
        result = probe("python", env={}, resolve=lambda: "/x", which=lambda n: None)
        self.assertIn("alias", result["expected"]["env-broken"])
        self.assertIn("resolve_gate_argv", result["expected"]["code-broken"])


class RuffProbeTests(unittest.TestCase):
    def test_an_unresolvable_ruff_is_environment_broken(self):
        def boom(strict=False):
            raise RuntimeError("ruff not found: put ruff on PATH")

        result = probe("ruff", env={}, ruff_argv=boom)
        self.assertEqual(result["verdict"], "env-broken")
        self.assertIn("ruff unresolved", result["detail"])

    def test_a_resolved_ruff_is_ok(self):
        result = probe("ruff", env={}, ruff_argv=lambda strict=False: ("/u/ruff",))
        self.assertEqual(result["verdict"], "ok")
        self.assertIn("/u/ruff", result["detail"])

    def test_the_non_strict_path_is_not_trusted(self):
        # A resolver that ignores ``strict`` would report a module fallback as
        # success; the probe must pass strict through.
        seen = {}

        def argv(strict=False):
            seen["strict"] = strict
            return ("/u/ruff",)

        probe("ruff", env={}, ruff_argv=argv)
        self.assertTrue(seen["strict"])


class HermeticProbeTests(unittest.TestCase):
    def test_a_live_key_is_environment_broken(self):
        result = probe("hermetic", env={"OPENROUTER_API_KEY": "x"})
        self.assertEqual(result["verdict"], "env-broken")
        self.assertIn("OPENROUTER_API_KEY", result["detail"])

    def test_a_routing_knob_is_environment_broken(self):
        result = probe("hermetic", env={"HARNESS_USE_FREE": "1"})
        self.assertEqual(result["verdict"], "env-broken")
        self.assertIn("routing", result["detail"].lower())

    def test_an_empty_setting_is_not_a_leak(self):
        result = probe("hermetic", env={"OPENROUTER_API_KEY": ""})
        self.assertEqual(result["verdict"], "ok")

    def test_a_clean_environment_is_ok(self):
        result = probe("hermetic", env={"HARNESS_LEDGER": "/tmp/l.jsonl"})
        self.assertEqual(result["verdict"], "ok")

    def test_the_drop_list_matches_r13s(self):
        with open(os.path.join(ROOT, "audits", "self", "audit.py"), encoding="utf-8") as handle:
            source = handle.read()
        block = re.search(r"_HERMETIC_ENV_DROP = \((.*?)\)", source, re.S)
        self.assertIsNotNone(block, "R13's drop list is not where the runbook says")
        names = set(re.findall(r'"([A-Z0-9_]+)"', block.group(1)))
        self.assertEqual(names, set(triage.HERMETIC_ENV_DROP))


class D12ProbeTests(unittest.TestCase):
    def test_no_pin_is_ok(self):
        self.assertEqual(probe("d12", env={})["verdict"], "ok")

    def test_a_matching_pin_is_ok(self):
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                             encoding="utf-8")
        self.addCleanup(lambda p=handle.name: os.path.exists(p) and os.unlink(p))
        json.dump({"commit": "abc1234def"}, handle)
        handle.close()
        result = probe("d12", env={"HARNESS_D12_BASE": "abc1234def",
                                   "HARNESS_D12_BASELINE": handle.name})
        self.assertEqual(result["verdict"], "ok")

    def test_a_stale_pin_is_environment_broken(self):
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                             encoding="utf-8")
        self.addCleanup(lambda p=handle.name: os.path.exists(p) and os.unlink(p))
        json.dump({"commit": "0000000aaa"}, handle)
        handle.close()
        result = probe("d12", env={"HARNESS_D12_BASE": "ffffff9bbb",
                                   "HARNESS_D12_BASELINE": handle.name})
        self.assertEqual(result["verdict"], "env-broken")
        self.assertIn("baseline names", result["detail"])

    def test_an_unreadable_baseline_is_environment_broken(self):
        result = probe("d12", env={"HARNESS_D12_BASE": "abc",
                                   "HARNESS_D12_BASELINE": "/nonexistent/x.json"})
        self.assertEqual(result["verdict"], "env-broken")


class RunnerTests(unittest.TestCase):
    def test_all_four_checks_run(self):
        results = triage.run_checks(env={"HARNESS_USE_FREE": ""})
        self.assertEqual([item["check"] for item in results],
                         ["python", "ruff", "hermetic", "d12"])

    def test_an_unknown_check_is_refused(self):
        with self.assertRaises(KeyError):
            triage.run_checks(["nope"])

    def test_render_names_the_verdict_and_both_worlds(self):
        text = triage.render(triage.run_checks(["d12"], env={}))
        self.assertIn("[triage] d12", text)
        self.assertIn("if env-broken:", text)
        self.assertIn("if code:", text)

    def test_the_command_line_fails_when_the_environment_is_broken(self):
        def stub(name):
            return (lambda **_: triage._result(name, "env-broken", "x", "a", "b"))
        with mock.patch.dict(triage.PROBES, {"python": stub("python")}):
            self.assertEqual(triage.main(["--check", "python"]), 1)

    def test_the_command_line_passes_when_clean(self):
        def stub(name):
            return (lambda **_: triage._result(name, "ok", "x", "a", "b"))
        with mock.patch.dict(triage.PROBES, {"python": stub("python")}):
            self.assertEqual(triage.main(["--check", "python"]), 0)

    def test_json_output_is_machine_readable(self):
        def stub(name):
            return (lambda **_: triage._result(name, "ok", "x", "a", "b"))
        with mock.patch.dict(triage.PROBES, {"ruff": stub("ruff")}):
            import contextlib
            import io
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                self.assertEqual(triage.main(["--check", "ruff", "--json"]), 0)
            parsed = json.loads(buffer.getvalue())
            self.assertEqual(parsed[0]["check"], "ruff")
            self.assertEqual(parsed[0]["verdict"], "ok")


class RunbookTests(unittest.TestCase):
    def setUp(self):
        with open(DOC, encoding="utf-8") as handle:
            self.text = handle.read()

    def test_every_required_entry_exists(self):
        for heading in ("## S5", "## D12", "## Bare-`python` gate failures",
                        "## R13"):
            self.assertIn(heading, self.text)

    def test_every_entry_names_its_check(self):
        for name in ("python", "ruff", "hermetic", "d12"):
            self.assertIn(f"--check {name}", self.text)

    def test_both_worlds_are_named(self):
        self.assertGreaterEqual(self.text.count("env-broken"), 4)
        self.assertGreaterEqual(self.text.count("code-broken"), 4)

    def test_the_helper_is_linked_from_the_contributor_docs(self):
        with open(os.path.join(ROOT, "CONTRIBUTING.md"), encoding="utf-8") as handle:
            contributing = handle.read()
        self.assertIn("docs/audit-triage.md", contributing)

    def test_the_runbook_points_at_the_wrapper_it_recommends(self):
        self.assertIn("scripts/hermetic-env.sh", self.text)

    def test_the_runbook_names_the_probe_module(self):
        self.assertIn("python -m harness.triage", self.text)


if __name__ == "__main__":
    unittest.main()
