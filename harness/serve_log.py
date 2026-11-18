"""Process-owned request log for ``harness serve`` (#574).

The UI server used to write its request lines to whatever stderr its launcher
inherited, so on a machine where the launcher redirected stderr to a file, that
file looked like the serve log while nothing in the product opened it -- a
restart left the file describing a dead process, and a healthy keepalive probe
left no request record anywhere.

This module owns the file side of that log:

- the product opens the file itself, so the path an operator reads is the path
  the running process writes;
- every process writes a startup marker naming its pid, port and path before
  any request line, so an existing file is never mistaken for the current
  process's output (a stale artifact stays visibly stale);
- the caller passes in an already-redacted line; this module holds no
  credential and adds no second formatting convention -- it prefixes the UTC
  time so a request record can be correlated with a probe.

``make_server`` stays file-free unless a path is given, so in-process tests
never touch the operator's home directory; the ``serve`` and ``desktop``
commands pass the default path.
"""
from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from pathlib import Path

#: Directory the serve log lives in, under the operator's harness home.
LOG_DIRNAME = "logs"
LOG_FILENAME = "serve.log"


def default_log_path() -> Path:
    """Return the default serve-log path (``~/.harness/logs/serve.log``)."""
    home = os.environ.get("HARNESS_HOME")
    base = Path(home).expanduser() if home else Path("~/.harness").expanduser()
    return base / LOG_DIRNAME / LOG_FILENAME


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ServeLog:
    """Append-only request log owned by one server process.

    Thread-safe: the UI server handles each request on its own thread, so the
    handle is guarded and every write is flushed -- a record that is still in a
    buffer when the process dies is exactly the failure this file exists to
    prevent.
    """

    def __init__(self, path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._fh = open(self.path, "a", encoding="utf-8", newline="\n")

    def startup(self, *, pid, port):
        """Write the marker that identifies this process as the file's writer.

        Unstamped on the left: the marker already carries its own UTC time and
        must be greppable from column zero, so a reader can tell which process
        wrote the lines that follow it.
        """
        self.write(
            "=== harness serve start {} pid={} port={} log={} ===".format(
                _utc_stamp(), pid, port, self.path),
            stamp=False)
        return self.path

    def write(self, line, *, stamp=True):
        """Append one already-redacted line, stamped in UTC unless told not to."""
        text = str(line).rstrip("\n")
        rendered = f"{_utc_stamp()} {text}\n" if stamp else f"{text}\n"
        with self._lock:
            self._fh.write(rendered)
            self._fh.flush()
        return text

    def close(self):
        with self._lock:
            if not self._fh.closed:
                self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def open_serve_log(path=None, *, pid=None, port=None):
    """Open (creating parents) the serve log and write this process's marker."""
    log = ServeLog(path or default_log_path())
    log.startup(pid=os.getpid() if pid is None else pid, port=port)
    return log
