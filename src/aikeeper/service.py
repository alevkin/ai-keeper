from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from statistics import median

from aikeeper.analytics import context_health, detect_session_anomalies, simulate_cost_rows
from aikeeper.audit import audit_privacy
from aikeeper.budgets import (
    budget_settings_state,
    budget_state,
    config_for_task,
    evaluate_budget_warnings,
    load_budget_config,
    load_budget_config_from_db,
)
from aikeeper.db import connect, init_db
from aikeeper.gitmeta import get_git_metadata, task_identity
from aikeeper.health import ingest_health
from aikeeper.pricing import PRICING_RETRIEVED_DATE, PRICING_SOURCE_LABEL, PRICING_SOURCE_URL, estimate_event_cost_usd
from aikeeper.timeutils import now_ms as current_now_ms
from aikeeper.timeutils import utc_day_start_ms, utc_week_start_ms


ACTIVE_WINDOW_MS = 600_000
IDLE_GAP_MS = 120_000
BURN_TREND_BUCKET_MS = 60_000
BURN_TREND_BUCKETS = ACTIVE_WINDOW_MS // BURN_TREND_BUCKET_MS
ECONOMICS_PROJECTION_MINUTES = 30


def _sum_tokens_since(con, session_filter: str, params: tuple, since_ms: int) -> int:
    row = con.execute(
        f"""
        select coalesce(sum(te.total_tokens), 0) as tokens
        from token_events te
        join sessions s on s.id = te.session_pk
        where {session_filter} and te.timestamp_ms >= ?
        """,
        (*params, since_ms),
    ).fetchone()
    return int(row["tokens"])


def _sum_tokens_between(con, start_ms: int, end_ms: int) -> int:
    row = con.execute(
        """
        select coalesce(sum(total_tokens), 0) as tokens
        from token_events
        where timestamp_ms >= ? and timestamp_ms < ?
        """,
        (start_ms, end_ms),
    ).fetchone()
    return int(row["tokens"])


def _row_int(row, key: str) -> int:
    try:
        return int(row[key] or 0)
    except (KeyError, TypeError, ValueError):
        return 0


def _estimate_rows_cost(rows) -> dict:
    total = 0.0
    unpriced: set[str] = set()
    for row in rows:
        cost = estimate_event_cost_usd(
            row["model"],
            input_tokens=_row_int(row, "input_tokens"),
            cached_input_tokens=_row_int(row, "cached_input_tokens"),
            cache_creation_input_tokens=_row_int(row, "cache_creation_input_tokens"),
            cache_creation_1h_input_tokens=_row_int(row, "cache_creation_1h_input_tokens"),
            output_tokens=_row_int(row, "output_tokens"),
        )
        if cost is None:
            unpriced.add(str(row["model"] or "unknown"))
            continue
        total += cost
    return {"usd": round(total, 6), "unpriced_models": sorted(unpriced)}


def _active_ms(rows, idle_gap_ms: int = IDLE_GAP_MS) -> int:
    timestamps = sorted({int(row["timestamp_ms"]) for row in rows})
    if len(timestamps) < 2:
        return 0
    active = 0
    for previous, current in zip(timestamps, timestamps[1:]):
        delta = max(current - previous, 0)
        active += min(delta, idle_gap_ms)
    return active


def _per_minute(value: int | float, active_ms: int) -> float:
    if active_ms <= 0:
        return 0.0
    return round(float(value) * 60_000 / active_ms, 6)


def _burn_rate_trend(rows, now_ms: int) -> dict:
    bucket_ms = BURN_TREND_BUCKET_MS
    bucket_count = BURN_TREND_BUCKETS
    window_start = now_ms - bucket_ms * bucket_count
    points = []
    for index in range(bucket_count):
        start = window_start + index * bucket_ms
        end = start + bucket_ms
        bucket_rows = [
            row
            for row in rows
            if start <= int(row["timestamp_ms"]) < end
            or (index == bucket_count - 1 and int(row["timestamp_ms"]) == now_ms)
        ]
        tokens = sum(int(row["total_tokens"]) for row in bucket_rows)
        cost = _estimate_rows_cost(bucket_rows)["usd"] if bucket_rows else 0.0
        elapsed_ms = min(bucket_ms, max(now_ms - start, 0))
        duration_ms = max(elapsed_ms, 1)
        points.append(
            {
                "start_ms": start,
                "end_ms": min(end, now_ms),
                "tokens": tokens,
                "estimated_cost_usd": cost,
                "tokens_per_minute": _per_minute(tokens, duration_ms),
                "usd_per_minute": _per_minute(cost, duration_ms),
            }
        )

    split = bucket_count // 2
    previous = points[:split]
    recent = points[split:]
    previous_rate = sum(point["tokens_per_minute"] for point in previous) / len(previous) if previous else 0.0
    recent_rate = sum(point["tokens_per_minute"] for point in recent) / len(recent) if recent else 0.0
    delta = recent_rate - previous_rate
    delta_ratio = delta / previous_rate if previous_rate else (1.0 if recent_rate else 0.0)
    threshold = max(previous_rate * 0.05, 1.0)
    if delta > threshold:
        direction = "up"
    elif delta < -threshold:
        direction = "down"
    else:
        direction = "flat"
    return {
        "bucket_ms": bucket_ms,
        "points": points,
        "previous_tokens_per_minute": round(previous_rate, 6),
        "recent_tokens_per_minute": round(recent_rate, 6),
        "delta_tokens_per_minute": round(delta, 6),
        "delta_ratio": round(delta_ratio, 6),
        "direction": direction,
    }


