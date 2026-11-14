"""W0.5 (#510): generic OpenAI-compatible direct backends (Groq, Cerebras).

A model reaches a direct backend only when it is named by its Harness
namespace id (``groq/<wire>`` or ``cerebras/<wire>``) and that wire id has a
committed offer below. Every other model stays on its existing provider, so
no existing pool, panel, or apply lane changes dispatch because this module
exists. An id carrying a ``groq/`` or ``cerebras/`` prefix but no committed
offer fails closed: the prefix claims the direct lane, and an unpriced model
must never be routed on a guess or booked as free.

Prices are the providers' published per-token list rates (Nov 2026: Groq
``openai/gpt-oss-20b`` $0.075/$0.30, ``openai/gpt-oss-120b`` $0.15/$0.60
per 1M input/output; Cerebras ``gpt-oss-120b`` $0.35/$0.75, ``qwen-3-32b``
$0.40/$0.80 per 1M). The provider-reported
``usage.cost`` always wins; the committed rates only price a response that
carries token counts but no cost (exactly the Fireworks lane's rule), and a
response with neither is refused rather than booked as free.

Only Llama-namespace-free, currently self-serve wire ids are committed: the
Llama rows on both providers moved to Contact Sales/enterprise in Oct 2026,
so they cannot serve the laptop-local pool this module exists for.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from .config import (CEREBRAS_BASE_URL, CEREBRAS_MODEL_PREFIX,
                     CEREBRAS_PROVIDER, GROQ_BASE_URL, GROQ_MODEL_PREFIX,
                     GROQ_PROVIDER)
from .errors import HarnessError

#: Env names that override the default base URLs (no network at import or
#: config time; read when a call is dispatched).
GROQ_BASE_URL_ENV = "HARNESS_GROQ_BASE_URL"
CEREBRAS_BASE_URL_ENV = "HARNESS_CEREBRAS_BASE_URL"

#: OpenAI-compatible chat path appended to the base URL.
CHAT_COMPLETIONS_PATH = "/chat/completions"


@dataclass(frozen=True)
class DirectOffer:
    """One committed direct-backend offer for one namespaced model id."""

    model: str       # Harness id, e.g. "groq/openai/gpt-oss-120b"
    wire: str        # provider-native id posted on the wire
    provider: str    # GROQ_PROVIDER or CEREBRAS_PROVIDER
    prompt: float    # USD per input token
    completion: float  # USD per output token


def _offer(model, wire, provider, input_per_mtok, output_per_mtok):
    return DirectOffer(model, wire, provider,
                       float(input_per_mtok) / 1_000_000.0,
                       float(output_per_mtok) / 1_000_000.0)


#: Committed Groq offers, cheapest first (provider list rates, Nov 2026).
#: ``groq/qwen/qwen3-32b`` was removed (#523): it is absent from the
#: account's live model list, so it 404s. Its served replacement
#: (``qwen/qwen3.8-27b``) has no committed list rate, and an id without a
#: committed offer is excluded, never priced on a guess -- it rejoins the
#: pool only with a committed rate.
GROQ_OFFERS = {
    "groq/openai/gpt-oss-20b": _offer(
        "groq/openai/gpt-oss-20b", "openai/gpt-oss-20b", GROQ_PROVIDER,
        0.075, 0.30),
    "groq/openai/gpt-oss-120b": _offer(
        "groq/openai/gpt-oss-120b", "openai/gpt-oss-120b", GROQ_PROVIDER,
        0.15, 0.60),
}

#: Committed Cerebras offers, cheapest first (provider list rates, Nov 2026).
CEREBRAS_OFFERS = {
    "cerebras/gpt-oss-120b": _offer(
        "cerebras/gpt-oss-120b", "gpt-oss-120b", CEREBRAS_PROVIDER,
        0.35, 0.75),
    "cerebras/qwen-3-32b": _offer(
        "cerebras/qwen-3-32b", "qwen-3-32b", CEREBRAS_PROVIDER,
        0.40, 0.80),
}


def provider_for(model):
    """The direct backend a namespaced id names, else raise (fail closed)."""
    if isinstance(model, str) and model.startswith(GROQ_MODEL_PREFIX):
        return GROQ_PROVIDER
    if isinstance(model, str) and model.startswith(CEREBRAS_MODEL_PREFIX):
        return CEREBRAS_PROVIDER
    raise HarnessError(f"model '{model}' names no direct backend")


def resolve_offer(model):
    """The committed direct offer for a namespaced id, else raise.

    An unknown wire id under a known prefix is refused -- the prefix claims
    the direct lane, so falling back to another provider would silently move
    a pinned model, and guessing a price would silently misbill it.
    """
    offers = None
    if isinstance(model, str) and model.startswith(GROQ_MODEL_PREFIX):
        offers = GROQ_OFFERS
    elif isinstance(model, str) and model.startswith(CEREBRAS_MODEL_PREFIX):
        offers = CEREBRAS_OFFERS
    else:
        raise HarnessError(f"model '{model}' names no direct backend")
    offer = offers.get(model)
    if offer is None:
        raise HarnessError(f"no committed direct endpoint for '{model}'")
    return offer


def wire_model(model):
    """The provider-native id posted on the wire for a namespaced id."""
    return resolve_offer(model).wire


def base_url_for(model):
    """The base URL a namespaced id dispatches to (env override wins)."""
    provider = provider_for(model)
    if provider == GROQ_PROVIDER:
        return (os.environ.get(GROQ_BASE_URL_ENV) or GROQ_BASE_URL).rstrip("/")
    return (os.environ.get(CEREBRAS_BASE_URL_ENV)
            or CEREBRAS_BASE_URL).rstrip("/")


def chat_url_for(model):
    """The full chat-completions URL a namespaced id dispatches to."""
    return base_url_for(model) + CHAT_COMPLETIONS_PATH


def cost_estimate(offer, prompt_tokens, completion_tokens):
    """Estimated USD from the offer's per-token list rates.

    Cached input is billed at the full input rate here, so the estimate is
    an upper bound on the prompt side (the Fireworks lane's rule).
    """
    return (float(prompt_tokens) * offer.prompt
            + float(completion_tokens) * offer.completion)
