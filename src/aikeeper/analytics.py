from __future__ import annotations

from aikeeper.pricing import estimate_event_cost_usd


def _event_int(event, key: str) -> int:
    try:
        return int(event[key] or 0)
    except (KeyError, TypeError, ValueError):
        return 0


def event_cost_usd(event, model: str | None) -> float | None:
    return estimate_event_cost_usd(
        model,
        input_tokens=_event_int(event, "input_tokens"),
        cached_input_tokens=_event_int(event, "cached_input_tokens"),
        cache_creation_input_tokens=_event_int(event, "cache_creation_input_tokens"),
        cache_creation_1h_input_tokens=_event_int(event, "cache_creation_1h_input_tokens"),
        output_tokens=_event_int(event, "output_tokens"),
    )


def _ratio(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator), 6)


def context_health(events: list, model: str | None = None) -> dict:
    if not events:
        return {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "cached_input_ratio": 0.0,
            "input_growth_ratio": 0.0,
            "cache_regression": False,
            "recommendation": "No token events imported yet.",
        }

    input_tokens = sum(_event_int(event, "input_tokens") for event in events)
    cached = sum(_event_int(event, "cached_input_tokens") for event in events)
    cache_creation = sum(
        _event_int(event, "cache_creation_input_tokens") + _event_int(event, "cache_creation_1h_input_tokens")
        for event in events
    )
    output = sum(_event_int(event, "output_tokens") for event in events)

    def cache_denominator(event) -> int:
        base = _event_int(event, "input_tokens")
        read = _event_int(event, "cached_input_tokens")
        write = _event_int(event, "cache_creation_input_tokens") + _event_int(event, "cache_creation_1h_input_tokens")
        return base + write + read if write or read > base else base

    first_input = max(cache_denominator(events[0]), 1)
    last_input = cache_denominator(events[-1])
    first_ratio = _ratio(_event_int(events[0], "cached_input_tokens"), cache_denominator(events[0]))
    last_ratio = _ratio(_event_int(events[-1], "cached_input_tokens"), cache_denominator(events[-1]))
    growth = round(last_input / first_input, 6)
    cache_regression = first_ratio >= 0.2 and last_ratio < first_ratio * 0.5
    cached_denominator = input_tokens + cache_creation
    if cache_creation or cached > input_tokens:
        cached_denominator += cached
    cached_ratio = _ratio(cached, cached_denominator)
    if growth >= 4 or cached_ratio < 0.2 or cache_regression:
        recommendation = "Consider compaction or a fresh session; context is growing and cache health is weak."
    else:
        recommendation = "Context looks healthy."
    return {
        "model": model,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached,
        "cache_creation_input_tokens": cache_creation,
        "output_tokens": output,
        "cached_input_ratio": cached_ratio,
        "first_input_tokens": first_input,
        "last_input_tokens": last_input,
        "input_growth_ratio": growth,
        "cache_regression": cache_regression,
        "recommendation": recommendation,
    }


def detect_session_anomalies(events: list, model: str | None) -> list[dict]:
    anomalies = []
    previous_cost = None
    previous_cache_ratio = None
    for event in events:
        sequence = int(event["sequence"])
        total_tokens = int(event["total_tokens"])
        input_tokens = _event_int(event, "input_tokens")
        cache_denominator = input_tokens + _event_int(event, "cache_creation_input_tokens") + _event_int(event, "cache_creation_1h_input_tokens")
        if _event_int(event, "cached_input_tokens") > input_tokens:
            cache_denominator += _event_int(event, "cached_input_tokens")
        cache_ratio = _ratio(_event_int(event, "cached_input_tokens"), cache_denominator or input_tokens)
        cost = event_cost_usd(event, model)

        if total_tokens >= 100_000:
            anomalies.append(
                {
                    "sequence": sequence,
                    "severity": "high",
                    "reason": "large turn",
                    "detail": f"Turn used {total_tokens:,} tokens.",
                }
            )
        if previous_cache_ratio is not None and previous_cache_ratio >= 0.2 and cache_ratio < previous_cache_ratio * 0.5:
            anomalies.append(
                {
                    "sequence": sequence,
                    "severity": "medium",
                    "reason": "cache regression",
                    "detail": f"Cached input ratio fell from {previous_cache_ratio:.1%} to {cache_ratio:.1%}.",
                }
            )
        if cost is not None and previous_cost is not None and cost >= 0.01 and cost > previous_cost * 2:
            anomalies.append(
                {
                    "sequence": sequence,
                    "severity": "medium",
                    "reason": "cost jump",
                    "detail": f"Turn estimate rose from ${previous_cost:.2f} to ${cost:.2f}.",
                }
            )
        if cost is not None:
            previous_cost = cost
        previous_cache_ratio = cache_ratio
    return anomalies


def simulate_cost_rows(rows: list, target_model: str) -> dict:
    actual = 0.0
    target = 0.0
    actual_unpriced = set()
    target_unpriced = False
    for row in rows:
        actual_cost = event_cost_usd(row, row["model"])
        if actual_cost is None:
            actual_unpriced.add(str(row["model"] or "unknown"))
        else:
            actual += actual_cost
        target_cost = event_cost_usd(row, target_model)
        if target_cost is None:
            target_unpriced = True
        else:
            target += target_cost
    return {
        "target_model": target_model,
        "event_count": len(rows),
        "actual_estimated_cost_usd": round(actual, 6),
        "target_estimated_cost_usd": round(target, 6),
        "estimated_savings_usd": round(actual - target, 6),
        "actual_unpriced_models": sorted(actual_unpriced),
        "target_unpriced": target_unpriced,
    }