def _estimate_cost(con, session_filter: str = "1 = 1", params: tuple = (), since_ms: int | None = None) -> dict:
    where = session_filter
    query_params = params
    if since_ms is not None:
        where = f"{where} and te.timestamp_ms >= ?"
        query_params = (*params, since_ms)
    rows = con.execute(
        f"""
        select s.model, te.input_tokens, te.cached_input_tokens,
               te.cache_creation_input_tokens, te.cache_creation_1h_input_tokens,
               te.output_tokens
        from token_events te
        join sessions s on s.id = te.session_pk
        where {where}
        """,
        query_params,
    ).fetchall()
    return _estimate_rows_cost(rows)


def _estimate_cost_between(con, start_ms: int, end_ms: int) -> dict:
    rows = con.execute(
        """
        select s.model, te.input_tokens, te.cached_input_tokens,
               te.cache_creation_input_tokens, te.cache_creation_1h_input_tokens,
               te.output_tokens
        from token_events te
        join sessions s on s.id = te.session_pk
        where te.timestamp_ms >= ? and te.timestamp_ms < ?
        """,
        (start_ms, end_ms),
    ).fetchall()
    return _estimate_rows_cost(rows)


def _date_label(day_start_ms: int) -> str:
    return datetime.fromtimestamp(day_start_ms / 1000, tz=UTC).date().isoformat()


def _daily_tokens(con, now_ms: int, days: int = 7) -> list[dict]:
    day_start = utc_day_start_ms(now_ms)
    day_ms = 86_400_000
    rows = []
    for index in range(days - 1, -1, -1):
        start = day_start - index * day_ms
        end = start + day_ms
        cost = _estimate_cost_between(con, start, end)
        rows.append({"date": _date_label(start), "tokens": _sum_tokens_between(con, start, end), "estimated_cost_usd": cost["usd"]})
    return rows


def _current_activity(con) -> dict | None:
    session = con.execute(
        """
        select s.id, s.provider, s.session_id, s.cwd, s.model, s.updated_at_ms, s.total_tokens,
               p.id as project_id, p.name as project_name, p.root_path,
               t.id as task_id, t.task_key, t.display_name as task_name,
               (
                   select te.total_tokens
                   from token_events te
                   where te.session_pk = s.id
                   order by te.sequence desc
                   limit 1
               ) as last_turn_tokens
        from sessions s
        join projects p on p.id = s.project_id
        join tasks t on t.id = s.task_id
        order by s.updated_at_ms desc, s.id desc
        limit 1
        """
    ).fetchone()
    if not session:
        return None
    data = dict(session)
    data["session_label"] = str(data["session_id"])[:8]
    data["last_turn_tokens"] = int(data["last_turn_tokens"] or 0)
    data["total_tokens"] = int(data["total_tokens"])
    session_cost = _estimate_cost(con, "s.id = ?", (data["id"],))
    data["estimated_cost_usd"] = session_cost["usd"]
    last_turn = con.execute(
        """
        select s.model, te.input_tokens, te.cached_input_tokens,
               te.cache_creation_input_tokens, te.cache_creation_1h_input_tokens,
               te.output_tokens
        from token_events te
        join sessions s on s.id = te.session_pk
        where te.session_pk = ?
        order by te.sequence desc
        limit 1
        """,
        (data["id"],),
    ).fetchall()
    data["last_turn_cost_usd"] = _estimate_rows_cost(last_turn)["usd"]
    return data


def _current_burn_rate(con, now_ms: int) -> dict:
    session = con.execute(
        """
        select id, session_id, model
        from sessions
        order by updated_at_ms desc, id desc
        limit 1
        """
    ).fetchone()
    empty = {
        "active_window_ms": ACTIVE_WINDOW_MS,
        "idle_gap_ms": IDLE_GAP_MS,
        "trend": _burn_rate_trend([], now_ms),
        "current": None,
    }
    if not session:
        return empty

    rows = con.execute(
        """
        select s.model, te.timestamp_ms, te.input_tokens, te.cached_input_tokens,
               te.cache_creation_input_tokens, te.cache_creation_1h_input_tokens,
               te.output_tokens, te.total_tokens
        from token_events te
        join sessions s on s.id = te.session_pk
        where te.session_pk = ? and te.timestamp_ms >= ?
        order by te.timestamp_ms asc, te.sequence asc
        """,
        (session["id"], now_ms - ACTIVE_WINDOW_MS),
    ).fetchall()
    if not rows:
        return empty

    tokens = sum(int(row["total_tokens"]) for row in rows)
    cost = _estimate_rows_cost(rows)["usd"]
    active = _active_ms(rows)
    return {
        "active_window_ms": ACTIVE_WINDOW_MS,
        "idle_gap_ms": IDLE_GAP_MS,
        "trend": _burn_rate_trend(rows, now_ms),
        "current": {
            "session_id": session["session_id"],
            "model": session["model"],
            "events": len(rows),
            "tokens": tokens,
            "estimated_cost_usd": cost,
            "active_ms": active,
            "tokens_per_minute": _per_minute(tokens, active),
            "usd_per_minute": _per_minute(cost, active),
        },
    }


