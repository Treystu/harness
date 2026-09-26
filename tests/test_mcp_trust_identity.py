"""Who may name the caller, and how the auth secret is compared.

Two properties of the MCP trust root, pinned together because they are the
same boundary seen from two sides: a peer's self-declared identity must not
be able to buy trust, and the secret that gates tool calls must not be
recoverable by watching how long a rejection takes.

Neither is visible in the functional MCP tests. A forged caller name produces
entirely plausible ledger output, and a timing-unsafe compare returns exactly
the right answer, so both defects pass every behavioural test that exists.
Something has to assert the property directly, which is this module.
"""
import hmac
import json
import unittest
from types import SimpleNamespace

from harness.mcp import McpServer
from tests.test_mcp import make_server, _serve


# A caller that has already climbed the trust ladder. Reusing this name is
# the impersonation these tests exist to prevent: trust is scored per caller,
# so claiming it would claim the score.
ESTABLISHED_NAME = "sparkx-apply-driver"
ESTABLISHED_VERSION = "1.1"
OPERATOR_ASSIGNED = "mcp:http/operator-assigned"


def _initialize_frame(client_name, client_version):
    """Built with json.dumps so the clientInfo under test is exactly what a
    client would send, rather than a hand-escaped approximation of it."""
    return json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "clientInfo": {"name": client_name, "version": client_version},
        },
    }) + "\n"


class TrustIdentityTests(unittest.TestCase):
    def test_stdio_default_honours_client_info(self):
        """The stdio trust model, unchanged: the peer is the embedding host,
        so its claim is as strong as the process boundary that produced it.
        Asserted alongside the default itself because the default is the
        security-relevant choice -- silently flipping it would reattribute
        ledger evidence for every existing stdio embedder, and no functional
        test would fail."""
        _, server = make_server()
        self.assertTrue(server.trust_client_info)
        _serve(server, _initialize_frame("probe-harness", "1.0"))
        self.assertEqual(server.caller, "mcp:probe-harness/1.0")

    def test_untrusted_transport_cannot_claim_an_established_caller(self):
        """The escalation this closes. The ledger is the trust root, so a peer
        that can name itself can name an identity that has already earned
        trust and inherit its score and history. A transport carrying an
        untrusted peer must keep the operator-assigned identity instead."""
        _, server = make_server()
        server.trust_client_info = False
        server.caller = OPERATOR_ASSIGNED
        server.ledger.caller = OPERATOR_ASSIGNED
        _serve(server, _initialize_frame(ESTABLISHED_NAME, ESTABLISHED_VERSION))
        self.assertEqual(server.caller, OPERATOR_ASSIGNED)
        self.assertNotEqual(server.caller, "mcp:" + ESTABLISHED_NAME + "/" + ESTABLISHED_VERSION)

    def test_untrusted_transport_does_not_retag_the_ledger(self):
        """The caller is not the only thing at stake. _capture_caller also
        re-tags the shared ledger, so an untrusted initialize would silently
        reattribute every later event on that connection, not just its own."""
        _, server = make_server()
        server.trust_client_info = False
        server.caller = OPERATOR_ASSIGNED
        server.ledger.caller = OPERATOR_ASSIGNED
        _serve(server, _initialize_frame(ESTABLISHED_NAME, ESTABLISHED_VERSION))
        self.assertEqual(server.ledger.caller, OPERATOR_ASSIGNED)


class AuthCompareTests(unittest.TestCase):
    """mcp_auth_token gates tools/call once a token is configured."""

    def _server(self, token):
        return McpServer(
            transport=None, api_key="k",
            governor=SimpleNamespace(spent=0.0, max_cost=1.0), ledger=None,
            router=None, engine=None, auth_token=token)

    def _call(self, server, presented):
        return server._check_auth({
            "method": "tools/call", "id": 1,
            "params": {"name": "spend_status",
                       "_meta": {"harness_token": presented}},
        })

    def test_comparison_goes_through_constant_time_compare(self):
        """Pinned behaviourally, not textually. A byte-wise == on a shared
        secret leaks it to a patient prober through response timing. Every
        other test in this module passes with a plain ==, which is exactly
        why this one has to exist to hold the property."""
        calls = []
        real = hmac.compare_digest

        def spy(a, b):
            calls.append((a, b))
            return real(a, b)

        hmac.compare_digest = spy
        self.addCleanup(setattr, hmac, "compare_digest", real)

        self.assertIsNone(self._call(self._server("secret"), "secret"))
        self.assertEqual(calls, [("secret", "secret")])

    def test_hardening_does_not_change_the_verdict(self):
        """Same refusals as before, including the near-misses a prefix, a
        trailing space, or a case difference would slip through if the
        comparison were ever loosened."""
        server = self._server("secret")
        for wrong in ("secrer", "secr", "secret ", "Secret", "SECRET", ""):
            denied = self._call(server, wrong)
            self.assertIsNotNone(denied, f"token {wrong!r} was accepted")
            self.assertEqual(denied["error"]["code"], -32001)

    def test_correct_token_still_accepted(self):
        self.assertIsNone(self._call(self._server("secret"), "secret"))


if __name__ == "__main__":
    unittest.main()
