"""MEDIA-1: hermetic coverage for harness.media_client.

No network or provider keys involved: `MediaAdapter` takes an injectable
`opener` seam, and every test here supplies a fake transport. Covers the
success path, an honest `MediaUnavailable` failure (service unreachable),
a budget-refusal envelope, and the `harness media ...` CLI face (including
its exit codes and the defer-style stderr message on failure).
"""
import io
import json
import os
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout, redirect_stderr
from unittest import mock

from harness.media_client import (DEFAULT_BASE, MediaAdapter,
                                  MediaEndpointMismatch, MediaUnavailable,
                                  identify_service, is_loopback, run_cli)


class _FakeResponse:
    """Minimal stand-in for the object urllib.request.urlopen's context
    manager yields: a `.read()` returning bytes, usable as a `with` target.
    """

    def __init__(self, payload, headers=None):
        self._body = json.dumps(payload).encode("utf-8")
        self.headers = headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_opener(responses):
    """Build an opener(req, timeout=...) that pops queued responses in order.

    Each queued item is either a dict (returned as a 200 JSON body) or an
    exception instance/class to raise (e.g. urllib.error.HTTPError or
    urllib.error.URLError), so tests can script multi-step interactions
    (POST job -> GET job while running -> GET job succeeded) deterministically.
    """
    calls = []
    headers = []

    def opener(req, timeout=None):
        calls.append((req.get_method(), req.full_url))
        headers.append(dict(req.headers))
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, type) and issubclass(item, Exception):
            raise item()
        if isinstance(item, _FakeResponse):
            return item
        return _FakeResponse(item)

    opener.calls = calls
    opener.headers = headers
    return opener


def _http_error(code, payload):
    body = json.dumps(payload).encode("utf-8")
    return urllib.error.HTTPError(
        url="http://example.invalid", code=code, msg="err",
        hdrs=None, fp=io.BytesIO(body),
    )


class MediaAdapterSuccessTests(unittest.TestCase):
    def test_image_success_wait(self):
        job = {
            "id": "job-1", "status": "queued", "kind": "image",
        }
        done = {
            "id": "job-1", "status": "succeeded", "kind": "image",
            "provider": "acme", "model": "gen-1",
            "cost_estimate": {"low": 0.01, "high": 0.02},
            "cost_actual": 0.015, "artifact_paths": ["/tmp/out.png"],
            "project": "demo",
        }
        opener = _fake_opener([job, done])
        adapter = MediaAdapter(base_url="http://media.local", opener=opener)
        env = adapter.image("a cabin in snowy woods", project="demo")

        self.assertEqual(env["status"], "succeeded")
        self.assertEqual(env["job_id"], "job-1")
        self.assertEqual(env["cost"], 0.015)
        self.assertEqual(env["artifacts"], ["/tmp/out.png"])
        # POST to create, then GET to poll once.
        self.assertEqual(opener.calls[0][0], "POST")
        self.assertEqual(opener.calls[1][0], "GET")

    def test_no_wait_returns_job_envelope_unresolved(self):
        job = {"id": "job-2", "status": "queued", "kind": "video"}
        opener = _fake_opener([job])
        adapter = MediaAdapter(base_url="http://media.local", opener=opener)
        result = adapter.video("ocean waves", project="demo", wait=False)
        self.assertEqual(result["job_id"], "job-2")
        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["kind"], "video")
        self.assertEqual(len(opener.calls), 1)

    def test_balance(self):
        opener = _fake_opener([{"balance": 4.2, "project": "demo"}])
        adapter = MediaAdapter(base_url="http://media.local", opener=opener)
        result = adapter.balance(project="demo")
        self.assertEqual(result["balance"], 4.2)


