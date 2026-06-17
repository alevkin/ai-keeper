from __future__ import annotations

from dataclasses import dataclass


PRICING_SOURCE_URL = "https://platform.claude.com/docs/en/about-claude/pricing"
PRICING_SOURCE_LABEL = "Bundled OpenAI and Anthropic API token rates, USD per 1M tokens"
PRICING_RETRIEVED_DATE = "2026-06-17"


@dataclass(frozen=True)
class ModelPrice:
    model: str
    input_per_million: float
    cached_input_per_million: float | None
    output_per_million: float
    cache_creation_per_million: float | None = None
    cache_creation_1h_per_million: float | None = None
    input_includes_cached_tokens: bool = True
    currency: str = "usd"


STANDARD_TOKEN_PRICES: dict[str, ModelPrice] = {
    "gpt-5.5": ModelPrice("gpt-5.5", input_per_million=5.00, cached_input_per_million=0.50, output_per_million=30.00),
    "gpt-5.5-pro": ModelPrice("gpt-5.5-pro", input_per_million=30.00, cached_input_per_million=None, output_per_million=180.00),
    "gpt-5.4": ModelPrice("gpt-5.4", input_per_million=2.50, cached_input_per_million=0.25, output_per_million=15.00),
    "gpt-5.4-mini": ModelPrice("gpt-5.4-mini", input_per_million=0.75, cached_input_per_million=0.075, output_per_million=4.50),
    "gpt-5.4-nano": ModelPrice("gpt-5.4-nano", input_per_million=0.20, cached_input_per_million=0.02, output_per_million=1.25),
    "gpt-5.4-pro": ModelPrice("gpt-5.4-pro", input_per_million=30.00, cached_input_per_million=None, output_per_million=180.00),
    "gpt-5.3-codex": ModelPrice("gpt-5.3-codex", input_per_million=1.75, cached_input_per_million=0.175, output_per_million=14.00),
    "chat-latest": ModelPrice("chat-latest", input_per_million=5.00, cached_input_per_million=0.50, output_per_million=30.00),
    "claude-fable-5": ModelPrice(
        "claude-fable-5",
        input_per_million=10.00,
        cached_input_per_million=1.00,
        cache_creation_per_million=12.50,
        cache_creation_1h_per_million=20.00,
        output_per_million=50.00,
        input_includes_cached_tokens=False,
    ),
    "claude-mythos-5": ModelPrice(
        "claude-mythos-5",
        input_per_million=10.00,
        cached_input_per_million=1.00,
        cache_creation_per_million=12.50,
        cache_creation_1h_per_million=20.00,
        output_per_million=50.00,
        input_includes_cached_tokens=False,
    ),
    "claude-opus-4-8": ModelPrice(
        "claude-opus-4-8",
        input_per_million=5.00,
        cached_input_per_million=0.50,
        cache_creation_per_million=6.25,
        cache_creation_1h_per_million=10.00,
        output_per_million=25.00,
        input_includes_cached_tokens=False,
    ),
    "claude-opus-4-7": ModelPrice(
        "claude-opus-4-7",
        input_per_million=5.00,
        cached_input_per_million=0.50,
        cache_creation_per_million=6.25,
        cache_creation_1h_per_million=10.00,
        output_per_million=25.00,
        input_includes_cached_tokens=False,
    ),
    "claude-opus-4-6": ModelPrice(
        "claude-opus-4-6",
        input_per_million=5.00,
        cached_input_per_million=0.50,
        cache_creation_per_million=6.25,
        cache_creation_1h_per_million=10.00,
        output_per_million=25.00,
        input_includes_cached_tokens=False,
    ),
    "claude-opus-4-5": ModelPrice(
        "claude-opus-4-5",
        input_per_million=5.00,
        cached_input_per_million=0.50,
        cache_creation_per_million=6.25,
        cache_creation_1h_per_million=10.00,
        output_per_million=25.00,
        input_includes_cached_tokens=False,
    ),
    "claude-sonnet-4-6": ModelPrice(
        "claude-sonnet-4-6",
        input_per_million=3.00,
        cached_input_per_million=0.30,
        cache_creation_per_million=3.75,
        cache_creation_1h_per_million=6.00,
        output_per_million=15.00,
        input_includes_cached_tokens=False,
    ),
    "claude-sonnet-4-5": ModelPrice(
        "claude-sonnet-4-5",
        input_per_million=3.00,
        cached_input_per_million=0.30,
        cache_creation_per_million=3.75,
        cache_creation_1h_per_million=6.00,
        output_per_million=15.00,
        input_includes_cached_tokens=False,
    ),
    "claude-sonnet-4": ModelPrice(
        "claude-sonnet-4",
        input_per_million=3.00,
        cached_input_per_million=0.30,
        cache_creation_per_million=3.75,
        cache_creation_1h_per_million=6.00,
        output_per_million=15.00,
        input_includes_cached_tokens=False,
    ),
    "claude-haiku-4-5": ModelPrice(
        "claude-haiku-4-5",
        input_per_million=1.00,
        cached_input_per_million=0.10,
        cache_creation_per_million=1.25,
        cache_creation_1h_per_million=2.00,
        output_per_million=5.00,
        input_includes_cached_tokens=False,
    ),
}

MODEL_ALIASES: dict[str, str] = {
    "claude-fable-5-20260612": "claude-fable-5",
    "claude-mythos-5-20260612": "claude-mythos-5",
    "claude-opus-4-8-20260604": "claude-opus-4-8",
    "claude-opus-4-7-20260414": "claude-opus-4-7",
    "claude-opus-4-6-20260224": "claude-opus-4-6",
    "claude-opus-4-5-20251101": "claude-opus-4-5",
    "claude-sonnet-4-6-20260224": "claude-sonnet-4-6",
    "claude-sonnet-4-5-20250929": "claude-sonnet-4-5",
    "claude-sonnet-4-20250514": "claude-sonnet-4",
    "claude-haiku-4-5-20251001": "claude-haiku-4-5",
}


def price_for_model(model: str | None) -> ModelPrice | None:
    if not model:
        return None
    key = MODEL_ALIASES.get(model, model)
    return STANDARD_TOKEN_PRICES.get(key)


def estimate_event_cost_usd(
    model: str | None,
    *,
    input_tokens: int,
    cached_input_tokens: int,
    cache_creation_input_tokens: int = 0,
    cache_creation_1h_input_tokens: int = 0,
    output_tokens: int,
) -> float | None:
    price = price_for_model(model)
    if not price:
        return None

    input_total = max(input_tokens, 0)
    cached = max(cached_input_tokens, 0)
    cache_creation_5m = max(cache_creation_input_tokens, 0)
    cache_creation_1h = max(cache_creation_1h_input_tokens, 0)
    if price.input_includes_cached_tokens:
        cached = min(cached, input_total)
        uncached_input = max(input_total - cached, 0)
    else:
        uncached_input = input_total
    cached_rate = price.cached_input_per_million
    if cached_rate is None:
        cached_rate = price.input_per_million
    cache_creation_rate = price.cache_creation_per_million
    if cache_creation_rate is None:
        cache_creation_rate = price.input_per_million
    cache_creation_1h_rate = price.cache_creation_1h_per_million
    if cache_creation_1h_rate is None:
        cache_creation_1h_rate = cache_creation_rate

    return (
        (uncached_input * price.input_per_million)
        + (cached * cached_rate)
        + (cache_creation_5m * cache_creation_rate)
        + (cache_creation_1h * cache_creation_1h_rate)
        + (max(output_tokens, 0) * price.output_per_million)
    ) / 1_000_000
