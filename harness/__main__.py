"""``python -m harness`` -> the CLI, the same entry point as ``harness``.

The documented invocation was ``python -m harness.cli``; running the package
itself is the obvious one, so it must reach the CLI's own usage text rather
than a Python-internals message about a missing ``__main__`` (#529).
"""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
