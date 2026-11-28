"""G13: a lane's continuation is its registered prompt, read from the pinned home.

Registry rule (#295 c.7232609553): the driver continues ONLY a lane with a
registered prompt, delivers that text VERBATIM, and parks NAMED when the file is
missing or unreadable - a continuation text is never improvised. These tests
hold the reader to that rule and hold the pinned home to covering the prompt
bytes, so a delivered continuation is attributable to an exact sha256.
"""

import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts import driver_runtime_home
from scripts import standing_prompts as registry
from scripts import windows_freebuff_dispatch as dispatch


def home_with(tmp_path, prompts):
    """A pinned-home layout carrying ``{lane-file-stem: text}``."""
    home = Path(tmp_path) / "runtime"
    root = home / "registry" / "standing-prompts"
    root.mkdir(parents=True)
    for stem, text in prompts.items():
        # Bytes, not text mode: the registry's sha is over the file's bytes, and
        # text mode would rewrite \n as \r\n on Windows and change that sha.
        (root / f"{stem}.md").write_bytes(text.encode("utf-8"))
    return home


class RegistryResolutionTests(unittest.TestCase):
    def test_a_lane_resolves_to_its_registered_text_and_the_exact_bytes_sha(self):
        body = "CHECK-IN STEER - Lane 1 (Harness)\n\nContinue in full.\n"
        with tempfile.TemporaryDirectory() as tmp:
            home = home_with(tmp, {"lane-1": body, "lane-2": "Lane 2 steer\n"})
            got = registry.resolve(home, "Lane 1")
        self.assertEqual(got["text"], body)
        self.assertEqual(got["file"], "lane-1.md")
        self.assertEqual(got["sha256"], hashlib.sha256(body.encode("utf-8")).hexdigest())

    def test_the_lane_name_maps_to_the_registry_file_stem(self):
        self.assertEqual(registry.lane_slug("Lane 1"), "lane-1")
        self.assertEqual(registry.lane_slug("Driver Fixes and Verify"), "driver-fixes-and-verify")
        self.assertEqual(registry.lane_slug("  lane 2 "), "lane-2")
        with self.assertRaises(registry.PromptMissing):
            registry.lane_slug("---")

    def test_one_lanes_prompt_is_never_delivered_for_another(self):
        """The negative the rule needs: reading the wrong file must be impossible."""
        with tempfile.TemporaryDirectory() as tmp:
            home = home_with(tmp, {"lane-1": "STEER ONE\n", "lane-2": "STEER TWO\n"})
            first = registry.resolve(home, "Lane 1")
            second = registry.resolve(home, "Lane 2")
        self.assertEqual(first["text"], "STEER ONE\n")
        self.assertEqual(second["text"], "STEER TWO\n")
        self.assertNotEqual(first["sha256"], second["sha256"])

    def test_a_changed_file_changes_the_sha_so_the_verdict_cannot_claim_the_old_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = home_with(tmp, {"lane-1": "old steer\n"})
            before = registry.resolve(home, "Lane 1")
            (home / "registry" / "standing-prompts" / "lane-1.md").write_bytes(b"new steer\n")
            after = registry.resolve(home, "Lane 1")
        self.assertNotEqual(before["sha256"], after["sha256"])

    def test_refusals_are_named_by_cause(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = home_with(tmp, {"lane-1": "steer\n", "blank": "   \n"})
            (home / "registry" / "standing-prompts" / "bad.md").write_bytes(b"\xff\xfe not utf-8")
            cases = [
                ("Lane 2", "no-prompt-registered"),   # not registered at all
                ("blank", "empty-prompt"),
                ("bad", "unreadable-prompt"),
            ]
            for lane, reason in cases:
                with self.assertRaises(registry.PromptMissing) as caught:
                    registry.resolve(home, lane)
                self.assertEqual(caught.exception.reason, reason, lane)
            bare = Path(tmp) / "unpinned"
            with self.assertRaises(registry.PromptMissing) as caught:
                registry.resolve(bare, "Lane 1")
        self.assertEqual(caught.exception.reason, "no-prompt-registered")
        self.assertIn("registry/standing-prompts", caught.exception.detail)

    def test_registered_lists_the_home_without_reading_the_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = home_with(tmp, {"lane-1": "a\n", "lane-2": "b\n"})
            self.assertEqual(registry.registered(home), ["lane-1", "lane-2"])


class PromptPinningTests(unittest.TestCase):
    """The prompt bytes ride the same pin as the code, so drift refuses."""

    def test_copy_registry_pins_the_bytes_and_a_later_edit_is_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "ledger-prompts"
            source.mkdir()
            (source / "lane-1.md").write_text("registered steer\n", encoding="utf-8")
            home = Path(tmp) / "home"
            (home / "scripts").mkdir(parents=True)
            (home / "scripts" / "windows_freebuff_watch.py").write_text("# code\n", encoding="utf-8")
            driver_runtime_home.copy_registry(source, home)
            driver_runtime_home.write_pin(home, "a" * 40)

            self.assertEqual(driver_runtime_home.verify(home), (True, "matches the pin"))
            (home / "registry" / "standing-prompts" / "lane-1.md").write_bytes(
                b"edited after the pin\n")
            ok, detail = driver_runtime_home.verify(home)
            self.assertFalse(ok)
            self.assertIn("registry/standing-prompts/lane-1.md", detail)

    def test_a_removed_lane_does_not_survive_a_refresh(self):
        """Removal is the deregistration mechanism; a stale copy would undo it."""
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "ledger-prompts"
            source.mkdir()
            (source / "lane-1.md").write_text("a\n", encoding="utf-8")
            (source / "lane-2.md").write_text("b\n", encoding="utf-8")
            home = Path(tmp) / "home"
            (home / "scripts").mkdir(parents=True)
            (home / "scripts" / "windows_freebuff_watch.py").write_text("# code\n", encoding="utf-8")
            driver_runtime_home.copy_registry(source, home)

            (source / "lane-2.md").unlink()
            driver_runtime_home.copy_registry(source, home)
            self.assertEqual(registry.registered(home), ["lane-1"])

    def test_an_empty_registry_directory_is_refused_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "ledger-prompts"
            source.mkdir()
            with self.assertRaisesRegex(RuntimeError, "carries no \\*.md prompts"):
                driver_runtime_home.copy_registry(source, Path(tmp) / "home")


if __name__ == "__main__":
    unittest.main()


class DispatchPromptFileTests(unittest.TestCase):
    """The child reads the prompt as bytes, so the typed text is the registered text."""

    def test_a_prompt_file_is_read_verbatim(self):
        body = "CHECK-IN STEER - Lane 1\n\n- a bullet\n- another\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prompt.txt"
            path.write_bytes(body.encode("utf-8"))
            self.assertEqual(dispatch.read_prompt_file(path), body)

    def test_blank_and_undecodable_prompts_are_refused_not_repaired(self):
        with tempfile.TemporaryDirectory() as tmp:
            blank = Path(tmp) / "blank.txt"
            blank.write_bytes(b"  \n\t\n")
            with self.assertRaisesRegex(ValueError, "empty"):
                dispatch.read_prompt_file(blank)
            bad = Path(tmp) / "bad.txt"
            bad.write_bytes(b"\xff\xfe\x00 not utf-8")
            with self.assertRaises(UnicodeDecodeError):
                dispatch.read_prompt_file(bad)
            with self.assertRaises(OSError):
                dispatch.read_prompt_file(Path(tmp) / "absent.txt")


class InstallPinsTheRegistryTests(unittest.TestCase):
    """The producer, end to end: code at a commit plus the registry, one pin."""

    def test_install_materializes_a_home_whose_prompts_the_claim_path_can_read(self):
        import subprocess

        if shutil.which("git") is None:
            self.skipTest("deps: git is required to materialize a runtime home")
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "dev"
            (source / "scripts").mkdir(parents=True)
            (source / "driver_core").mkdir(parents=True)
            (source / "scripts" / "windows_freebuff_watch.py").write_text("# watch\n", encoding="utf-8")
            (source / "driver_core" / "__init__.py").write_text("# core\n", encoding="utf-8")
            for args in (("init", "-q"), ("add", "-A"),
                         ("-c", "user.email=ci@example.invalid", "-c", "user.name=ci",
                          "commit", "-qm", "base")):
                subprocess.run(["git", "-C", str(source), *args], check=True, capture_output=True, text=True)
            ledger = Path(tmp) / "ledger-prompts"
            ledger.mkdir()
            (ledger / "lane-1.md").write_bytes(b"registered steer\n")

            home = Path(tmp) / "home"
            pin = driver_runtime_home.install(source, home, registry=ledger)
            self.assertEqual(registry.resolve(home, "Lane 1")["text"], "registered steer\n")
            self.assertIn("registry/standing-prompts/lane-1.md", pin["manifest"])

            # Deregistration + replacement both take effect on refresh, without
            # the driver's commit moving.
            (ledger / "lane-1.md").unlink()
            (ledger / "lane-2.md").write_bytes(b"second steer\n")
            refreshed = driver_runtime_home.refresh_registry(home, ledger)
            self.assertEqual(refreshed["sha"], pin["sha"])
            self.assertEqual(registry.registered(home), ["lane-2"])
            with self.assertRaises(registry.PromptMissing):
                registry.resolve(home, "Lane 1")
            self.assertEqual(driver_runtime_home.verify(home), (True, "matches the pin"))