def _model_efficiency(con) -> list[dict]:
    rows = con.execute(
        """
        select s.provider, coalesce(s.model, 'unknown') as model, s.id as session_pk,
               te.timestamp_ms, te.input_tokens, te.cached_input_tokens,
               te.cache_creation_input_tokens, te.cache_creation_1h_input_tokens,
               te.output_tokens, te.total_tokens
        from token_events te
        join sessions s on s.id = te.session_pk
        order by s.provider asc, model asc, te.timestamp_ms asc, te.sequence asc
        """
    ).fetchall()
    grouped: dict[tuple[str, str], list] = {}
    sessions: dict[tuple[str, str], set[int]] = {}
    for row in rows:
        key = (str(row["provider"]), str(row["model"]))
        grouped.setdefault(key, []).append(row)
        sessions.setdefault(key, set()).add(int(row["session_pk"]))

    models = []
    for (provider, model), model_rows in grouped.items():
        total_tokens = sum(int(row["total_tokens"]) for row in model_rows)
        input_tokens = sum(_row_int(row, "input_tokens") for row in model_rows)
        cached_input_tokens = sum(_row_int(row, "cached_input_tokens") for row in model_rows)
        cache_creation_input_tokens = sum(
            _row_int(row, "cache_creation_input_tokens") + _row_int(row, "cache_creation_1h_input_tokens")
            for row in model_rows
        )
        output_tokens = sum(_row_int(row, "output_tokens") for row in model_rows)
        cost = _estimate_rows_cost(model_rows)["usd"]
        active = _active_ms(model_rows)
        event_count = len(model_rows)
        cache_denominator = input_tokens + cache_creation_input_tokens
        if cache_creation_input_tokens or cached_input_tokens > input_tokens:
            cache_denominator += cached_input_tokens
        models.append(
            {
                "provider": provider,
                "model": model,
                "session_count": len(sessions[(provider, model)]),
                "event_count": event_count,
                "total_tokens": total_tokens,
                "input_tokens": input_tokens,
                "cached_input_tokens": cached_input_tokens,
                "cache_creation_input_tokens": cache_creation_input_tokens,
                "output_tokens": output_tokens,
                "estimated_cost_usd": cost,
                "avg_cost_per_turn_usd": round(cost / event_count, 6) if event_count else 0.0,
                "cached_input_ratio": round(cached_input_tokens / cache_denominator, 6) if cache_denominator else 0.0,
                "active_ms": active,
                "tokens_per_minute": _per_minute(total_tokens, active),
                "usd_per_minute": _per_minute(cost, active),
            }
        )
    return sorted(models, key=lambda item: (item["estimated_cost_usd"], item["total_tokens"]), reverse=True)


def _provider_totals(model_rows: list[dict], total_tokens: int) -> list[dict]:
    providers: dict[str, dict] = {}
    for row in model_rows:
        provider = str(row["provider"])
        item = providers.setdefault(
            provider,
            {
                "provider": provider,
                "session_count": 0,
                "event_count": 0,
                "total_tokens": 0,
                "estimated_cost_usd": 0.0,
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "output_tokens": 0,
                "model_count": 0,
            },
        )
        item["session_count"] += int(row["session_count"])
        item["event_count"] += int(row["event_count"])
        item["total_tokens"] += int(row["total_tokens"])
        item["estimated_cost_usd"] += float(row["estimated_cost_usd"])
        item["input_tokens"] += int(row["input_tokens"])
        item["cached_input_tokens"] += int(row["cached_input_tokens"])
        item["cache_creation_input_tokens"] += int(row["cache_creation_input_tokens"])
        item["output_tokens"] += int(row["output_tokens"])
        item["model_count"] += 1

    rows = []
    for item in providers.values():
        item["estimated_cost_usd"] = round(float(item["estimated_cost_usd"]), 6)
        item["token_share"] = round(item["total_tokens"] / total_tokens, 6) if total_tokens else 0.0
        rows.append(item)
    return sorted(rows, key=lambda item: (item["estimated_cost_usd"], item["total_tokens"]), reverse=True)


