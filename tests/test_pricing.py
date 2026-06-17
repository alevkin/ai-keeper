import pytest

from aikeeper.pricing import estimate_event_cost_usd, price_for_model


def test_estimates_gpt55_standard_short_context_cost() -> None:
    cost = estimate_event_cost_usd(
        "gpt-5.5",
        input_tokens=200,
        cached_input_tokens=50,
        output_tokens=100,
    )

    assert cost == pytest.approx(0.003775)


def test_unknown_model_has_no_estimate() -> None:
    assert price_for_model("unknown-model") is None
    assert estimate_event_cost_usd("unknown-model", input_tokens=100, cached_input_tokens=0, output_tokens=50) is None


def test_estimates_codex_specialized_model_cost() -> None:
    cost = estimate_event_cost_usd(
        "gpt-5.3-codex",
        input_tokens=1_000_000,
        cached_input_tokens=100_000,
        output_tokens=100_000,
    )

    assert cost == pytest.approx(2.9925)


def test_estimates_claude_sonnet_cache_read_and_write_cost() -> None:
    cost = estimate_event_cost_usd(
        "claude-sonnet-4-6",
        input_tokens=3,
        cached_input_tokens=17_946,
        cache_creation_input_tokens=7_000,
        cache_creation_1h_input_tokens=241,
        output_tokens=8,
    )

    expected = ((3 * 3.00) + (17_946 * 0.30) + (7_000 * 3.75) + (241 * 6.00) + (8 * 15.00)) / 1_000_000
    assert cost == pytest.approx(expected)


def test_estimates_bedrock_converse_claude_alias_cost() -> None:
    cost = estimate_event_cost_usd(
        "converse/us.anthropic.claude-haiku-4-5-20251001-v1:0",
        input_tokens=100,
        cached_input_tokens=200,
        cache_creation_input_tokens=300,
        output_tokens=50,
    )

    expected = ((100 * 1.00) + (200 * 0.10) + (300 * 1.25) + (50 * 5.00)) / 1_000_000
    assert cost == pytest.approx(expected)
