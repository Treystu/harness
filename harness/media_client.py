"""harness.media_client — adapter to the sovereign-media service.

Thin, zero-dependency client (stdlib only) so harness (and anything embedding
harness) can generate images/videos through the cost-bounded media service
without ever holding provider credentials. Budgets, sign-in state, and
hash-chained spend ledger all live service-side; harness only ever receives
job envelopes (status, cost, artifact paths).

Honest-failure contract (mirrors HARNESS_DEFER): if the service is down,
unsigned-in, or refuses on budget, the caller gets a refusal envelope with
the reason — never a silent empty result.

Usage (Python):
    from harness.media_client import MediaAdapter
    media = MediaAdapter()
    result = media.image("a cabin in snowy woods", project="scmessenger")
    result["status"]        # "succeeded" / "failed" / "refused" / "service_unavailable"
    result["artifacts"]     # local artifact paths (same machine) or URLs
    result["cost"]          # actual USD spent, when settled

Wrong-service guard (#566): the media service defaults to loopback 8765 and
`harness serve` used to as well, so a loopback endpoint may be the harness UI
rather than the media service. Before the first media operation, a loopback
endpoint is probed once with a credential-free read-only GET; a positively
identified harness UI raises :class:`MediaEndpointMismatch` and no token is
sent. Remote endpoints are operator-declared and skip the probe.

Usage (CLI, wired into harness.cli as `harness media ...`):
    harness media image "a cabin in snowy woods" --project scmessenger
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from .loopback import media_base_url
from .paths import get_config_dir

# No provider/service brand strings are hardcoded here: the endpoint the
# adapter talks to is always resolved from config or environment, in this
# order: explicit constructor args > config file > env vars > loopback
# default. The default is a *local* fallback (not a brand), matching the
# `media serve` quickstart in docs/media.md.
#: The media service's loopback default: base + 0 of the harness-owned port
#: family (#655, one rule in harness/loopback.py). Media stays on 8765 while
#: the harness UI is base + 2 (8767, #566), so the two can run together.
DEFAULT_BASE = os.environ.get("MEDIA_BASE_URL", media_base_url())
CONFIG_PATH = os.environ.get(
    "MEDIA_CONFIG_PATH",
    os.path.join(get_config_dir(), "media.json"),
)


def _load_endpoint():
    env_token = os.environ.get("MEDIA_TOKEN")
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
            return cfg.get("base_url", DEFAULT_BASE), cfg.get("token") or env_token
        except (OSError, ValueError):
            pass
    return DEFAULT_BASE, env_token


class MediaUnavailable(Exception):
    """The media service could not be reached or refused the request."""


class MediaEndpointMismatch(MediaUnavailable):
    """The endpoint answered as another local service, not the media service."""


#: Identity markers of the harness web UI. They are protocol surface, not a
#: provider brand: ``UiRequestHandler`` sets the ``Server`` header and, since
#: #587, the ``X-Harness-*`` headers on every response.
HARNESS_UI_SERVER_PREFIX = "harness-ui/"
HARNESS_UI_BODY_MARKERS = ("harness-ui/", "harness ui")

#: Keys that mark a JSON answer as belonging to the media service.
_MEDIA_PROBE_KEYS = frozenset({"balance", "currency", "jobs", "spent",
                               "ceiling"})

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_PROBE_PATH = "/v1/balance"


def _host_of(base_url):
    try:
        return (urllib.parse.urlsplit(base_url).hostname or "").lower()
    except ValueError:
        return ""


def is_loopback(base_url):
    """True when ``base_url`` points at this machine's loopback interface."""
    return _host_of(base_url) in _LOOPBACK_HOSTS


def _header_value(headers, name):
    if headers is None:
        return None
    try:
        return headers.get(name)
    except AttributeError:
        return None


def identify_service(headers, body):
    """Classify a probe answer: ``"harness-ui"``, ``"media"`` or ``"unknown"``.

    ``headers`` is the response header mapping (``None`` for a bare test
double), ``body`` its raw bytes. A generic 401 with no body is ``unknown``:
    it cannot identify the UI, and it is not a recognizable media challenge.
    """
    server = _header_value(headers, "Server") or ""
    if (server.lower().startswith(HARNESS_UI_SERVER_PREFIX)
            or _header_value(headers, "X-Harness-Version")
            or _header_value(headers, "X-Harness-Commit")):
        return "harness-ui"
    if isinstance(body, (bytes, bytearray)):
        text = bytes(body).decode("utf-8", "replace")
    else:
        text = str(body or "")
    lowered = text.lower()
    if any(marker in lowered for marker in HARNESS_UI_BODY_MARKERS):
        return "harness-ui"
    try:
        payload = json.loads(text)
    except ValueError:
        return "unknown"
    if isinstance(payload, list):
        return "media" if payload and isinstance(payload[0], dict) else "unknown"
    if not isinstance(payload, dict):
        return "unknown"
    if _MEDIA_PROBE_KEYS & set(payload):
        return "media"
    if "error" in payload or "detail" in payload:
        # The service's own note, e.g. its credential challenge. A bare 401
        # with no body is not this case and stays unidentified.
        return "media"
    return "unknown"