class MediaAdapterFailureTests(unittest.TestCase):
    def test_service_unavailable_raises_media_unavailable(self):
        opener = _fake_opener([urllib.error.URLError("connection refused")])
        adapter = MediaAdapter(base_url="http://media.local", opener=opener)
        with self.assertRaises(MediaUnavailable) as ctx:
            adapter.image("prompt", project="demo")
        self.assertIn("media.local", str(ctx.exception))

    def test_budget_refused_returns_envelope_not_exception(self):
        err = _http_error(402, {
            "error": "budget_refused",
            "message": "over per-call ceiling",
            "math": {"ceiling": 0.5, "estimate": 0.56},
        })
        opener = _fake_opener([err])
        adapter = MediaAdapter(base_url="http://media.local", opener=opener)
        result = adapter.image("prompt", project="demo")
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["error"], "over per-call ceiling")
        self.assertEqual(result["math"]["ceiling"], 0.5)

    def test_timeout_when_job_never_settles(self):
        job = {"id": "job-3", "status": "queued", "kind": "image"}
        running = {"id": "job-3", "status": "running", "kind": "image"}
        opener = _fake_opener([job, running])
        adapter = MediaAdapter(base_url="http://media.local", opener=opener)
        with mock.patch("time.time", side_effect=[0, 0, 100]):
            with mock.patch("time.sleep"):
                result = adapter.wait("job-3", timeout=1.0, interval=0.1)
        self.assertEqual(result["status"], "timeout")
        self.assertEqual(result["job_id"], "job-3")


class MediaCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Isolate from any real ~/.config/harness/media.json on the host.
        self._env_patch = mock.patch.dict(os.environ, {
            "MEDIA_CONFIG_PATH": os.path.join(self.tmp.name, "media.json"),
            "MEDIA_BASE_URL": "http://media.local",
        }, clear=False)
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)
        # DEFAULT_BASE is bound at import, so the env above does not move it.
        # These tests are about CLI output and exit codes; endpoint identity
        # (the loopback probe, #566) has its own class below.
        self._base_patch = mock.patch(
            "harness.media_client.DEFAULT_BASE", "http://media.local")
        self._base_patch.start()
        self.addCleanup(self._base_patch.stop)

    def test_cli_image_success_exit_zero(self):
        job = {"id": "job-1", "status": "queued", "kind": "image"}
        done = {
            "id": "job-1", "status": "succeeded", "kind": "image",
            "provider": "acme", "model": "gen-1", "cost_actual": 0.01,
            "artifact_paths": ["/tmp/out.png"], "project": "demo",
        }
        opener = _fake_opener([job, done])
        out = io.StringIO()
        with mock.patch("harness.media_client.MediaAdapter",
                        lambda *a, **k: MediaAdapter(opener=opener)):
            with redirect_stdout(out):
                code = run_cli(["image", "a cabin", "--project", "demo"])
        self.assertEqual(code, 0)
        self.assertIn("succeeded", out.getvalue())
        self.assertIn("/tmp/out.png", out.getvalue())

    def test_cli_no_wait_reports_accepted_job_and_exits_zero(self):
        for kind, status in (("image", "queued"), ("video", "running")):
            with self.subTest(kind=kind, status=status):
                job_id = f"{kind}-accepted"
                job = {"id": job_id, "status": status, "kind": kind}
                opener = _fake_opener([job])
                out = io.StringIO()
                with mock.patch("harness.media_client.MediaAdapter",
                                lambda *a, **k: MediaAdapter(opener=opener)):
                    with redirect_stdout(out):
                        code = run_cli([kind, "test prompt", "--no-wait"])

                self.assertEqual(code, 0)
                self.assertIn(f"job {job_id}  [{status}]", out.getvalue())
                self.assertEqual(len(opener.calls), 1)

    def test_cli_service_unavailable_exits_four_and_defers(self):
        opener = _fake_opener([urllib.error.URLError("refused")])
        err = io.StringIO()
        with mock.patch("harness.media_client.MediaAdapter",
                        lambda *a, **k: MediaAdapter(opener=opener)):
            with redirect_stderr(err):
                code = run_cli(["image", "a cabin", "--project", "demo"])
        self.assertEqual(code, 4)
        self.assertIn("[defer] media:", err.getvalue())

    def test_cli_invalid_job_ids_are_argparse_errors(self):
        for job_id in ("", ".", ".."):
            with self.subTest(job_id=job_id):
                err = io.StringIO()
                with mock.patch.object(MediaAdapter, "_request") as request:
                    with redirect_stderr(err):
                        with self.assertRaises(SystemExit) as raised:
                            run_cli(["job", job_id])

                self.assertEqual(raised.exception.code, 2)
                self.assertIn("non-empty path segment", err.getvalue())
                self.assertNotIn("Traceback", err.getvalue())
                request.assert_not_called()

    def test_cli_job_lookup_still_succeeds(self):
        done = {
            "id": "job-1", "status": "succeeded", "kind": "image",
            "provider": "acme", "model": "gen-1", "project": "demo",
        }
        out = io.StringIO()
        with mock.patch.object(MediaAdapter, "_request", return_value=done) as request:
            with redirect_stdout(out):
                code = run_cli(["job", "job-1"])

        self.assertEqual(code, 0)
        self.assertIn("job job-1  [succeeded]", out.getvalue())
        request.assert_called_once_with("GET", "/v1/jobs/job-1")

    def test_cli_budget_refused_exits_nonzero_and_shows_math(self):
        e = _http_error(402, {
            "error": "budget_refused", "message": "over ceiling",
            "math": {"ceiling": 0.5},
        })
        opener = _fake_opener([e])
        out = io.StringIO()
        with mock.patch("harness.media_client.MediaAdapter",
                        lambda *a, **k: MediaAdapter(opener=opener)):
            with redirect_stdout(out):
                code = run_cli(["video", "ocean waves", "--project", "demo"])
        self.assertEqual(code, 1)
        self.assertIn("refused", out.getvalue())
        self.assertIn("ceiling", out.getvalue())

    def test_cli_provider_and_model_are_free_strings_not_choices(self):
        # No hardcoded provider ladder in argparse: an arbitrary provider
        # name must parse without argparse rejecting it.
        job = {"id": "job-9", "status": "queued", "kind": "image"}
        done = {
            "id": "job-9", "status": "succeeded", "kind": "image",
            "provider": "some-new-provider", "model": "whatever",
            "cost_actual": 0.0, "artifact_paths": [], "project": "demo",
        }
        opener = _fake_opener([job, done])
        out = io.StringIO()
        with mock.patch("harness.media_client.MediaAdapter",
                        lambda *a, **k: MediaAdapter(opener=opener)):
            with redirect_stdout(out):
                code = run_cli([
                    "image", "prompt", "--project", "demo",
                    "--provider", "some-new-provider", "--model", "whatever",
                ])
        self.assertEqual(code, 0)

    def test_cli_dispatch_from_harness_cli_main(self):
        # Confirms harness.cli intercepts "media" before argparse's main
        # build_parser (mirrors the serve/desktop early-intercept pattern).
        from harness import cli as harness_cli
        with mock.patch("harness.media_client.run_cli", return_value=0) as m:
            code = harness_cli.main(["media", "balance", "--project", "demo"])
        self.assertEqual(code, 0)
        m.assert_called_once_with(["balance", "--project", "demo"])