def _task_rollups(con) -> list[dict]:
    rows = con.execute(
        """
        select t.id as task_id, t.task_key, t.display_name, p.name as project_name,
               s.id as session_pk, s.provider, s.model, te.sequence, te.timestamp_ms,
               te.input_tokens, te.cached_input_tokens,
               te.cache_creation_input_tokens, te.cache_creation_1h_input_tokens,
               te.output_tokens, te.total_tokens
        from tasks t
        join projects p on p.id = t.project_id
        left join sessions s on s.task_id = t.id
        left join token_events te on te.session_pk = s.id
        order by t.id asc, te.timestamp_ms asc, te.sequence asc
        """
    ).fetchall()
    grouped: dict[int, dict] = {}
    for row in rows:
        task_id = int(row["task_id"])
        item = grouped.setdefault(
            task_id,
            {
                "task_id": task_id,
                "task_key": row["task_key"],
                "display_name": row["display_name"],
                "project_name": row["project_name"],
                "session_ids": set(),
                "events": [],
            },
        )
        if row["session_pk"] is not None:
            item["session_ids"].add(int(row["session_pk"]))
        if row["sequence"] is not None:
            item["events"].append(row)

    rollups = []
    for item in grouped.values():
        events = item["events"]
        total_tokens = sum(_row_int(row, "total_tokens") for row in events)
        input_tokens = sum(_row_int(row, "input_tokens") for row in events)
        cached_input_tokens = sum(_row_int(row, "cached_input_tokens") for row in events)
        cache_creation_input_tokens = sum(
            _row_int(row, "cache_creation_input_tokens") + _row_int(row, "cache_creation_1h_input_tokens")
            for row in events
        )
        output_tokens = sum(_row_int(row, "output_tokens") for row in events)
        cache_denominator = input_tokens + cached_input_tokens + cache_creation_input_tokens
        rollups.append(
            {
                "task_id": item["task_id"],
                "task_key": item["task_key"],
                "display_name": item["display_name"],
                "project_name": item["project_name"],
                "session_count": len(item["session_ids"]),
                "event_count": len(events),
                "total_tokens": total_tokens,
                "input_tokens": input_tokens,
                "cached_input_tokens": cached_input_tokens,
                "cache_creation_input_tokens": cache_creation_input_tokens,
                "output_tokens": output_tokens,
                "estimated_cost_usd": _estimate_rows_cost(events)["usd"] if events else 0.0,
                "active_ms": _active_ms(events),
                "cache_share": round(cached_input_tokens / cache_denominator, 6) if cache_denominator else 0.0,
            }
        )
    return rollups


def _driver_state(value: float, warn_at: float, over_at: float, *, higher_is_better: bool = False) -> str:
    if higher_is_better:
        if value >= over_at:
            return "good"
        if value >= warn_at:
            return "watch"
        return "risk"
    if value >= over_at:
        return "risk"
    if value >= warn_at:
        return "watch"
    return "good"


def _task_event_rows(con, task_id: int) -> list:
    return con.execute(
        """
        select s.provider, s.model, te.sequence, te.timestamp_ms,
               te.input_tokens, te.cached_input_tokens,
               te.cache_creation_input_tokens, te.cache_creation_1h_input_tokens,
               te.output_tokens, te.reasoning_output_tokens, te.total_tokens
        from token_events te
        join sessions s on s.id = te.session_pk
        where s.task_id = ?
        order by te.timestamp_ms desc, te.sequence desc
        limit 12
        """,
        (task_id,),
    ).fetchall()


def _phase_for_turn(sequence: int, index_from_latest: int) -> str:
    if sequence <= 2:
        return "plan"
    if index_from_latest <= 1:
        return "verify"
    return "build"