class MediaAdapter:
    def __init__(self, base_url=None, token=None, timeout=60, opener=None):
        base, env_token = _load_endpoint()
        self.base = (base_url or base).rstrip("/")
        self.token = token or env_token
        self.timeout = timeout
        # Injectable transport seam for hermetic tests: defaults to the real
        # urllib opener, but tests pass a fake so nothing touches the network.
        self._opener = opener or urllib.request.urlopen
        # Remote endpoints are operator-declared; only a loopback endpoint can
        # be the harness UI by accident, so only it needs the probe (#566).
        self._identified = not is_loopback(self.base)

    # ---- transport ----

    def _ensure_identified(self):
        """Prove a loopback endpoint is the media service before spending it.

        One credential-free read-only GET: no media operation is sent and no
        token leaves the process until the answer identifies the service.
        """
        if self._identified:
            return
        request = urllib.request.Request(self.base + _PROBE_PATH, method="GET")
        try:
            with self._opener(request, timeout=min(self.timeout, 5.0)) as resp:
                headers = getattr(resp, "headers", None)
                body = resp.read()
        except urllib.error.HTTPError as exc:
            try:
                headers = exc.headers
                body = exc.read()
            finally:
                exc.close()
        except (urllib.error.URLError, OSError) as exc:
            raise MediaUnavailable(
                "media service unreachable at {} ({}). Start it with: media "
                "serve".format(self.base, exc)
            ) from exc
        kind = identify_service(headers, body)
        if kind == "harness-ui":
            raise MediaEndpointMismatch(
                "the endpoint at {} answered as the Harness web UI, not the "
                "media service; no media operation or token was sent. "
                "`harness serve` has defaulted to 127.0.0.1:8767 since #566, "
                "so an older or explicitly configured Harness UI is on this "
                "port. Remedy: point MEDIA_BASE_URL (or "
                "~/.config/harness/media.json) at the media service, or stop "
                "the Harness UI on this port.".format(self.base))
        if kind != "media":
            raise MediaUnavailable(
                "the endpoint at {} answered but did not identify itself as "
                "the media service: no media-shaped read-only answer and no "
                "recognizable auth challenge. This is not a credential "
                "failure -- no token was sent. The media service should "
                "expose a stable, credential-free identity marker."
                .format(self.base))
        self._identified = True

    def _request(self, method, path, body=None):
        self._ensure_identified()
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["X-Media-Token"] = self.token
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers=headers)
        try:
            with self._opener(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                try:
                    err = json.loads(e.read().decode("utf-8"))
                except Exception:
                    err = {"error": "HTTP {}".format(e.code)}
            finally:
                e.close()
            if err.get("error") == "budget_refused":
                return {"status": "refused", "error": err.get("message"),
                        "math": err.get("math")}
            raise MediaUnavailable(str(err.get("error") or err)) from e
        except (urllib.error.URLError, OSError) as e:
            raise MediaUnavailable(
                "media service unreachable at {} ({}). Start it with: media serve".format(self.base, e)
            ) from e

    @staticmethod
    def _quote_job_id(job_id):
        """Encode a job ID as one non-empty URL path segment.

        ``urllib.parse.quote(..., safe="")`` still preserves the unreserved
        dot character, so standalone ``.`` and ``..`` must be rejected before
        a proxy or upstream server can normalize them as path segments.
        """
        segment = str(job_id)
        if not segment or segment in {".", ".."}:
            raise ValueError("media job_id must be a non-empty path segment")
        return urllib.parse.quote(segment, safe="")

    # ---- core API ----

    def image(self, prompt, project="default", wait=True, timeout=600.0, **params):
        return self._generate("image", prompt, project, wait, timeout, params)

    def video(self, prompt, project="default", wait=True, timeout=1200.0, **params):
        return self._generate("video", prompt, project, wait, timeout, params)

    def _generate(self, kind, prompt, project, wait, timeout, params):
        job = self._request("POST", "/v1/jobs", {
            "kind": kind, "prompt": prompt, "project": project, "params": params,
        })
        if job.get("status") == "refused":
            return job  # budget refusal envelope with math
        if not wait:
            return self._envelope(job)
        return self.wait(job["id"], timeout=timeout)

    def wait(self, job_id, timeout=600.0, interval=2.0):
        import time
        quoted_job_id = self._quote_job_id(job_id)
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = self._request("GET", "/v1/jobs/{}".format(
                quoted_job_id))
            if job.get("status") in ("succeeded", "failed", "refused"):
                return self._envelope(job)
            time.sleep(interval)
        return {"status": "timeout", "job_id": job_id}

    def job(self, job_id):
        return self._envelope(self._request(
            "GET", "/v1/jobs/{}".format(self._quote_job_id(job_id))))

    def jobs(self, project=None, limit=20):
        q = "/v1/jobs?limit={}".format(int(limit))
        if project:
            q += "&project={}".format(urllib.parse.quote(project))
        return [self._envelope(j) for j in self._request("GET", q).get("jobs", [])]

    def balance(self, project=None):
        path = "/v1/balance" + ("?project={}".format(urllib.parse.quote(project)) if project else "")
        return self._request("GET", path)

    @staticmethod
    def _envelope(job):
        return {
            "job_id": job.get("id"),
            "status": job.get("status"),
            "kind": job.get("kind"),
            "provider": job.get("provider"),
            "model": job.get("model"),
            "cost_estimate": job.get("cost_estimate"),
            "cost": job.get("cost_actual"),
            "artifacts": job.get("artifact_paths") or [],
            "error": job.get("error"),
            "project": job.get("project"),
        }


# ---- CLI handler (wired as `harness media ...`) ----

def run_cli(args, settings=None):
    """harness media {image|video|job|jobs|balance} — returns exit code."""
    import argparse
    import sys

    from .cli_parser import add_output_flags
    from .cli_report import _emit, apply_output_flags

    ap = argparse.ArgumentParser(prog="harness media")
    sub = ap.add_subparsers(dest="media_cmd", required=True)

    # --provider/--model are free strings: the provider catalog (openai,
    # google, higgsfield, fal, replicate, luma, ...) lives service-side in
    # sovereign-media, not hardcoded here — harness never brand-ladders
    # media providers in code.
    p = sub.add_parser("image")
    p.add_argument("prompt")
    p.add_argument("--project", default="default")
    p.add_argument("--provider", default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--size", default=None)
    p.add_argument("--quality", default=None, choices=["low", "medium", "high"])
    p.add_argument("--no-wait", action="store_true")
    p.add_argument("--timeout", type=float, default=600)
    add_output_flags(p)

    p = sub.add_parser("video")
    p.add_argument("prompt")
    p.add_argument("--project", default="default")
    p.add_argument("--provider", default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--seconds", type=int, default=None)
    p.add_argument("--no-wait", action="store_true")
    p.add_argument("--timeout", type=float, default=1200)
    add_output_flags(p)

    p = sub.add_parser("job")
    p.add_argument("job_id")
    add_output_flags(p)

    p = sub.add_parser("jobs")
    p.add_argument("--project", default=None)
    p.add_argument("--limit", type=int, default=20)
    add_output_flags(p)

    p = sub.add_parser("balance")
    p.add_argument("--project", default=None)
    add_output_flags(p)

    opts = ap.parse_args(args)
    apply_output_flags(opts)
    if opts.media_cmd == "job":
        try:
            MediaAdapter._quote_job_id(opts.job_id)
        except ValueError as e:
            ap.error(str(e))

    adapter = MediaAdapter()

    def show(env):
        print("job {}  [{}]  {}/{}  project={}".format(
            env.get("job_id"), env.get("status"), env.get("provider"),
            env.get("model"), env.get("project")))
        est = env.get("cost_estimate") or {}
        if est:
            print("  estimate: ${:.4f} - ${:.4f}".format(est.get("low", 0), est.get("high", 0)))
        if env.get("cost") is not None:
            print("  cost:     ${:.4f}".format(env["cost"]))
        for a in env.get("artifacts") or []:
            print("  artifact: {}".format(a))
        if env.get("error"):
            print("  error:    {}".format(env["error"]))
        if env.get("math"):
            print("  math:     {}".format(json.dumps(env["math"], sort_keys=True)))

    def exit_code(env):
        status = env.get("status")
        if (status == "succeeded"
                or (opts.no_wait and status in ("queued", "running"))):
            return 0
        return 1

    def render(payload, fallback):
        if opts.out:
            _emit(payload, opts.out, force_json=True)
        else:
            fallback()

    try:
        if opts.media_cmd == "image":
            params = {k: v for k, v in (("size", opts.size), ("quality", opts.quality)) if v}
            env = adapter.image(opts.prompt, project=opts.project, wait=not opts.no_wait,
                                timeout=opts.timeout, provider=opts.provider,
                                model=opts.model, **params)
            render(env, lambda: show(env))
            return exit_code(env)
        if opts.media_cmd == "video":
            params = {"seconds": opts.seconds} if opts.seconds else {}
            env = adapter.video(opts.prompt, project=opts.project, wait=not opts.no_wait,
                                timeout=opts.timeout, provider=opts.provider,
                                model=opts.model, **params)
            render(env, lambda: show(env))
            return exit_code(env)
        if opts.media_cmd == "job":
            env = adapter.job(opts.job_id)
            render(env, lambda: show(env))
            return 0
        if opts.media_cmd == "jobs":
            envs = adapter.jobs(project=opts.project, limit=opts.limit)
            render({"jobs": envs}, lambda: [show(e) for e in envs])
            return 0
        if opts.media_cmd == "balance":
            bal = adapter.balance(opts.project)
            render(bal, lambda: print(json.dumps(bal, indent=2)))
            return 0
    except MediaUnavailable as e:
        # defer-style honest failure: state the reason, spend nothing
        if opts.out:
            _emit({"status": "deferred", "error": str(e)}, opts.out, force_json=True)
        print("[defer] media: {}".format(e), file=sys.stderr)
        return 4
    return 2
