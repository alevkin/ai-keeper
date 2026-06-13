from __future__ import annotations

from dataclasses import dataclass


PRICING_SOURCE_URL = "https://developers.openai.com/api/docs/pricing"
PRICING_SOURCE_LABEL = "OpenAI API pricing, Standard token rates, USD per 1M tokens"
PRICING_RETRIEVED_DATE = "2026-06-13"


@dataclass(frozen=True)
class ModelPrice:
    model: str
    input_per_million: float
    cached_input_per_million: float | None
    output_per_million: float
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
}


def price_for_model(model: str | None) -> ModelPrice | None:
    if not model:
        return None
    return STANDARD_TOKEN_PRICES.get(model)


def estimate_event_cost_usd(
    model: str | None,
    *,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
) -> float | None:
    price = price_for_model(model)
    if not price:
        return None

    cached = min(max(cached_input_tokens, 0), max(input_tokens, 0))
    uncached_input = max(input_tokens - cached, 0)
    cached_rate = price.cached_input_per_million
    if cached_rate is None:
        cached_rate = price.input_per_million

    return (
        (uncached_input * price.input_per_million)
        + (cached * cached_rate)
        + (max(output_tokens, 0) * price.output_per_million)
    ) / 1_000_000
