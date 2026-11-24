"""Run the focused renderer regression for #706 under Node.

The UI's markdown renderer is browser code; this drives it in a bare VM the
same way `test_ui_stop_race` drives the stop race, and skips when Node is not
installed (the same optional-dependency rule the stop-race test uses).
"""
import shutil
import subprocess
import unittest
from pathlib import Path


class UiMarkdownCodeTests(unittest.TestCase):
    def test_code_blocks_keep_their_own_inline_markers(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("optional deps: Node.js is not installed")
        test_file = Path(__file__).with_name("ui_markdown_code.test.cjs")
        result = subprocess.run(
            [node, "--test", str(test_file)], capture_output=True, text=True,
            timeout=30, check=False)
        self.assertEqual(result.returncode, 0,
                         result.stdout + "\n" + result.stderr)


if __name__ == "__main__":
    unittest.main()