class JobIdQuotingTests(unittest.TestCase):
    """job_id is interpolated into the request path: hostile values must be
    percent-encoded (safe="") so they cannot alter the path structure."""

    def _adapter(self, responses):
        opener = _fake_opener(responses)
        return MediaAdapter(base_url="http://media.local", opener=opener), opener

    def test_wait_quotes_hostile_job_id(self):
        cases = [("../x", "..%2Fx"), ("a?b=c", "a%3Fb%3Dc"), ("a/b", "a%2Fb")]
        for hostile, quoted in cases:
            done = {"id": hostile, "status": "succeeded", "kind": "image"}
            adapter, opener = self._adapter([done])
            adapter.wait(hostile, timeout=1.0)
            method, url = opener.calls[0]
            self.assertEqual(method, "GET")
            self.assertTrue(url.endswith("/v1/jobs/" + quoted),
                            f"hostile {hostile!r} -> {url}")

    def test_job_quotes_hostile_job_id(self):
        for hostile, quoted in [("../x", "..%2Fx"), ("a?b=c", "a%3Fb%3Dc")]:
            done = {"id": hostile, "status": "succeeded", "kind": "image"}
            adapter, opener = self._adapter([done])
            adapter.job(hostile)
            _, url = opener.calls[0]
            self.assertTrue(url.endswith("/v1/jobs/" + quoted), url)

    def test_normal_job_id_unchanged(self):
        done = {"id": "job-1", "status": "succeeded", "kind": "image"}
        adapter, opener = self._adapter([done])
        env = adapter.job("job-1")
        self.assertTrue(opener.calls[0][1].endswith("/v1/jobs/job-1"))
        self.assertEqual(env["job_id"], "job-1")

    def test_wait_rejects_empty_and_dot_segments_before_request(self):
        for job_id in ("", ".", ".."):
            with self.subTest(job_id=job_id):
                adapter, opener = self._adapter([])
                with self.assertRaisesRegex(ValueError, "non-empty path segment"):
                    adapter.wait(job_id, timeout=1.0)
                self.assertEqual(opener.calls, [])

    def test_job_rejects_empty_and_dot_segments_before_request(self):
        for job_id in ("", ".", ".."):
            with self.subTest(job_id=job_id):
                adapter, opener = self._adapter([])
                with self.assertRaisesRegex(ValueError, "non-empty path segment"):
                    adapter.job(job_id)
                self.assertEqual(opener.calls, [])


