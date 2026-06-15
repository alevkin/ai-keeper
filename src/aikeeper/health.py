from __future__ import annotations

from pathlib import Path

from aikeeper.db import connect, init_db
from aikeeper.pricing import price_for_model
from aikeeper.timeutils import now_ms as current_now_ms


SOURCE_LIMIT = 25


def _source_path(source_key: str) -> str | None:
    prefixes = ("codex-transcript:", "claude-transcript:")
    for prefix in prefixes:
        if source_key.startswith(prefix):
            return source_key[len(prefix) :]
    return None


def _provider_counts(rows) -> dict[str, int]:
    return {str(row["provider"]): int(row["count"]) for row in rows}


def ingest_health(db_path: Path | str, *, now_ms: int | None = None) -> dict:
    now = now_ms or current_now_ms()
    with connect(db_path) as con:
        init_db(con)
        total_sessions = con.execute("select count(*) as count from sessions").fetchone()
        provider_rows = con.execute(
            """
            select provider, count(*) as count
            from sessions
            group by provider
            order by provider asc
            """
        ).fetchall()
        token_events = con.execute("select count(*) as count from token_events").fetchone()
        transcript_rows = con.execute(
            """
            select distinct transcript_path
            from sessions
            where transcript_path is not null and transcript_path != ''
            order by transcript_path asc
            """
        ).fetchall()
        ingest_rows = con.execute(
            """
            select source_key, last_offset, updated_at_ms
            from ingest_state
            order by updated_at_ms asc, source_key asc
            """
        ).fetchall()
        model_rows = con.execute(
            """
            select coalesce(model, 'unknown') as model, count(*) as sessions
            from sessions
            group by coalesce(model, 'unknown')
            order by model asc
            """
        ).fetchall()

    transcript_paths = [str(row["transcript_path"]) for row in transcript_rows]
    missing_transcripts = [path for path in transcript_paths if not Path(path).expanduser().exists()]

    source_details = []
    lagging_sources = 0
    missing_sources = 0
    for row in ingest_rows:
        source_key = str(row["source_key"])
        path = _source_path(source_key)
        source_file = Path(path).expanduser() if path else None
        exists = source_file.exists() if source_file else None
        if exists is False:
            missing_sources += 1
        is_lagging = False
        if exists and source_file:
            is_lagging = source_file.stat().st_size > int(row["last_offset"])
        if is_lagging:
            lagging_sources += 1
        source_details.append(
            {
                "source_key": source_key,
                "path": path,
                "exists": exists,
                "last_offset": int(row["last_offset"]),
                "updated_at_ms": int(row["updated_at_ms"]),
                "stale": is_lagging,
                "lagging": is_lagging,
            }
        )

    unknown_models = sorted({str(row["model"]) for row in model_rows if str(row["model"]).lower() in {"", "unknown", "none"}})
    unpriced_models = sorted({str(row["model"]) for row in model_rows if price_for_model(str(row["model"])) is None})
    issues = []
    if missing_transcripts:
        issues.append(f"{len(missing_transcripts)} missing transcript path(s)")
    if missing_sources:
        issues.append(f"{missing_sources} missing ingest source(s)")
    if lagging_sources:
        issues.append(f"{lagging_sources} lagging ingest source(s)")
    if unknown_models:
        issues.append(f"{len(unknown_models)} unknown model label(s)")
    if unpriced_models:
        issues.append(f"{len(unpriced_models)} unpriced model(s)")

    return {
        "status": "ok" if not issues else "warn",
        "issues": issues,
        "sessions": {
            "total": int(total_sessions["count"]),
            "by_provider": _provider_counts(provider_rows),
        },
        "token_events": {
            "total": int(token_events["count"]),
        },
        "transcripts": {
            "tracked": len(transcript_paths),
            "missing": len(missing_transcripts),
        },
        "ingest_state": {
            "sources": len(ingest_rows),
            "stale_sources": lagging_sources,
            "lagging_sources": lagging_sources,
            "missing_sources": missing_sources,
            "sample": _prioritized_sources(source_details),
            "truncated": len(source_details) > SOURCE_LIMIT,
        },
        "models": {
            "known": [str(row["model"]) for row in model_rows],
            "unknown": unknown_models,
            "unpriced": unpriced_models,
        },
        "generated_at_ms": now,
    }


def _prioritized_sources(sources: list[dict]) -> list[dict]:
    return sorted(
        sources,
        key=lambda item: (
            not (item["exists"] is False or item["lagging"]),
            -int(item["updated_at_ms"]),
            str(item["source_key"]),
        ),
    )[:SOURCE_LIMIT]
