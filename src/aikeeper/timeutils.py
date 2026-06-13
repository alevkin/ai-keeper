from __future__ import annotations

from datetime import UTC, datetime, time


def now_ms() -> int:
    return int(datetime.now(tz=UTC).timestamp() * 1000)


def parse_timestamp_ms(value: str | None) -> int:
    if not value:
        return now_ms()
    normalized = value.replace("Z", "+00:00")
    return int(datetime.fromisoformat(normalized).timestamp() * 1000)


def utc_day_start_ms(value_ms: int) -> int:
    dt = datetime.fromtimestamp(value_ms / 1000, tz=UTC)
    start = datetime.combine(dt.date(), time.min, tzinfo=UTC)
    return int(start.timestamp() * 1000)


def utc_week_start_ms(value_ms: int) -> int:
    dt = datetime.fromtimestamp(value_ms / 1000, tz=UTC)
    start_date = dt.date()
    start_date = start_date.fromordinal(start_date.toordinal() - start_date.weekday())
    start = datetime.combine(start_date, time.min, tzinfo=UTC)
    return int(start.timestamp() * 1000)