class MediaOutputFlagsTests(unittest.TestCase):
    """Issue #329: every media subcommand supports --out/--quiet/--events/--no-color."""

    def test_all_media_subcommands_accept_and_honor_output_flags(self):
        import os
        import tempfile
        from harness import events as _events, output as _output, render as _render

        cases = [
            ("image", ["image", "a cabin", "--no-wait"],
             [{"id": "j1", "status": "queued", "kind": "image"}], 0, "queued"),
            ("video", ["video", "waves", "--no-wait"],
             [{"id": "j2", "status": "running", "kind": "video"}], 0, "running"),
            ("job", ["job", "j3"],
             [{"id": "j3", "status": "succeeded", "kind": "image"}], 0, "succeeded"),
            ("jobs", ["jobs", "--project", "demo"],
             [{"jobs": [{"id": "j4", "status": "succeeded", "kind": "image"}]}], 0, None),
            ("balance", ["balance", "--project", "demo"],
             [{"remaining": 4.25}], 0, None),
        ]
        old_quiet = _output.QUIET
        old_color = getattr(_render, "_COLOR_ENABLED", None)
        before_sinks = list(getattr(_events, "_sinks", []))
        try:
            with tempfile.TemporaryDirectory() as d:
                for subcmd, argv, payloads, expected_rc, expected_status in cases:
                    with self.subTest(subcmd=subcmd):
                        out_path = os.path.join(d, f"{subcmd}.json")
                        events_path = os.path.join(d, f"{subcmd}.events.jsonl")
                        opener = _fake_opener(payloads)

                        def fake_init(self, base_url=None, token=None, timeout=60,
                                      _opener=opener):
                            self.base = "http://media.local"
                            self.token = token or "tok"
                            self.timeout = timeout
                            self._opener = _opener
                            self._identified = True

                        with mock.patch.object(MediaAdapter, "__init__", fake_init), \
                             redirect_stdout(io.StringIO()), \
                             redirect_stderr(io.StringIO()):
                            rc = run_cli(argv + [
                                "--out", out_path, "--quiet",
                                "--events", events_path, "--no-color",
                            ])
                        self.assertEqual(rc, expected_rc)
                        with open(out_path, encoding="utf-8") as handle:
                            data = json.load(handle)
                        if expected_status:
                            self.assertEqual(data["status"], expected_status)
                        elif subcmd == "jobs":
                            self.assertEqual(data["jobs"][0]["job_id"], "j4")
                        else:
                            self.assertEqual(data["remaining"], 4.25)

                err_out = os.path.join(d, "unavailable.json")
                opener = _fake_opener([urllib.error.URLError("down")])

                def fake_init_down(self, base_url=None, token=None, timeout=60,
                                   _opener=opener):
                    self.base = "http://media.local"
                    self.token = token or "tok"
                    self.timeout = timeout
                    self._opener = _opener
                    self._identified = True

                with mock.patch.object(MediaAdapter, "__init__", fake_init_down), \
                     redirect_stdout(io.StringIO()), \
                     redirect_stderr(io.StringIO()):
                    rc = run_cli(["balance", "--out", err_out, "--quiet", "--no-color"])
                self.assertEqual(rc, 4)
                with open(err_out, encoding="utf-8") as handle:
                    self.assertEqual(json.load(handle)["status"], "deferred")

                for stdout_argv, opener_resp, expected_sub in (
                    (["jobs", "--project", "demo"],
                     [{"jobs": [{"id": "j5", "status": "succeeded", "kind": "image"}]}],
                     "job j5  [succeeded]"),
                    (["balance", "--project", "demo"],
                     [{"remaining": 3.5}],
                     "3.5"),
                ):
                    with self.subTest(stdout_argv=stdout_argv):
                        buf = io.StringIO()
                        op = _fake_opener(opener_resp)

                        def fake_init_plain(self, base_url=None, token=None, timeout=60,
                                            _opener=op):
                            self.base = "http://media.local"
                            self.token = token or "tok"
                            self.timeout = timeout
                            self._opener = _opener
                            self._identified = True

                        with mock.patch.object(MediaAdapter, "__init__", fake_init_plain), \
                             redirect_stdout(buf):
                            rc = run_cli(stdout_argv)
                        self.assertEqual(rc, 0)
                        self.assertIn(expected_sub, buf.getvalue())
        finally:
            _output.QUIET = old_quiet
            if old_color is not None:
                _render.set_color_enabled(old_color)
            for sink in list(getattr(_events, "_sinks", [])):
                if sink not in before_sinks:
                    _events.remove_sink(sink)
                    if hasattr(sink, "close"):
                        sink.close()