def _task_economics(con, current: dict | None, burn_rate: dict) -> dict:
    empty = {
        "configured": False,
        "projection_minutes": ECONOMICS_PROJECTION_MINUTES,
        "status": "learning",
        "status_label": "Learning baseline",
        "next_best_move": {
            "title": "Start a tracked task",
            "detail": "AI Keeper will compare task cost once provider events arrive.",
            "actions": [],
        },
        "drivers": [],
        "ledger": [],
    }
    if not current:
        return empty

    rollups = _task_rollups(con)
    current_rollup = next((row for row in rollups if row["task_id"] == int(current["task_id"])), None)
    if not current_rollup:
        return empty

    baseline_costs = [
        float(row["estimated_cost_usd"])
        for row in rollups
        if row["task_id"] != int(current["task_id"]) and float(row["estimated_cost_usd"]) > 0
    ]
    baseline_tokens = [
        int(row["total_tokens"])
        for row in rollups
        if row["task_id"] != int(current["task_id"]) and int(row["total_tokens"]) > 0
    ]
    baseline_events = [
        int(row["event_count"])
        for row in rollups
        if row["task_id"] != int(current["task_id"]) and int(row["event_count"]) > 0
    ]
    baseline_cost = round(float(median(baseline_costs)), 6) if baseline_costs else None
    baseline_token_count = int(median(baseline_tokens)) if baseline_tokens else None
    baseline_event_count = int(median(baseline_events)) if baseline_events else None
    task_cost = float(current_rollup["estimated_cost_usd"])
    task_tokens = int(current_rollup["total_tokens"])
    event_count = int(current_rollup["event_count"])
    active = int(current_rollup["active_ms"])
    current_burn = burn_rate.get("current") if burn_rate else None
    usd_per_minute = float(current_burn.get("usd_per_minute", 0.0)) if current_burn else 0.0
    tokens_per_minute = float(current_burn.get("tokens_per_minute", 0.0)) if current_burn else 0.0
    projected_cost = round(task_cost + usd_per_minute * ECONOMICS_PROJECTION_MINUTES, 6)
    projected_tokens = int(task_tokens + tokens_per_minute * ECONOMICS_PROJECTION_MINUTES)
    baseline_delta = (task_cost - baseline_cost) / baseline_cost if baseline_cost else None

    if baseline_cost is None:
        status = "learning"
        status_label = "Learning baseline"
    elif baseline_delta <= 0.1:
        status = "efficient"
        status_label = "Within usual range"
    elif baseline_delta <= 0.75:
        status = "watch"
        status_label = "Above usual"
    else:
        status = "risk"
        status_label = "Expensive task"

    token_delta = (task_tokens - baseline_token_count) / baseline_token_count if baseline_token_count else None
    event_delta = (event_count - baseline_event_count) / baseline_event_count if baseline_event_count else None
    avg_turn_cost = round(task_cost / event_count, 6) if event_count else 0.0
    drivers = [
        {
            "label": "Context load",
            "value": f"{task_tokens:,} tokens",
            "state": _driver_state(token_delta or 0.0, 0.25, 0.75) if token_delta is not None else "learning",
            "detail": "Compared with usual task tokens" if token_delta is not None else "Needs more completed task history",
        },
        {
            "label": "Turn volume",
            "value": f"{event_count:,} turns",
            "state": _driver_state(event_delta or 0.0, 0.25, 0.75) if event_delta is not None else "learning",
            "detail": "More turns usually means more rework and context drag" if event_delta is not None else "Baseline not ready yet",
        },
        {
            "label": "Cache leverage",
            "value": f"{current_rollup['cache_share'] * 100:.0f}%",
            "state": _driver_state(float(current_rollup["cache_share"]), 0.15, 0.35, higher_is_better=True),
            "detail": "Higher cache share lowers repeated context cost",
        },
        {
            "label": "Active burn",
            "value": f"${usd_per_minute:.2f}/min",
            "state": _driver_state(usd_per_minute, 0.25, 0.75),
            "detail": f"Projection uses the last {ACTIVE_WINDOW_MS // 60_000} active minutes",
        },
    ]

    actions = []
    if status == "risk":
        title = "Stop the drift before the next broad turn"
        detail = "The task is already far above your learned baseline. Ask for a narrow plan or split the remaining work."
        actions = ["Ask for a 3-step plan", "Split the task", "Commit the working slice"]
    elif usd_per_minute >= 0.25:
        title = "Let this turn finish, then narrow the next one"
        detail = "Live burn is high. Keep the next prompt scoped to one file, one failing test, or one decision."
        actions = ["Narrow next turn", "Run tests first", "Avoid broad refactor prompts"]
    elif current_rollup["cache_share"] < 0.15 and event_count >= 6:
        title = "Compress context before more implementation"
        detail = "Repeated context is not getting much cache help. Summarize state, then continue with a smaller prompt."
        actions = ["Summarize state", "Drop old context", "Continue from latest diff"]
    elif baseline_cost is None:
        title = "Keep collecting task history"
        detail = "AI Keeper needs more task samples before it can judge whether this task is unusually expensive."
        actions = ["Finish the current slice", "Keep task branches clean"]
    else:
        title = "Continue, but keep the next turn specific"
        detail = "The task is still inside the learned range. Preserve that by asking for the smallest useful next step."
        actions = ["Continue", "Keep scope narrow"]

    ledger = []
    recent_rows = _task_event_rows(con, int(current["task_id"]))
    for index, row in enumerate(recent_rows):
        cost = _estimate_rows_cost([row])["usd"]
        ledger.append(
            {
                "sequence": int(row["sequence"]),
                "phase": _phase_for_turn(int(row["sequence"]), index),
                "provider": row["provider"],
                "model": row["model"],
                "tokens": _row_int(row, "total_tokens"),
                "estimated_cost_usd": cost,
                "timestamp_ms": int(row["timestamp_ms"]),
            }
        )
    ledger.reverse()

    return {
        "configured": True,
        "projection_minutes": ECONOMICS_PROJECTION_MINUTES,
        "status": status,
        "status_label": status_label,
        "task": {
            "id": current_rollup["task_id"],
            "key": current_rollup["task_key"],
            "name": current_rollup["display_name"],
            "project_name": current_rollup["project_name"],
        },
        "spent": {
            "tokens": task_tokens,
            "estimated_cost_usd": task_cost,
            "event_count": event_count,
            "session_count": int(current_rollup["session_count"]),
            "active_ms": active,
            "avg_turn_cost_usd": avg_turn_cost,
        },
        "projection": {
            "tokens": projected_tokens,
            "estimated_cost_usd": projected_cost,
            "additional_cost_usd": round(projected_cost - task_cost, 6),
        },
        "baseline": {
            "sample_size": len(baseline_costs),
            "estimated_cost_usd": baseline_cost,
            "tokens": baseline_token_count,
            "event_count": baseline_event_count,
            "delta_ratio": round(baseline_delta, 6) if baseline_delta is not None else None,
        },
        "drivers": drivers,
        "next_best_move": {"title": title, "detail": detail, "actions": actions},
        "ledger": ledger,
    }


def _simulation_summaries(con) -> list[dict]:
    rows = con.execute(
        """
        select s.model, te.input_tokens, te.cached_input_tokens,
               te.cache_creation_input_tokens, te.cache_creation_1h_input_tokens,
               te.output_tokens
        from token_events te
        join sessions s on s.id = te.session_pk
        order by te.timestamp_ms asc, te.sequence asc
        """
    ).fetchall()
    source = [dict(row) for row in rows]
    return [simulate_cost_rows(source, target) for target in ("gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.3-codex")]


