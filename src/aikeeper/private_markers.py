from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aikeeper.settings import app_home


VALID_SCOPES = {"company", "project"}


@dataclass(frozen=True)
class PrivateMarkerRule:
    rule_id: str
    scope: str
    reason: str
    pattern: re.Pattern[str]


def default_private_markers_path() -> Path:
    configured = os.environ.get("AIKEEPER_PRIVATE_MARKERS")
    if configured:
        return Path(configured).expanduser()
    return app_home() / "private-markers.toml"


def _rule_reason(scope: str) -> str:
    if scope == "company":
        return "contains a locally configured private company marker"
    return "contains a locally configured private project or machine marker"


def _compile_pattern(record: dict[str, Any]) -> re.Pattern[str]:
    flags = re.IGNORECASE if bool(record.get("ignore_case", True)) else 0
    literal = record.get("literal")
    regex = record.get("regex")
    if literal and regex:
        raise ValueError("private marker rule must define either literal or regex, not both")
    if literal:
        return re.compile(re.escape(str(literal)), flags)
    if regex:
        return re.compile(str(regex), flags)
    raise ValueError("private marker rule must define literal or regex")


def _normalize_rule(record: dict[str, Any]) -> PrivateMarkerRule:
    rule_id = str(record.get("id") or "").strip()
    if not rule_id:
        raise ValueError("private marker rule id is required")
    scope = str(record.get("scope") or "project").strip()
    if scope not in VALID_SCOPES:
        raise ValueError(f"private marker rule {rule_id!r} has unsupported scope {scope!r}")
    reason = str(record.get("reason") or _rule_reason(scope)).strip()
    return PrivateMarkerRule(rule_id=rule_id, scope=scope, reason=reason, pattern=_compile_pattern(record))


def _records_from_config(data: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    raw_rules = data.get("rules")
    if isinstance(raw_rules, list):
        records.extend(record for record in raw_rules if isinstance(record, dict))
    private_markers = data.get("private_markers")
    if isinstance(private_markers, dict):
        nested_rules = private_markers.get("rules")
        if isinstance(nested_rules, list):
            records.extend(record for record in nested_rules if isinstance(record, dict))
    return records


def load_private_marker_rules(path: Path | str | None = None) -> list[PrivateMarkerRule]:
    marker_path = Path(path).expanduser() if path is not None else default_private_markers_path()
    if not marker_path.exists():
        return []
    with marker_path.open("rb") as handle:
        data = tomllib.load(handle)
    return [_normalize_rule(record) for record in _records_from_config(data)]