class MediaEndpointIdentityTests(unittest.TestCase):
    """#566: a loopback endpoint must be the media service before it is used.

    The harness UI and the media service both defaulted to 127.0.0.1:8765, so a
    loopback endpoint can be the wrong service. The guard is one credential-free
    read-only probe: no media operation and no token before it passes.
    """

    BASE = "http://127.0.0.1:8765"

    def _adapter(self, responses, token="owner-secret"):
        opener = _fake_opener(responses)
        adapter = MediaAdapter(base_url=self.BASE, token=token, opener=opener)
        return adapter, opener

    def test_a_harness_ui_at_the_endpoint_raises_mismatch_before_any_token(self):
        ui = _FakeResponse({"error": "not found"}, headers={
            "Server": "harness-ui/1.4.0 Python/3.11",
        })
        adapter, opener = self._adapter([ui])
        with self.assertRaises(MediaEndpointMismatch) as raised:
            adapter.image("a cabin")
        message = str(raised.exception)
        self.assertIn("media service", message)
        self.assertIn(self.BASE, message)
        self.assertIn("MEDIA_BASE_URL", message)
        self.assertEqual(opener.calls, [("GET", self.BASE + "/v1/balance")])
        self.assertFalse(any("owner-secret" in str(h) for h in opener.headers))

    def test_an_identified_ui_without_a_server_header_is_still_caught(self):
        ui = _FakeResponse({"error": "not found"}, headers={
            "X-Harness-Commit": "abc123",
        })
        adapter, opener = self._adapter([ui])
        with self.assertRaises(MediaEndpointMismatch):
            adapter.image("a cabin")
        self.assertEqual(len(opener.calls), 1)

    def test_a_bare_401_without_identity_is_unidentified_not_a_ui(self):
        challenge = urllib.error.HTTPError(
            url=self.BASE, code=401, msg="unauthorized", hdrs=None,
            fp=io.BytesIO(b""))
        adapter, opener = self._adapter([challenge])
        with self.assertRaises(MediaUnavailable) as raised:
            adapter.image("a cabin")
        message = str(raised.exception)
        self.assertNotIsInstance(raised.exception, MediaEndpointMismatch)
        self.assertIn("did not identify", message)
        self.assertIn("no token was sent", message)
        self.assertEqual(len(opener.calls), 1)

    def test_a_media_identity_answer_lets_the_operation_through(self):
        balance = _FakeResponse({"balance": 4.0, "currency": "USD"})
        job = {"id": "job-1", "status": "succeeded", "kind": "image"}
        adapter, opener = self._adapter([balance, job])
        result = adapter.image("a cabin", wait=False)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(opener.calls, [
            ("GET", self.BASE + "/v1/balance"),
            ("POST", self.BASE + "/v1/jobs"),
        ])
        # The probe is credential-free; the operation carries the token.
        self.assertFalse(any("owner-secret" in str(h) for h in opener.headers[:1]))
        self.assertTrue(any("owner-secret" in str(h) for h in opener.headers[1:]))

    def test_the_media_credential_challenge_is_recognized(self):
        # #683 finding 23: the challenge identifies the service only when it
        # names the media credential; a generic "sign in required" does not.
        challenge = _http_error(401, {"error": "X-Media-Token required"})
        job = {"id": "job-2", "status": "succeeded", "kind": "image"}
        adapter, opener = self._adapter([challenge, job])
        self.assertEqual(adapter.image("x", wait=False)["status"], "succeeded")
        self.assertEqual(len(opener.calls), 2)

    def test_a_generic_json_error_sends_no_token(self):
        generic = _http_error(404, {"detail": "Not Found"})
        adapter, opener = self._adapter([generic])
        with self.assertRaises(MediaUnavailable) as raised:
            adapter.image("a cabin")
        self.assertIn("did not identify", str(raised.exception))
        self.assertEqual(opener.calls, [("GET", self.BASE + "/v1/balance")])
        self.assertFalse(any("owner-secret" in str(h) for h in opener.headers))

    def test_an_unreachable_endpoint_still_says_how_to_start_it(self):
        adapter, opener = self._adapter([urllib.error.URLError("refused")])
        with self.assertRaises(MediaUnavailable) as raised:
            adapter.image("a cabin")
        self.assertIn("media serve", str(raised.exception))
        self.assertEqual(len(opener.calls), 1)

    def test_the_probe_runs_once_per_adapter(self):
        balance = _FakeResponse({"balance": 1.0})
        first = {"id": "a", "status": "succeeded", "kind": "image"}
        second = {"id": "b", "status": "succeeded", "kind": "image"}
        adapter, opener = self._adapter([balance, first, second])
        adapter.image("one", wait=False)
        adapter.image("two", wait=False)
        probes = [c for c in opener.calls if c[1].endswith("/v1/balance")]
        self.assertEqual(len(probes), 1)

    def test_a_remote_endpoint_is_operator_declared_and_not_probed(self):
        job = {"id": "job-3", "status": "succeeded", "kind": "image"}
        opener = _fake_opener([job])
        adapter = MediaAdapter(base_url="http://media.local", opener=opener)
        self.assertEqual(adapter.image("x", wait=False)["status"], "succeeded")
        self.assertEqual(opener.calls, [("POST", "http://media.local/v1/jobs")])

    def test_the_identification_table_covers_every_answer_shape(self):
        cases = [
            ({"Server": "harness-ui/0.1 Python/3.9"}, b'{"error": "x"}',
             "harness-ui"),
            ({"X-Harness-Version": "0.5.0"}, b"", "harness-ui"),
            ({}, b"<html>Harness UI</html>", "harness-ui"),
            ({}, b'{"balance": 2.0}', "media"),
            ({}, b'[{"jobs": 1}]', "media"),
            # #683 finding 23: a generic JSON error names nothing media-
            # specific, so it cannot identify the service.
            (None, '{"detail": "sign in"}', "unknown"),
            (None, '{"detail": "Not Found"}', "unknown"),
            (None, '{"error": "invalid request"}', "unknown"),
            # The service's own credential challenge still identifies it.
            (None, '{"detail": "X-Media-Token required"}', "media"),
            (None, '{"error": "media token missing"}', "media"),
            ({}, b"[]", "unknown"),
            ({}, b"3", "unknown"),
            ({}, b'{"unrelated": 1}', "unknown"),
            ({}, b"not json", "unknown"),
            (object(), b'{"balance": 1}', "media"),
        ]
        for headers, body, expected in cases:
            with self.subTest(headers=headers, body=body):
                self.assertEqual(identify_service(headers, body), expected)

    def test_a_malformed_base_url_is_not_treated_as_loopback(self):
        # An unparsable URL must not be probed as if it were local.
        self.assertFalse(is_loopback("http://[::1"))
        self.assertTrue(is_loopback("http://localhost:8765"))
        self.assertFalse(is_loopback("http://media.example:8765"))

    def test_the_defaults_keep_the_ui_off_the_media_port(self):
        import inspect
        from harness import server as server_module
        self.assertEqual(
            inspect.signature(server_module.make_server)
            .parameters["port"].default, 8767)
        self.assertIn("8765", DEFAULT_BASE)

if __name__ == "__main__":
    unittest.main()
