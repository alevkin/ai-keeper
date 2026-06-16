from __future__ import annotations

from pathlib import Path
import json
import os
from datetime import UTC, datetime

import httpx

from aikeeper.codex import sync_codex_once
from aikeeper.service import status_for_cwd
from aikeeper.settings import DEFAULT_HOST, DEFAULT_PORT, app_home
from aikeeper.settings import codex_home as default_codex_home
from aikeeper.settings import default_db_path


def _record_hook_event(payload: dict, result: dict) -> None:
    event_path = app_home() / "hook-events.jsonl"
    record = {
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "event": payload.get("hook_event_name"),
        "session_id": payload.get("session_id"),
        "cwd": payload.get("cwd"),
        "transcript_path": payload.get("transcript_path"),
        "result_keys": sorted(result.keys()),
    }
    try:
        event_path.parent.mkdir(parents=True, exist_ok=True)
        with event_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError:
        return


def _tokens(value: int) -> str:
    return f"{value:,} tokens"


def _usd(value: float | None) -> str:
    amount = float(value or 0)
    if 0 < abs(amount) < 0.01:
        return f"${amount:,.4f}"
    return f"${amount:,.2f}"


def _tokens_with_cost(tokens: int, cost: float | None = None) -> str:
    text = _tokens(tokens)
    if cost is not None:
        text += f" ({_usd(cost)} est.)"
    return text


def _budget_value(value: float | int, unit: str) -> str:
    if unit == "usd":
        return _usd(float(value))
    return _tokens(int(value))


def _budget_fragment(warnings: list[dict] | None) -> str:
    if not warnings:
        return ""
    warning = warnings[0]
    return (
        f" | budget {warning['severity']}: {warning['label']} "
        f"{_budget_value(warning['used'], warning['unit'])}/{_budget_value(warning['limit'], warning['unit'])}"
    )


def _dashboard_candidates() -> list[str]:
    configured = os.environ.get("AIKEEPER_DASHBOARD_URL")
    urls = [configured.rstrip("/")] if configured else []
    urls.extend(f"http://{DEFAULT_HOST}:{port}" for port in range(DEFAULT_PORT, DEFAULT_PORT + 6))
    return list(dict.fromkeys(urls))


def _find_dashboard_url() -> str | None:
    for url in _dashboard_candidates():
        try:
            response = httpx.get(f"{url}/api/ping", timeout=0.25)
            data = response.json() if response.status_code == 200 else {}
        except (httpx.HTTPError, ValueError):
            data = {}
        if isinstance(data, dict) and data.get("service") == "aikeeper":
            return url
        try:
            response = httpx.get(f"{url}/api/overview", timeout=0.5)
            data = response.json() if response.status_code == 200 else {}
        except (httpx.HTTPError, ValueError):
            continue
        if isinstance(data, dict) and "total_tokens" in data:
            return url
    return None


def _summary(status: dict, dashboard_url: str | None = None) -> str:
    line = (
        f"> **AI Keeper** | turn {_tokens_with_cost(status['session']['last_turn_tokens'], status['session'].get('last_turn_cost_usd'))} | "
        f"session {_tokens_with_cost(status['session']['total_tokens'], status['session'].get('estimated_cost_usd'))} | "
        f"task today {_tokens(status['task']['today_tokens'])} | "
        f"project today {_tokens(status['project']['today_tokens'])}"
    )
    if dashboard_url:
        line += f" | [dashboard]({dashboard_url})"
    line += _budget_fragment(status.get("budget_warnings"))
    return line


def _prompt_context(status: dict) -> str:
    return (
        "AI Keeper usage context is metadata-only and contains no prompt or transcript text. "
        "Append this exact line as a short separate line in your response when it is relevant "
        f"to show local Codex usage: {_summary(status, dashboard_url=_find_dashboard_url())}"
    )


def handle_codex_hook(
    payload: dict,
    *,
    db_path: Path | str | None = None,
    codex_home: Path | str | None = None,
) -> dict:
    db = Path(db_path).expanduser() if db_path else default_db_path()
    home = Path(codex_home).expanduser() if codex_home else default_codex_home()
    safe_context = {key: value for key, value in payload.items() if key != "prompt"}
    event_name = payload.get("hook_event_name")
    hook_context = safe_context
    if event_name == "UserPromptSubmit" and not safe_context.get("transcript_path"):
        hook_context = None
    sync_codex_once(
        db_path=db,
        codex_home=home,
        transcript_path=safe_context.get("transcript_path"),
        hook_context=hook_context,
    )

    if event_name == "Stop":
        status = status_for_cwd(db, Path(str(payload.get("cwd") or Path.cwd())))
        result = {"continue": True, "systemMessage": _summary(status, dashboard_url=_find_dashboard_url())}
        _record_hook_event(safe_context, result)
        return result
    if event_name == "UserPromptSubmit":
        status = status_for_cwd(db, Path(str(payload.get("cwd") or Path.cwd())))
        result = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": _prompt_context(status),
            }
        }
        _record_hook_event(safe_context, result)
        return result
    result = {}
    _record_hook_event(safe_context, result)
    return result
