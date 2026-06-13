from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


LIMIT_DEFINITIONS = {
    "project_daily_usd": {"scope": "project", "label": "project daily USD", "unit": "usd"},
    "project_daily_tokens": {"scope": "project", "label": "project daily tokens", "unit": "tokens"},
    "task_daily_usd": {"scope": "task", "label": "task daily USD", "unit": "usd"},
    "task_daily_tokens": {"scope": "task", "label": "task daily tokens", "unit": "tokens"},
    "session_usd": {"scope": "session", "label": "session USD", "unit": "usd"},
    "session_tokens": {"scope": "session", "label": "session tokens", "unit": "tokens"},
    "turn_usd": {"scope": "turn", "label": "turn USD", "unit": "usd"},
    "turn_tokens": {"scope": "turn", "label": "turn tokens", "unit": "tokens"},
}


@dataclass(frozen=True)
class BudgetConfig:
    configured: bool
    source_path: str | None
    warn_at: float
    limits: dict[str, float]


def _positive_number(value: object) -> float | None:
    if isinstance(value, int | float) and value > 0:
        return float(value)
    return None


def load_budget_config(path: Path | str | None) -> BudgetConfig:
    if not path:
        return BudgetConfig(configured=False, source_path=None, warn_at=0.8, limits={})
    config_path = Path(path).expanduser()
    if not config_path.exists():
        return BudgetConfig(configured=False, source_path=str(config_path), warn_at=0.8, limits={})

    with config_path.open("rb") as handle:
        data = tomllib.load(handle)
    defaults = data.get("defaults") if isinstance(data.get("defaults"), dict) else {}
    warn_at = _positive_number(defaults.get("warn_at")) or 0.8
    limits = {}
    for key in LIMIT_DEFINITIONS:
        limit = _positive_number(defaults.get(key))
        if limit is not None:
            limits[key] = limit
    return BudgetConfig(configured=bool(limits), source_path=str(config_path), warn_at=warn_at, limits=limits)


def budget_state(config: BudgetConfig) -> dict:
    return {
        "configured": config.configured,
        "source_path": config.source_path,
        "warn_at": config.warn_at,
        "limits": config.limits,
    }


def evaluate_budget_warnings(values: dict[str, float | int], config: BudgetConfig) -> list[dict]:
    if not config.configured:
        return []

    warnings = []
    for key, limit in config.limits.items():
        used = float(values.get(key, 0) or 0)
        if used <= 0:
            continue
        ratio = used / limit
        if ratio < config.warn_at:
            continue
        definition = LIMIT_DEFINITIONS[key]
        warnings.append(
            {
                "key": key,
                "scope": definition["scope"],
                "label": definition["label"],
                "unit": definition["unit"],
                "used": round(used, 6),
                "limit": round(limit, 6),
                "ratio": round(ratio, 6),
                "warn_at": config.warn_at,
                "severity": "over" if ratio >= 1 else "near",
            }
        )
    return sorted(warnings, key=lambda warning: (warning["severity"] == "over", warning["ratio"]), reverse=True)