def _project_anomalies(sessions: list[dict]) -> list[dict]:
    models = [session["model"] or "unknown" for session in sessions]
    unique_models = list(dict.fromkeys(models))
    if len(unique_models) <= 1:
        return []
    return [
        {
            "severity": "low",
            "reason": "model switch",
            "detail": "Project has sessions across models: " + ", ".join(unique_models[:5]),
        }
    ]


def _budget_values(
    *,
    project_today_tokens: int,
    project_today_cost_usd: float,
    task_today_tokens: int,
    task_today_cost_usd: float,
    session_tokens: int,
    session_cost_usd: float,
    turn_tokens: int,
    turn_cost_usd: float,
) -> dict[str, float | int]:
    return {
        "project_daily_tokens": project_today_tokens,
        "project_daily_usd": project_today_cost_usd,
        "task_daily_tokens": task_today_tokens,
        "task_daily_usd": task_today_cost_usd,
        "session_tokens": session_tokens,
        "session_usd": session_cost_usd,
        "turn_tokens": turn_tokens,
        "turn_usd": turn_cost_usd,
    }


def _budget_config(db_path: Path | str, path: Path | str | None = None):
    if path is not None:
        return load_budget_config(path)
    return load_budget_config_from_db(db_path)


def _overview_budget(
    con,
    current: dict | None,
    day_start: int,
    config,
) -> tuple[dict, list[dict]]:
    if not current:
        return budget_state(config), []
    task_config = config_for_task(config, str(current["task_key"]))

    project_today_tokens = _sum_tokens_since(con, "s.project_id = ?", (current["project_id"],), day_start)
    task_today_tokens = _sum_tokens_since(con, "s.task_id = ?", (current["task_id"],), day_start)
    project_today_cost = _estimate_cost(con, "s.project_id = ?", (current["project_id"],), day_start)
    task_today_cost = _estimate_cost(con, "s.task_id = ?", (current["task_id"],), day_start)
    values = _budget_values(
        project_today_tokens=project_today_tokens,
        project_today_cost_usd=project_today_cost["usd"],
        task_today_tokens=task_today_tokens,
        task_today_cost_usd=task_today_cost["usd"],
        session_tokens=int(current["total_tokens"]),
        session_cost_usd=float(current["estimated_cost_usd"]),
        turn_tokens=int(current["last_turn_tokens"]),
        turn_cost_usd=float(current["last_turn_cost_usd"]),
    )
    return budget_state(task_config), evaluate_budget_warnings(values, task_config)


def status_for_cwd(
    db_path: Path | str,
    cwd: Path | str,
    now_ms: int | None = None,
    budget_path: Path | str | None = None,
) -> dict:
    now = now_ms or current_now_ms()
    day_start = utc_day_start_ms(now)
    config = _budget_config(db_path, budget_path)
    meta = get_git_metadata(cwd)
    task_key, _source, issue_id, display_name = task_identity(meta.branch)

    with connect(db_path) as con:
        init_db(con)
        session = con.execute(
            """
            select s.*, p.name as project_name, p.root_path, t.task_key, t.display_name as task_name
            from sessions s
            join projects p on p.id = s.project_id
            join tasks t on t.id = s.task_id
            where s.cwd = ? or p.root_path = ?
            order by s.updated_at_ms desc, s.id desc
            limit 1
            """,
            (str(Path(cwd).expanduser()), str(meta.root_path)),
        ).fetchone()
        if not session:
            return {
                "project": {"name": meta.root_path.name, "root_path": str(meta.root_path), "today_tokens": 0, "today_cost_usd": 0.0},
                "task": {"task_key": task_key, "display_name": display_name, "issue_id": issue_id, "today_tokens": 0, "today_cost_usd": 0.0},
                "session": {"session_id": None, "total_tokens": 0, "last_turn_tokens": 0, "estimated_cost_usd": 0.0, "last_turn_cost_usd": 0.0},
                "budget": budget_state(config),
                "budget_warnings": [],
            }

        last_turn = con.execute(
            """
            select te.total_tokens, s.model, te.input_tokens, te.cached_input_tokens,
                   te.cache_creation_input_tokens, te.cache_creation_1h_input_tokens,
                   te.output_tokens
            from token_events te
            join sessions s on s.id = te.session_pk
            where te.session_pk = ?
            order by sequence desc
            limit 1
            """,
            (session["id"],),
        ).fetchone()

        project_today = _sum_tokens_since(con, "s.project_id = ?", (session["project_id"],), day_start)
        task_today = _sum_tokens_since(con, "s.task_id = ?", (session["task_id"],), day_start)
        project_today_cost = _estimate_cost(con, "s.project_id = ?", (session["project_id"],), day_start)
        task_today_cost = _estimate_cost(con, "s.task_id = ?", (session["task_id"],), day_start)
        session_cost = _estimate_cost(con, "s.id = ?", (session["id"],))
        last_turn_cost = _estimate_rows_cost([last_turn]) if last_turn else {"usd": 0.0}
        status = {
            "project": {
                "id": session["project_id"],
                "name": session["project_name"],
                "root_path": session["root_path"],
                "today_tokens": project_today,
                "today_cost_usd": project_today_cost["usd"],
            },
            "task": {
                "id": session["task_id"],
                "task_key": session["task_key"],
                "display_name": session["task_name"],
                "issue_id": issue_id,
                "today_tokens": task_today,
                "today_cost_usd": task_today_cost["usd"],
            },
            "session": {
                "id": session["id"],
                "session_id": session["session_id"],
                "total_tokens": int(session["total_tokens"]),
                "last_turn_tokens": int(last_turn["total_tokens"]) if last_turn else 0,
                "estimated_cost_usd": session_cost["usd"],
                "last_turn_cost_usd": last_turn_cost["usd"],
            },
        }
        task_config = config_for_task(config, str(session["task_key"]))
        values = _budget_values(
            project_today_tokens=project_today,
            project_today_cost_usd=project_today_cost["usd"],
            task_today_tokens=task_today,
            task_today_cost_usd=task_today_cost["usd"],
            session_tokens=int(session["total_tokens"]),
            session_cost_usd=session_cost["usd"],
            turn_tokens=int(last_turn["total_tokens"]) if last_turn else 0,
            turn_cost_usd=last_turn_cost["usd"],
        )
        status["budget"] = budget_state(task_config)
        status["budget_warnings"] = evaluate_budget_warnings(values, task_config)
        return status


