"""W0.5 (#510): generic direct backends (Groq/Cerebras) -- namespace, keys,
dispatch, accounting, and pool assembly.

Hermetic. A recording transport supplies every response. Settings and key
lookup run against a temp HOME and CONFIG_DIR, so the operator's real config
and key files are never read, and a socket guard proves nothing here opens a
connection. No test touches the network or needs a provider key.
"""
import io
import os
import socket
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from harness import config
from harness.chat import (chat, chat_for_route, chat_routed,
                            governed_completion)
from harness.direct_compat import (provider_for, resolve_offer,
                                   wire_model)
from harness.config import (CEREBRAS_PROVIDER, DEFAULT_CEREBRAS_POOL,
                            DEFAULT_GROQ_POOL, FREE_APPLY_POOL,
                            GROQ_PROVIDER, direct_backend_pool,
                            is_cerebras_model_id, is_direct_compat_id,
                            is_groq_model_id, laptop_local_pool,
                            resolve_cerebras_key, resolve_groq_key,
                            shipped_model_ids)
from harness.errors import HarnessError
from harness.results import _http_error
from harness.routing_table import (backend_for_model, backend_registry,
                                   route_for_model)

GROQ_ID = "groq/openai/gpt-oss-120b"
GROQ_WIRE = "openai/gpt-oss-120b"
CEREBRAS_ID = "cerebras/gpt-oss-120b"
MESSAGES = [{"role": "user", "content": "Reply with the single word: ok"}]
_DIRECT_ENV = ("GROQ_API_KEY", "HARNESS_GROQ_KEY", "CEREBRAS_API_KEY",
               "HARNESS_CEREBRAS_KEY", "HARNESS_GROQ_BASE_URL",
               "HARNESS_CEREBRAS_BASE_URL")
_OTHER_KEYS = ("OPENROUTER_API_KEY", "FIREWORKS_API_KEY",
               "HARNESS_FIREWORKS_KEY", "META_API_KEY", "MUSE_API_KEY")


class RecordingTransport:
    """Returns canned responses in order and records every POST."""

    def __init__(self, resps):
        self.resps = list(resps)
        self.calls = []

    def post(self, url, api_key, payload, timeout=45):
        self.calls.append((url, api_key, payload))
        status, resp = self.resps[min(len(self.calls) - 1, len(self.resps) - 1)]
        return status, resp

    def get(self, url, api_key, timeout=15):
        raise AssertionError(f"direct-compat tests must not GET {url}")


def _resp(content="ok", **usage):
    return {"choices": [{"message": {"content": content},
                         "finish_reason": "stop"}],
            "usage": dict(usage)}


class _StubGovernor:
    """Only the governor surface _chat_direct touches."""

    def __init__(self, remaining=1.0):
        self._remaining = remaining

    def check_byok(self, model_id):
        return None

    def assert_no_tools(self, payload, label):
        return None

    def remaining(self):
        return self._remaining


class _GovernedStub(_StubGovernor):
    """The extra governor surface governed_completion touches."""

    def preflight(self, prompt, calls):
        return None

    def record_actual(self, cost, model, lane=None):
        return None


