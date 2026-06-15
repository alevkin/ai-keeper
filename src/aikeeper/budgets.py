from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib

from aikeeper.db import connect, init_db
from aikeeper.timeutils import now_ms as current_now_ms


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
    task_limits: dict[str, dict[str, float]]


def _positive_number(value: object) -> float | None:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            value = float(stripped)
        except ValueError:
            return None
    if isinstance(value, int | float) and value > 0:
        return float(value)
    return None


def load_budget_config(path: Path | str | None) -> BudgetConfig:
    if not path:
        return BudgetConfig(configured=False, source_path=None, warn_at=0.8, limits={}, task_limits={})
    config_path = Path(path).expanduser()
    if not config_path.exists():
        return BudgetConfig(configured=False, source_path=str(config_path), warn_at=0.8, limits={}, task_limits={})

    with config_path.open("rb") as handle:
        data = tomllib.load(handle)
    defaults = data.get("defaults") if isinstance(data.get("defaults"), dict) else {}
    warn_at = _positive_number(defaults.get("warn_at")) or 0.8
    limits = {}
    for key in LIMIT_DEFINITIONS:
        limit = _positive_number(defaults.get(key))
        if limit is not None:
            limits[key] = limit
    task_limits = {}
    tasks = data.get("tasks") if isinstance(data.get("tasks"), dict) else {}
    for task_key, raw in tasks.items():
        if not isinstance(raw, dict):
            continue
        task_values = {}
        for key in LIMIT_DEFINITIONS:
            limit = _positive_number(raw.get(key))
            if limit is not None:
                task_values[key] = limit
        if task_values:
            task_limits[str(task_key)] = task_values
    return BudgetConfig(
        configured=bool(limits or task_limits),
        source_path=str(config_path),
        warn_at=warn_at,
        limits=limits,
        task_limits=task_limits,
    )


def load_budget_config_from_db(db_path: Path | str) -> BudgetConfig:
    with connect(db_path) as con:
        init_db(con)
        rows = con.execute("select * from budget_settings order by scope asc, scope_key asc").fetchall()

    defaults = next((row for row in rows if row["scope"] == "defaults" and row["scope_key"] == ""), None)
    warn_at = _positive_number(defaults["warn_at"] if defaults else None) or 0.8
    limits = _limits_from_row(defaults) if defaults else {}
    task_limits = {}
    for row in rows:
        if row["scope"] != "task" or not row["scope_key"]:
            continue
        values = _limits_from_row(row)
        if values:
            task_limits[str(row["scope_key"])] = values
    return BudgetConfig(
        configured=bool(limits or task_limits),
        source_path="sqlite",
        warn_at=warn_at,
        limits=limits,
        task_limits=task_limits,
    )


def save_budget_settings(
    db_path: Path | str,
    *,
    scope: str,
    scope_key: str = "",
    warn_at: object = None,
    limits: dict[str, object] | None = None,
) -> BudgetConfig:
    if scope not in {"defaults", "task"}:
        raise ValueError("scope must be defaults or task")
    key = "" if scope == "defaults" else str(scope_key or "").strip()
    if scope == "task" and not key:
        raise ValueError("task budget settings require task_key")
    clean_limits = _clean_limits(limits or {})
    warn_value = _positive_number(warn_at) if scope == "defaults" else None
    if scope == "defaults" and warn_value is None:
        warn_value = 0.8

    with connect(db_path) as con:
        init_db(con)
        if scope == "task" and not clean_limits:
            con.execute("delete from budget_settings where scope = ? and scope_key = ?", (scope, key))
        else:
            columns = ["scope", "scope_key", "warn_at", *LIMIT_DEFINITIONS, "updated_at_ms"]
            values = [scope, key, warn_value, *[clean_limits.get(name) for name in LIMIT_DEFINITIONS], current_now_ms()]
            placeholders = ", ".join("?" for _ in columns)
            updates = ", ".join(f"{column} = excluded.{column}" for column in columns[2:])
            con.execute(
                f"""
                insert into budget_settings({", ".join(columns)})
                values ({placeholders})
                on conflict(scope, scope_key) do update set {updates}
                """,
                values,
            )
        con.commit()
    return load_budget_config_from_db(db_path)


def budget_settings_state(config: BudgetConfig, task_key: str | None = None) -> dict:
    fields = []
    for key, definition in LIMIT_DEFINITIONS.items():
        fields.append(
            {
                "key": key,
                "label": definition["label"],
                "unit": definition["unit"],
                "step": "0.01" if definition["unit"] == "usd" else "1",
            }
        )
    current_task = None
    if task_key:
        task_key = str(task_key)
        current_task = {"task_key": task_key, "limits": config.task_limits.get(task_key, {})}
    return {
        "source": config.source_path,
        "limit_fields": fields,
        "defaults": {"warn_at": config.warn_at, "limits": config.limits},
        "current_task": current_task,
    }


def _clean_limits(values: dict[str, object]) -> dict[str, float]:
    clean = {}
    for key in LIMIT_DEFINITIONS:
        number = _positive_number(values.get(key))
        if number is not None:
            clean[key] = number
    return clean


def _limits_from_row(row) -> dict[str, float]:
    if row is None:
        return {}
    values = {}
    for key in LIMIT_DEFINITIONS:
        number = _positive_number(row[key])
        if number is not None:
            values[key] = number
    return values


def config_for_task(config: BudgetConfig, task_key: str | None) -> BudgetConfig:
    if not task_key:
        return config
    limits = {**config.limits, **config.task_limits.get(str(task_key), {})}
    return BudgetConfig(
        configured=bool(limits),
        source_path=config.source_path,
        warn_at=config.warn_at,
        limits=limits,
        task_limits=config.task_limits,
    )


def budget_state(config: BudgetConfig) -> dict:
    return {
        "configured": config.configured,
        "source_path": config.source_path,
        "warn_at": config.warn_at,
        "limits": config.limits,
        "task_limits": config.task_limits,
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