def overview(db_path: Path | str, now_ms: int | None = None, budget_path: Path | str | None = None) -> dict:
    now = now_ms or current_now_ms()
    day_start = utc_day_start_ms(now)
    week_start = utc_week_start_ms(now)
    with connect(db_path) as con:
        init_db(con)
        total_tokens = con.execute("select coalesce(sum(total_tokens), 0) as tokens from token_events").fetchone()
        today_tokens = con.execute(
            "select coalesce(sum(total_tokens), 0) as tokens from token_events where timestamp_ms >= ?",
            (day_start,),
        ).fetchone()
        week_tokens = con.execute(
            "select coalesce(sum(total_tokens), 0) as tokens from token_events where timestamp_ms >= ?",
            (week_start,),
        ).fetchone()
        projects = con.execute(
            """
            select p.id, p.name, p.root_path,
                   coalesce(sum(te.total_tokens), 0) as tokens,
                   coalesce(sum(case when te.timestamp_ms >= ? then te.total_tokens else 0 end), 0) as today_tokens
            from projects p
            left join sessions s on s.project_id = p.id
            left join token_events te on te.session_pk = s.id
            group by p.id
            order by tokens desc, p.last_seen_ms desc
            """
            ,
            (day_start,),
        ).fetchall()
        tasks = con.execute(
            """
            select t.id, t.display_name, t.task_key, p.name as project_name,
                   coalesce(sum(te.total_tokens), 0) as tokens
            from tasks t
            join projects p on p.id = t.project_id
            left join sessions s on s.task_id = t.id
            left join token_events te on te.session_pk = s.id
            group by t.id
            order by tokens desc, t.last_seen_ms desc
            limit 12
            """
        ).fetchall()
        total_cost = _estimate_cost(con)
        today_cost = _estimate_cost(con, since_ms=day_start)
        week_cost = _estimate_cost(con, since_ms=week_start)
        project_rows = []
        for row in projects:
            item = dict(row)
            item["estimated_cost_usd"] = _estimate_cost(con, "s.project_id = ?", (row["id"],))["usd"]
            item["today_estimated_cost_usd"] = _estimate_cost(
                con, "s.project_id = ?", (row["id"],), day_start
            )["usd"]
            project_rows.append(item)
        task_rows = []
        for row in tasks:
            item = dict(row)
            item["estimated_cost_usd"] = _estimate_cost(con, "s.task_id = ?", (row["id"],))["usd"]
            task_rows.append(item)
        current_activity = _current_activity(con)
        config = _budget_config(db_path, budget_path)
        budget, budget_warnings = _overview_budget(con, current_activity, day_start, config)
        current_task_key = current_activity["task_key"] if current_activity else None
        model_efficiency = _model_efficiency(con)
        total_token_count = int(total_tokens["tokens"])
        burn_rate = _current_burn_rate(con, now)
        return {
            "generated_at_ms": now,
            "total_tokens": total_token_count,
            "today_tokens": int(today_tokens["tokens"]),
            "week_tokens": int(week_tokens["tokens"]),
            "estimated_cost": {
                "currency": "usd",
                "total_usd": total_cost["usd"],
                "today_usd": today_cost["usd"],
                "week_usd": week_cost["usd"],
                "unpriced_models": sorted(
                    set(total_cost["unpriced_models"])
                    | set(today_cost["unpriced_models"])
                    | set(week_cost["unpriced_models"])
                ),
                "source_label": PRICING_SOURCE_LABEL,
                "source_url": PRICING_SOURCE_URL,
                "retrieved_date": PRICING_RETRIEVED_DATE,
            },
            "daily_tokens": _daily_tokens(con, now),
            "current_activity": current_activity,
            "burn_rate": burn_rate,
            "task_economics": _task_economics(con, current_activity, burn_rate),
            "model_efficiency": model_efficiency,
            "provider_totals": _provider_totals(model_efficiency, total_token_count),
            "simulations": _simulation_summaries(con),
            "budget": budget,
            "budget_warnings": budget_warnings,
            "budget_settings": budget_settings_state(config, current_task_key),
            "privacy_audit": audit_privacy(db_path),
            "ingest_health": ingest_health(db_path, now_ms=now),
            "projects": project_rows,
            "tasks": task_rows,
        }


