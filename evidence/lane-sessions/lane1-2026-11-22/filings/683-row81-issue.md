# Bind the fetch policy before passing the default fetcher

Part of #683, finding 81 (P1). Verified against `main` `8fc28a0e` on
2026-11-25: still present.

## Method

Code read of the named path at `8fc28a0e`: `harness/web.py` and the code it calls,
on 2026-11-25. No repository code changed in that act, so this is a read
of the shipped path, not a run and not a test.

## Result

harness/web.py:867-875 hands `fetch_url` (or the injected `fetch_url_fn`) straight to `execute_plan` as the plan's `fetch_fn`, while `fetch_url` at :616-617 requires `allowed_hosts` and the legacy branch at :900-905 passes it explicitly. harness/research_plan.py:798-803 then calls `fetch_fn(url)` with one positional argument, and `_fetch_source` catches only `HarnessError`, so the `TypeError` escapes an accepted URL plan and the gatherer returns nothing.

## The finding

For an accepted URL plan using the default transport, `execute_plan` eventually invokes `_fetch_source`, which calls `fetch_fn(url)`, but `fetch_url` requires an `allowed_hosts` argument. This path therefore raises an uncaught `TypeError` before fetching anything. Unlike the legacy path, it also never forwards `allow_any_public` or `named_hosts`. Pass an adapter that supplies the configured fetch policy; the existing one-argument test doubles conceal this failure.

## Scope of this issue

Pass an adapter that supplies the configured fetch policy, so the default transport receives the allowlist, the any-public exemption and the named hosts exactly as the legacy path does. One-argument test doubles stay valid, which is why the adapter is the fix rather than a second required parameter.

## Not claimed

- Not claimed: that the `fetch_url` signature changes; the legacy seam keeps its shape.
- Not claimed: that every injected fetcher must accept policy arguments. An injected callable that already binds policy is left alone.
- Not claimed: any behaviour for a plan with no URL query.

## Acceptance

- An accepted URL plan executes with the default transport without raising TypeError.
- The fetch it performs applies the configured allowlist and the any-public and named-host exemptions.
- A hermetic test runs a URL plan through the default path with a stubbed transport and asserts the policy reached it.

Provenance: https://github.com/Treystu/harness/pull/669#discussion_r4658925851

