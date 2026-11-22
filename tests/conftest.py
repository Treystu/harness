"""#656: a session-level home guard for the whole test suite.

Most harness tests isolate themselves with ``tempfile.TemporaryDirectory``, but
a test that forgets cannot be allowed to write into the live operator home. A
single pytest session therefore points every harness-owned state anchor at one
ephemeral directory before any test module is imported:

- ``HARNESS_HOME``       - request logs (``~/.harness``)
- ``HARNESS_CONFIG_DIR`` - config, ledger and media state (``~/.config/harness``)
- ``HARNESS_LEDGER``     - the JSONL ledger file

Anything a test forgets to isolate lands in that ephemeral tree and is removed
at process exit, so a suite run can no longer contaminate an operator database.
A test that wants its own directory still wins: it sets the variable inside its
own body, which overrides this guard for its duration.

``scripts/cleanup_test_records.py`` removes rows an earlier, unguarded run left
behind; its dry run is the operator-facing count.
"""
import atexit
import os
import shutil
import tempfile

_GUARD_VARS = ("HARNESS_HOME", "HARNESS_CONFIG_DIR", "HARNESS_LEDGER")
_saved = {}
_guard_root = None


def _install_guard():
    global _guard_root
    if _guard_root is not None:
        return _guard_root
    _guard_root = tempfile.mkdtemp(prefix="harness-test-home-")
    for name in _GUARD_VARS:
        _saved[name] = os.environ.get(name)
    os.environ["HARNESS_HOME"] = _guard_root
    os.environ["HARNESS_CONFIG_DIR"] = os.path.join(_guard_root, "config")
    os.environ["HARNESS_LEDGER"] = os.path.join(_guard_root, "ledger.jsonl")
    atexit.register(_remove_guard)
    return _guard_root


def _remove_guard():
    for name, value in _saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    if _guard_root:
        shutil.rmtree(_guard_root, ignore_errors=True)


def pytest_configure(config):  # noqa: ARG001 - pytest hook signature
    _install_guard()


def pytest_sessionstart(session):  # noqa: ARG001 - pytest hook signature
    # Import time can run before pytest_configure in some plugin orders; this
    # is idempotent, so the guard is installed either way.
    _install_guard()


def guard_root():
    """The ephemeral home this session writes into (used by the guard test)."""
    return _install_guard()
