"""#289: the uv lock must describe the project it claims to.

The migration replaces a requirements file with a lockfile, so the lockfile *is*
the dependency contract. A lock that pins a different project version, or lacks
an extra the project declares, installs a world nobody described -- and no test
notices until `uv sync --frozen` misbehaves. These tests hold the agreement
between `pyproject.toml` and `uv.lock` hermetically, plus the drift detector's
own behaviour on synthetic disagreements, and the rollback record the issue asks
for.
"""
import os
import tempfile
import unittest

from harness import deps_lock as dl

ROOT = dl.default_root()
DOC = os.path.join(ROOT, "docs", "dependencies.md")


def write(root, pyproject, lock):
    py_path = os.path.join(root, "pyproject.toml")
    with open(py_path, "w", encoding="utf-8") as handle:
        handle.write(pyproject)
    with open(os.path.join(root, "uv.lock"), "w", encoding="utf-8") as handle:
        handle.write(lock)


PYPROJECT = """
[project]
name = "demo"
version = "1.2.3"
requires-python = ">=3.9"

[project.optional-dependencies]
dev = ["ruff>=0.6", "build>=1.2"]
render = ["playwright>=1.44"]
"""


def lock_text(version="1.2.3", requires=">=3.9", extras=None, packages=None):
    extras = extras if extras is not None else {
        "dev": '[\n    { name = "build" },\n    { name = "ruff" },\n]',
        "render": '[\n    { name = "playwright" },\n]',
    }
    # Extras as an inline table list under one subtable: the shape uv writes.
    block = "\n".join("{} = {}".format(name, body) for name, body in extras.items())
    return ("version = 1\nrevision = 3\nrequires-python = \"{}\"\n\n"
            "[[package]]\nname = \"demo\"\nversion = \"{}\"\nsource = {{ editable = \".\" }}\n\n"
            "[package.optional-dependencies]\n{}\n".format(requires, version, block))


class ShippedAgreementTests(unittest.TestCase):
    def test_pyproject_and_lock_agree(self):
        project, lock = dl.load(ROOT)
        result = dl.check(project, lock)
        self.assertEqual(result["drift"], [], dl.render(result))

    def test_the_lock_pins_the_declared_project_version(self):
        project, lock = dl.load(ROOT)
        root = dl.root_package(lock, project["name"])
        self.assertIsNotNone(root)
        self.assertEqual(root["version"], project["version"])

    def test_every_declared_extra_is_locked(self):
        project, lock = dl.load(ROOT)
        root = dl.root_package(lock, project["name"])
        locked = root.get("optional-dependencies") or {}
        for extra in project.get("optional-dependencies") or {}:
            self.assertIn(extra, locked)

    def test_the_lock_has_no_identity_less_packages(self):
        _, lock = dl.load(ROOT)
        bad = [p for p in lock["package"]
               if not p.get("name") or not p.get("version")]
        self.assertEqual(bad, [])

    def test_the_lock_is_a_supported_schema(self):
        _, lock = dl.load(ROOT)
        self.assertIn(lock["version"], dl.SUPPORTED_LOCK_VERSIONS)

    def test_the_command_line_reports_in_sync(self):
        self.assertEqual(dl.main(["--check", "--quiet"]), 0)


class DriftDetectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp(prefix="deps-")

    def _result(self, pyproject=PYPROJECT, lock=None):
        write(self.temp, pyproject, lock if lock is not None else lock_text())
        project, document = dl.load(self.temp)
        return dl.check(project, document)

    def test_a_matching_pair_has_no_drift(self):
        self.assertEqual(self._result()["drift"], [])

    def test_a_stale_project_version_is_drift(self):
        kinds = [d["kind"] for d in self._result(lock=lock_text(version="1.0.0"))["drift"]]
        self.assertEqual(kinds, ["project_version_drift"])

    def test_a_requires_python_disagreement_is_drift(self):
        kinds = [d["kind"] for d in self._result(lock=lock_text(requires=">=3.10"))["drift"]]
        self.assertEqual(kinds, ["requires_python_drift"])

    def test_an_extra_missing_from_the_lock_is_drift(self):
        lock = lock_text(extras={"dev": '[\n    { name = "build" },\n    { name = "ruff" },\n]'})
        kinds = [d["kind"] for d in self._result(lock=lock)["drift"]]
        self.assertEqual(kinds, ["extra_missing_from_lock"])
        self.assertIn("render", self._result(lock=lock)["drift"][0]["detail"])

    def test_an_extra_member_missing_from_the_lock_is_drift(self):
        lock = lock_text(extras={
            "dev": '[\n    { name = "build" },\n]',
            "render": '[\n    { name = "playwright" },\n]'})
        kinds = [d["kind"] for d in self._result(lock=lock)["drift"]]
        self.assertEqual(kinds, ["extra_member_missing"])
        self.assertIn("ruff", self._result(lock=lock)["drift"][0]["detail"])

    def test_an_undeclared_extra_in_the_lock_is_drift(self):
        lock = lock_text(extras={
            "dev": '[\n    { name = "build" },\n    { name = "ruff" },\n]',
            "render": '[\n    { name = "playwright" },\n]',
            "old": '[\n    { name = "numpy" },\n]'})
        kinds = [d["kind"] for d in self._result(lock=lock)["drift"]]
        self.assertEqual(kinds, ["extra_not_declared"])

    def test_a_project_absent_from_the_lock_is_drift(self):
        lock = ('version = 1\nrevision = 3\nrequires-python = ">=3.9"\n\n'
                '[[package]]\nname = "other"\nversion = "1.0"\n')
        kinds = [d["kind"] for d in self._result(lock=lock)["drift"]]
        self.assertEqual(kinds, ["project_not_locked"])

    def test_an_unsupported_lock_schema_is_drift(self):
        kinds = [d["kind"] for d in
                 self._result(lock=lock_text().replace("version = 1", "version = 9", 1))["drift"]]
        self.assertIn("unsupported_lock_version", kinds)

    def test_a_missing_lockfile_is_an_error_not_a_pass(self):
        with open(os.path.join(self.temp, "pyproject.toml"), "w", encoding="utf-8") as handle:
            handle.write(PYPROJECT)
        with self.assertRaises(dl.LockError):
            dl.load(self.temp)

    def test_a_pyproject_without_a_project_table_is_an_error(self):
        write(self.temp, "[build-system]\nrequires = []\n", lock_text())
        with self.assertRaises(dl.LockError):
            dl.load(self.temp)

    def test_the_command_line_fails_on_drift(self):
        write(self.temp, PYPROJECT, lock_text(version="0.0.1"))
        self.assertEqual(dl.main(["--root", self.temp]), 1)


class TrackedArtifactTests(unittest.TestCase):
    """A lock nobody tracks is not a contract -- it is one developer's leftovers."""

    def test_the_lock_is_not_gitignored(self):
        with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as handle:
            text = handle.read()
        patterns = [line.strip() for line in text.splitlines()
                    if line.strip() and not line.strip().startswith("#")]
        self.assertNotIn("uv.lock", patterns)
        self.assertNotIn("/uv.lock", patterns)

    def test_the_ignore_rule_still_covers_local_scratch(self):
        with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("dogfood_matrix_results.json", text)


class RollbackRecordTests(unittest.TestCase):
    """The issue asks for a rollback note; the note is only useful if it is checkable."""

    def test_the_dependency_doc_exists(self):
        self.assertTrue(os.path.exists(DOC))

    def test_the_doc_records_the_exact_revert(self):
        with open(DOC, encoding="utf-8") as handle:
            text = handle.read()
        for needle in ("git revert", "uv lock", "pip install -e", "uv sync"):
            self.assertIn(needle, text)

    def test_the_doc_states_whether_ci_is_on_the_uv_path(self):
        with open(DOC, encoding="utf-8") as handle:
            text = handle.read().lower()
        self.assertIn("ci", text)
        self.assertIn("not on the uv path yet", text)

    def test_the_doc_records_the_ignore_rule_that_hid_the_drift(self):
        with open(DOC, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn(".gitignore", text)
        self.assertIn("tracked", text)


if __name__ == "__main__":
    unittest.main()
