"""One owner for the harness-owned loopback ports (#655).

Rule, stated once:

    base  = HARNESS_BASE_PORT, else 8765
    media = base + 0   -> 8765
    serve = base + 2   -> 8767

The desktop shell runs the *serve* surface (``harness/ui.py`` calls
``make_server``), so it binds the serve port; the old 8766 desktop default is
retired (#566/#655). Media keeps a documented offset of its own rather than a
second independent default, so one operator setting moves the harness-owned
family together and the two services still cannot collide.

An unreadable or out-of-range ``HARNESS_BASE_PORT`` falls back to the documented
default rather than to a half-parsed port: a typo must not move a service onto
a port nobody wrote down.
"""
import os

BASE_PORT_ENV = "HARNESS_BASE_PORT"
DEFAULT_BASE_PORT = 8765
MEDIA_OFFSET = 0
SERVE_OFFSET = 2


def base_port(environ=None):
    """The one base port for harness-owned loopback services."""
    environ = os.environ if environ is None else environ
    raw = str(environ.get(BASE_PORT_ENV, "") or "").strip()
    if not raw:
        return DEFAULT_BASE_PORT
    try:
        port = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_BASE_PORT
    if not (1 <= port <= 65535 - SERVE_OFFSET):
        return DEFAULT_BASE_PORT
    return port


def media_port(environ=None):
    """The media service's loopback port (base + 0)."""
    return base_port(environ) + MEDIA_OFFSET


def serve_port(environ=None):
    """The serve/desktop loopback port (base + 2)."""
    return base_port(environ) + SERVE_OFFSET


def serve_base_url(environ=None):
    return f"http://127.0.0.1:{serve_port(environ)}"


def media_base_url(environ=None):
    return f"http://127.0.0.1:{media_port(environ)}"