def _task_budget_summary(con, task, *, day_start: int, config) -> tuple[dict, list[dict]]:
    task_config = config_for_task(config, str(task["task_key"]))
    task_today_tokens = _sum_tokens_since(con, "s.task_id = ?", (task["id"],), day_start)
    task_today_cost = _estimate_cost(con, "s.task_id = ?", (task["id"],), day_start)
    values = _budget_values(
        project_today_tokens=0,
        project_today_cost_usd=0.0,
        task_today_tokens=task_today_tokens,
        task_today_cost_usd=task_today_cost["usd"],
        session_tokens=0,
        session_cost_usd=0.0,
        turn_tokens=0,
        turn_cost_usd=0.0,
    )
    return budget_state(task_config), evaluate_budget_warnings(values, task_config)


def project_detail(
    db_path: Path | str,
    project_id: int,
    *,
    budget_path: Path | str | None = None,
    now_ms: int | None = None,
) -> dict:
    now = now_ms or current_now_ms()
    day_start = utc_day_start_ms(now)
    config = _budget_config(db_path, budget_path)
    with connect(db_path) as con:
        init_db(con)
        project = con.execute("select * from projects where id = ?", (project_id,)).fetchone()
        if not project:
            raise KeyError(project_id)
        tasks = con.execute(
            """
            select t.*, coalesce(sum(te.total_tokens), 0) as tokens, count(distinct s.id) as sessions_count
            from tasks t
            left join sessions s on s.task_id = t.id
            left join token_events te on te.session_pk = s.id
            where t.project_id = ?
            group by t.id
            order by tokens desc, t.last_seen_ms desc
            """,
            (project_id,),
        ).fetchall()
        sessions = con.execute(
            """
            select s.*, t.display_name as task_name
            from sessions s
            join tasks t on t.id = s.task_id
            where s.project_id = ?
            order by s.updated_at_ms desc
            limit 50
            """,
            (project_id,),
        ).fetchall()
        task_rows = []
        for row in tasks:
            item = dict(row)
            budget, warnings = _task_budget_summary(con, row, day_start=day_start, config=config)
            item["budget"] = budget
            item["budget_warnings"] = warnings
            task_rows.append(item)
        session_rows = [dict(row) for row in sessions]
        return {
            "project": dict(project),
            "tasks": task_rows,
            "sessions": session_rows,
            "anomalies": _project_anomalies(session_rows),
        }


def session_detail(db_path: Path | str, session_pk: int) -> dict:
    with connect(db_path) as con:
        init_db(con)
        session = con.execute(
            """
            select s.*, p.name as project_name, t.display_name as task_name
            from sessions s
            join projects p on p.id = s.project_id
            join tasks t on t.id = s.task_id
            where s.id = ?
            """,
            (session_pk,),
        ).fetchone()
        if not session:
            raise KeyError(session_pk)
        events = con.execute(
            """
            select * from token_events
            where session_pk = ?
            order by sequence asc
            """,
            (session_pk,),
        ).fetchall()
        event_rows = [dict(row) for row in events]
        return {
            "session": dict(session),
            "events": event_rows,
            "context_health": context_health(event_rows, session["model"]),
            "anomalies": detect_session_anomalies(event_rows, session["model"]),
        }


def simulate_model_cost(db_path: Path | str, target_model: str) -> dict:
    with connect(db_path) as con:
        init_db(con)
        rows = con.execute(
            """
            select s.model, te.input_tokens, te.cached_input_tokens,
                   te.cache_creation_input_tokens, te.cache_creation_1h_input_tokens,
                   te.output_tokens
            from token_events te
            join sessions s on s.id = te.session_pk
            order by te.timestamp_ms asc, te.sequence asc
            """
        ).fetchall()
    return simulate_cost_rows([dict(row) for row in rows], target_model)


def task_budget_status(db_path: Path | str, *, budget_path: Path | str | None = None, now_ms: int | None = None) -> list[dict]:
    now = now_ms or current_now_ms()
    day_start = utc_day_start_ms(now)
    config = _budget_config(db_path, budget_path)
    with connect(db_path) as con:
        init_db(con)
        tasks = con.execute(
            """
            select t.id, t.task_key, t.display_name, p.name as project_name,
                   coalesce(sum(te.total_tokens), 0) as total_tokens
            from tasks t
            join projects p on p.id = t.project_id
            left join sessions s on s.task_id = t.id
            left join token_events te on te.session_pk = s.id
            group by t.id
            order by total_tokens desc
            """
        ).fetchall()
        rows = []
        for task in tasks:
            budget, warnings = _task_budget_summary(con, task, day_start=day_start, config=config)
            rows.append(
                {
                    "task_key": task["task_key"],
                    "display_name": task["display_name"],
                    "project_name": task["project_name"],
                    "total_tokens": int(task["total_tokens"]),
                    "budget": budget,
                    "budget_warnings": warnings,
                }
            )
    return rows