class _IsolatedHome(unittest.TestCase):
    """Point HOME, USERPROFILE and CONFIG_DIR at a temp dir for each test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self.config_dir = self.home / ".config" / "harness"
        env = {"HOME": str(self.home), "USERPROFILE": str(self.home)}
        self._env = mock.patch.dict(os.environ, env)
        self._env.start()
        for name in _DIRECT_ENV + _OTHER_KEYS:
            os.environ.pop(name, None)
        self._cfg = mock.patch.object(config, "CONFIG_DIR", str(self.config_dir))
        self._cfg.start()

    def tearDown(self):
        self._cfg.stop()
        self._env.stop()
        self._tmp.cleanup()

    def _write(self, rel, text):
        path = self.home / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


class NamespaceTests(unittest.TestCase):
    def test_prefix_predicates(self):
        self.assertTrue(is_groq_model_id(GROQ_ID))
        self.assertTrue(is_cerebras_model_id(CEREBRAS_ID))
        self.assertTrue(is_direct_compat_id(GROQ_ID))
        self.assertTrue(is_direct_compat_id(CEREBRAS_ID))
        self.assertFalse(is_groq_model_id(CEREBRAS_ID))
        self.assertFalse(is_cerebras_model_id(GROQ_ID))

    def test_openrouter_ids_are_never_direct(self):
        for mid in ("deepseek/deepseek-v4-flash", "openai/gpt-oss-120b",
                    "qwen/qwen3-32b", "groq", "cerebras", "", None):
            self.assertFalse(is_direct_compat_id(mid), mid)

    def test_namespace_cannot_collide_with_shipped_openrouter_ids(self):
        for mid in shipped_model_ids():
            self.assertFalse(is_direct_compat_id(mid), mid)

    def test_provider_and_wire_mapping(self):
        self.assertEqual(provider_for(GROQ_ID), GROQ_PROVIDER)
        self.assertEqual(provider_for(CEREBRAS_ID), CEREBRAS_PROVIDER)
        self.assertEqual(wire_model(GROQ_ID), GROQ_WIRE)
        self.assertEqual(wire_model(CEREBRAS_ID), "gpt-oss-120b")
        with self.assertRaises(HarnessError):
            provider_for("deepseek/deepseek-v4-flash")

    def test_unknown_wire_ids_fail_closed(self):
        for mid in ("groq/llama-3.3-70b-versatile",
                    "groq/no-such-model",
                    "cerebras/no-such-model",
                    "deepseek/deepseek-v4-flash"):
            with self.assertRaises(HarnessError, msg=mid):
                resolve_offer(mid)

    def test_committed_pools_are_cheapest_first(self):
        self.assertEqual(DEFAULT_GROQ_POOL, [
            "groq/openai/gpt-oss-20b",
            "groq/openai/gpt-oss-120b",
            "groq/qwen/qwen3-32b",
        ])
        self.assertEqual(DEFAULT_CEREBRAS_POOL, [
            "cerebras/gpt-oss-120b",
            "cerebras/qwen-3-32b",
        ])
        for pool in (DEFAULT_GROQ_POOL, DEFAULT_CEREBRAS_POOL):
            for mid in pool:
                resolve_offer(mid)

    def test_backend_registry_names_the_key_surfaces(self):
        registry = backend_registry()
        self.assertIn(GROQ_PROVIDER, registry)
        self.assertIn(CEREBRAS_PROVIDER, registry)
        self.assertEqual(backend_for_model(GROQ_ID), GROQ_PROVIDER)
        self.assertEqual(backend_for_model(CEREBRAS_ID), CEREBRAS_PROVIDER)
        self.assertEqual(backend_for_model("deepseek/deepseek-v4-flash"),
                         "openrouter")

    def test_route_for_model_resolves_identity_and_refuses_unknown(self):
        route = route_for_model(GROQ_ID)
        self.assertEqual(route.provider, GROQ_PROVIDER)
        self.assertEqual(route.wire_model, GROQ_ID)
        self.assertEqual(route.offer.model, GROQ_ID)
        route = route_for_model(CEREBRAS_ID)
        self.assertEqual(route.provider, CEREBRAS_PROVIDER)
        with self.assertRaises(HarnessError):
            route_for_model("groq/no-such-model")


class KeyTests(_IsolatedHome):
    def test_scmorc_file_wins_over_harness_file_and_env(self):
        self._write(".config/scmorc/groq.env", "GROQ_API_KEY=scmorc-key\n")
        self._write(".config/harness/groq.env", "GROQ_API_KEY=harness-key\n")
        os.environ["GROQ_API_KEY"] = "env-key"
        self.assertEqual(resolve_groq_key(), "scmorc-key")

    def test_harness_file_is_the_second_source(self):
        self._write(".config/harness/cerebras.env",
                    "CEREBRAS_API_KEY=harness-key\n")
        os.environ["CEREBRAS_API_KEY"] = "env-key"
        self.assertEqual(resolve_cerebras_key(), "harness-key")

    def test_env_is_used_last_and_its_value_is_never_logged(self):
        os.environ["GROQ_API_KEY"] = "gsk-super-secret-value"
        buf = io.StringIO()
        with redirect_stderr(buf):
            self.assertEqual(resolve_groq_key(), "gsk-super-secret-value")
        self.assertNotIn("gsk-super-secret-value", buf.getvalue())

    def test_openrouter_key_in_the_file_is_not_read_as_direct(self):
        self._write(".config/harness/groq.env",
                    "OPENROUTER_API_KEY=or-key\n")
        self.assertIsNone(resolve_groq_key())

    def test_no_key_anywhere_resolves_to_none(self):
        self.assertIsNone(resolve_groq_key())
        self.assertIsNone(resolve_cerebras_key())

    def test_missing_key_refuses_before_dispatch(self):
        transport = RecordingTransport([(200, _resp(cost=0.001))])
        with self.assertRaisesRegex(HarnessError, "Groq key missing"):
            chat(transport, "or-key", GROQ_ID, MESSAGES, 64)
        self.assertEqual(transport.calls, [])
        with self.assertRaisesRegex(HarnessError, "Cerebras key missing"):
            chat(transport, "or-key", CEREBRAS_ID, MESSAGES, 64)
        self.assertEqual(transport.calls, [])


class DispatchTests(_IsolatedHome):
    def _ok(self, **usage):
        return RecordingTransport([(200, _resp(**usage))])

    def test_groq_posts_the_openai_shape_to_the_groq_url(self):
        transport = self._ok(cost=0.001)
        status, _ = chat(transport, "or-key", GROQ_ID, MESSAGES, 64,
                         groq_key="g-key")
        self.assertEqual(status, 200)
        (url, key, payload), = transport.calls
        self.assertEqual(url, "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(key, "g-key")
        self.assertEqual(payload, {"model": GROQ_WIRE, "messages": MESSAGES,
                                  "max_tokens": 64})

    def test_cerebras_posts_the_openai_shape_to_the_cerebras_url(self):
        transport = self._ok(cost=0.001)
        status, _ = chat(transport, "or-key", CEREBRAS_ID, MESSAGES, 64,
                         cerebras_key="c-key")
        self.assertEqual(status, 200)
        (url, key, payload), = transport.calls
        self.assertEqual(url, "https://api.cerebras.ai/v1/chat/completions")
        self.assertEqual(key, "c-key")
        self.assertEqual(payload["model"], "gpt-oss-120b")

    def test_base_url_override_is_honored(self):
        os.environ["HARNESS_GROQ_BASE_URL"] = "https://groq.local/v1"
        transport = self._ok(cost=0.001)
        chat(transport, "or-key", GROQ_ID, MESSAGES, 64, groq_key="g-key")
        (url, _, _), = transport.calls
        self.assertEqual(url, "https://groq.local/v1/chat/completions")

    def test_the_openrouter_key_is_never_posted_to_a_direct_backend(self):
        transport = self._ok(cost=0.001)
        chat(transport, "or-key", GROQ_ID, MESSAGES, 64, groq_key="g-key")
        for _, key, _ in transport.calls:
            self.assertNotEqual(key, "or-key")

    def test_routed_dispatch_uses_the_settings_key_surface(self):
        from harness.config import load_settings
        settings = load_settings(
            overrides={"groq_key": "g-settings-key",
                       "cerebras_key": "c-settings-key"})
        transport = self._ok(cost=0.001)
        status, _ = chat_routed(transport, "or-key", GROQ_ID, MESSAGES, 64,
                                settings=settings)
        self.assertEqual(status, 200)
        (_, key, _), = transport.calls
        self.assertEqual(key, "g-settings-key")
        transport = self._ok(cost=0.001)
        route = route_for_model(CEREBRAS_ID)
        status, _ = chat_for_route(route, transport, "or-key", None,
                                   MESSAGES, 64, cerebras_key="c-key")
        self.assertEqual(status, 200)
        (_, key, _), = transport.calls
        self.assertEqual(key, "c-key")

    def test_error_statuses_surface_with_the_provider_message(self):
        for status, message in ((402, "spend limit exhausted"),
                                (429, "rate limit exceeded"),
                                (500, "upstream error")):
            body = {"error": {"message": message, "type": "provider_error",
                              "code": "upstream"}}
            transport = RecordingTransport([(status, body)])
            got_status, got_resp = chat(transport, "or-key", GROQ_ID,
                                        MESSAGES, 64, groq_key="g-key")
            self.assertEqual(got_status, status)
            self.assertEqual(got_resp, body)
            self.assertEqual(_http_error(got_status, got_resp),
                             f"HTTP {status}: {message}")


class GovernedKeyThreadingTests(_IsolatedHome):
    """W0.5 wiring: governed_completion threads the settings direct keys.

    Hermetic: the recording transport stands in for Groq/Cerebras, and the
    isolated home means no real key file or environment key can leak in."""

    def test_settings_keyed_groq_id_posts_settings_key_to_groq_url(self):
        transport = RecordingTransport([(200, _resp(cost=0.001))])
        completion = governed_completion(
            transport, "or-key", _GovernedStub(), GROQ_ID, "hi", 64,
            label="simple-answer", groq_key="g-settings-key",
            cerebras_key="c-settings-key")
        self.assertEqual(completion["model"], GROQ_ID)
        (url, key, _), = transport.calls
        self.assertEqual(url,
                         "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(key, "g-settings-key")
        self.assertNotEqual(key, "or-key")

    def test_settings_keyed_cerebras_id_posts_settings_key(self):
        transport = RecordingTransport([(200, _resp(cost=0.001))])
        completion = governed_completion(
            transport, "or-key", _GovernedStub(), CEREBRAS_ID, "hi", 64,
            label="simple-answer", groq_key="g-settings-key",
            cerebras_key="c-settings-key")
        self.assertEqual(completion["model"], CEREBRAS_ID)
        (url, key, _), = transport.calls
        self.assertEqual(url, "https://api.cerebras.ai/v1/chat/completions")
        self.assertEqual(key, "c-settings-key")
        self.assertNotEqual(key, "or-key")

    def test_missing_keys_refuse_before_dispatch(self):
        transport = RecordingTransport([(200, _resp(cost=0.001))])
        with self.assertRaisesRegex(HarnessError, "Groq key missing"):
            governed_completion(transport, "or-key", _GovernedStub(),
                                GROQ_ID, "hi", 64)
        self.assertEqual(transport.calls, [])
        with self.assertRaisesRegex(HarnessError, "Cerebras key missing"):
            governed_completion(transport, "or-key", _GovernedStub(),
                                CEREBRAS_ID, "hi", 64)
        self.assertEqual(transport.calls, [])


class AccountingTests(unittest.TestCase):
    def test_provider_reported_cost_is_kept_as_is(self):
        transport = RecordingTransport([(200, _resp(cost=0.0042))])
        status, resp = chat(transport, "or-key", GROQ_ID, MESSAGES, 64,
                            groq_key="g-key",
                            governor=_StubGovernor())
        self.assertEqual(status, 200)
        self.assertEqual(resp["usage"]["cost"], 0.0042)
        self.assertNotIn("cost_estimated", resp["usage"])

    def test_missing_cost_is_estimated_from_committed_rates(self):
        # groq/openai/gpt-oss-20b: $0.075/$0.30 per 1M tokens.
        transport = RecordingTransport(
            [(200, _resp(prompt_tokens=1000, completion_tokens=500))])
        status, resp = chat(transport, "or-key",
                            "groq/openai/gpt-oss-20b", MESSAGES, 64,
                            groq_key="g-key", governor=_StubGovernor())
        self.assertEqual(status, 200)
        self.assertAlmostEqual(resp["usage"]["cost"], 0.000225)
        self.assertTrue(resp["usage"]["cost_estimated"])

    def test_missing_cost_and_counts_is_refused(self):
        transport = RecordingTransport([(200, _resp())])
        with self.assertRaisesRegex(HarnessError, "refusing to bill blind"):
            chat(transport, "or-key", GROQ_ID, MESSAGES, 64,
                 groq_key="g-key", governor=_StubGovernor())
        self.assertEqual(len(transport.calls), 1)

    def test_worst_case_over_remaining_is_refused_before_dispatch(self):
        transport = RecordingTransport([(200, _resp(cost=0.001))])
        with self.assertRaisesRegex(HarnessError, "remaining budget"):
            chat(transport, "or-key", GROQ_ID, MESSAGES, 64,
                 groq_key="g-key", governor=_StubGovernor(remaining=0.0))
        self.assertEqual(transport.calls, [])


class SpendPricingTests(unittest.TestCase):
    """W0.5 pricing cure (#510): the governor prices keyed direct ids from
    the committed offers without consulting the OpenRouter catalog.

    Hermetic. The recording transport refuses every GET, and fetch_models
    is additionally mocked to raise, so a passing committed-id test proves
    no catalog consult. No test touches the network or needs a provider key.
    """

    def _governor(self):
        from harness.spend import SpendGovernor
        transport = RecordingTransport([(200, _resp(cost=0.001))])
        return SpendGovernor(transport, "or-key")

    def _no_catalog(self, gov):
        return mock.patch.object(
            gov, "fetch_models",
            side_effect=AssertionError("must not consult OpenRouter catalog"))

    def test_committed_ids_price_from_committed_offers(self):
        gov = self._governor()
        with self._no_catalog(gov):
            pricing = gov.fetch_pricing([GROQ_ID, CEREBRAS_ID])
        for mid in (GROQ_ID, CEREBRAS_ID):
            offer = resolve_offer(mid)
            self.assertEqual(pricing[mid], (offer.prompt, offer.completion))

    def test_committed_groq_rates_match_published_list(self):
        # groq/openai/gpt-oss-20b: $0.075/$0.30 per 1M tokens.
        gov = self._governor()
        with self._no_catalog(gov):
            pricing = gov.fetch_pricing(["groq/openai/gpt-oss-20b"])
        prompt, completion = pricing["groq/openai/gpt-oss-20b"]
        self.assertAlmostEqual(prompt, 0.075 / 1_000_000)
        self.assertAlmostEqual(completion, 0.30 / 1_000_000)

    def test_uncommitted_direct_ids_fail_closed(self):
        for mid in ("groq/no-such-model", "cerebras/no-such-model"):
            gov = self._governor()
            with self._no_catalog(gov):
                with self.assertRaises(HarnessError, msg=mid):
                    gov.fetch_pricing([mid])


class PoolTests(_IsolatedHome):
    def test_no_keys_means_no_direct_ids_only_free_rungs(self):
        self.assertEqual(direct_backend_pool(), [])
        self.assertEqual(laptop_local_pool(), list(FREE_APPLY_POOL))

    def test_missing_keys_exclude_their_ids(self):
        pool = direct_backend_pool(groq_key="g-key")
        self.assertTrue(all(mid.startswith("groq/") for mid in pool))
        self.assertEqual(pool, list(DEFAULT_GROQ_POOL))

    def test_full_pool_is_cheapest_capable_first_with_committed_offers(self):
        pool = direct_backend_pool(groq_key="g", cerebras_key="c",
                                   fireworks_key="f", meta_key="m")
        rates = config._direct_offer_rates()
        for mid in pool:
            self.assertIn(mid, rates, mid)
        blended = {mid: 4000 * rates[mid][0] + 1500 * rates[mid][1]
                   for mid in pool}
        self.assertEqual(pool, sorted(pool, key=lambda m: (blended[m], m)))
        self.assertEqual(len(pool), len(set(pool)))

    def test_local_pool_appends_free_rungs_untouched(self):
        pool = laptop_local_pool(groq_key="g", cerebras_key="c")
        direct = [m for m in pool if is_direct_compat_id(m)]
        self.assertEqual(pool[len(direct):], list(FREE_APPLY_POOL))
        self.assertEqual(direct, direct_backend_pool(groq_key="g",
                                                    cerebras_key="c"))

    def test_unroutable_fireworks_ids_never_leak_into_the_pool(self):
        pool = direct_backend_pool(fireworks_key="f", meta_key="m")
        from harness.fireworks import resolve_offer as _fw_offer
        for mid in pool:
            if mid.startswith("accounts/"):
                _fw_offer(mid)


class NoNetworkTests(unittest.TestCase):
    def test_route_dispatch_pool_and_pricing_open_no_socket(self):
        def refuse(*_a, **_k):
            raise AssertionError("direct-compat must not touch the network")

        transport = RecordingTransport([(200, _resp(cost=0.001))])
        with mock.patch.object(socket, "socket", side_effect=refuse), \
                mock.patch.object(socket, "create_connection",
                                  side_effect=refuse), \
                mock.patch.object(socket, "getaddrinfo", side_effect=refuse):
            route = route_for_model(GROQ_ID)
            chat_for_route(route, transport, "or-key", None, MESSAGES, 8,
                           groq_key="g-key")
            direct_backend_pool(groq_key="g", cerebras_key="c")
            laptop_local_pool(groq_key="g")


if __name__ == "__main__":
    unittest.main()
