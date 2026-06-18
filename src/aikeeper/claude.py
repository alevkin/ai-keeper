from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from aikeeper.codex import SyncResult, TokenUsageEvent
from aikeeper.db import connect, init_db
from aikeeper.settings import claude_home as default_claude_home
from aikeeper.storage import upsert_session
from aikeeper.timeutils import now_ms, parse_timestamp_ms


@dataclass(frozen=True)
class ClaudeEvent:
    session_id: str
    cwd: str
    model: str | None
    git_branch: str | None
    usage: TokenUsageEvent

    @property
    def total_tokens(self) -> int:
        return self.usage.total_tokens

    @property
    def cached_input_tokens(self) -> int:
        return self.usage.cached_input_tokens

    @property
    def cache_creation_input_tokens(self) -> int:
        return self.usage.cache_creation_input_tokens + self.usage.cache_creation_1h_input_tokens


def _int(value: object) -> int:
    return int(value) if isinstance(value, int | float) else 0


def _dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _usage_from_message(raw: dict) -> dict:
    message = _dict(raw.get("message"))
    usage = message.get("usage") if isinstance(message.get("usage"), dict) else raw.get("usage")
    return usage if isinstance(usage, dict) else {}


def _cache_creation_usage(usage: dict) -> tuple[int, int]:
    cache_creation = _dict(usage.get("cache_creation"))
    five_min = _int(cache_creation.get("ephemeral_5m_input_tokens"))
    one_hour = _int(cache_creation.get("ephemeral_1h_input_tokens"))
    total = _int(usage.get("cache_creation_input_tokens"))
    if total and not five_min and not one_hour:
        five_min = total
    elif total > five_min + one_hour:
        five_min += total - five_min - one_hour
    return five_min, one_hour


def parse_claude_token_events(
    lines: Iterable[str],
    *,
    fallback_session_id: str | None = None,
    fallback_cwd: Path | str | None = None,
) -> Iterable[ClaudeEvent]:
    for line in lines:
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue

        usage = _usage_from_message(raw)
        if not usage:
            continue

        message = _dict(raw.get("message"))
        input_tokens = _int(usage.get("input_tokens"))
        cache_read_tokens = _int(usage.get("cache_read_input_tokens")) + _int(usage.get("cached_input_tokens"))
        cache_write_5m, cache_write_1h = _cache_creation_usage(usage)
        output_tokens = _int(usage.get("output_tokens"))
        total_tokens = (
            _int(usage.get("total_tokens"))
            or input_tokens
            + cache_read_tokens
            + cache_write_5m
            + cache_write_1h
            + output_tokens
        )
        session_id = str(raw.get("sessionId") or raw.get("session_id") or fallback_session_id or "claude-session")
        cwd = str(raw.get("cwd") or fallback_cwd or Path.cwd())
        model = raw.get("model") or message.get("model")
        git_branch = raw.get("gitBranch") or raw.get("git_branch")
        yield ClaudeEvent(
            session_id=session_id,
            cwd=cwd,
            model=str(model) if model else None,
            git_branch=str(git_branch) if git_branch else None,
            usage=TokenUsageEvent(
                timestamp_ms=parse_timestamp_ms(raw.get("timestamp")),
                input_tokens=input_tokens,
                cached_input_tokens=cache_read_tokens,
                output_tokens=output_tokens,
                reasoning_output_tokens=0,
                total_tokens=total_tokens,
                running_total_tokens=total_tokens,
                cache_creation_input_tokens=cache_write_5m,
                cache_creation_1h_input_tokens=cache_write_1h,
            ),
        )


def _scan_claude_transcripts(claude_home: Path) -> list[Path]:
    root = claude_home / "projects"
    return sorted(root.rglob("*.jsonl")) if root.exists() else []


def _last_offset(con: sqlite3.Connection, source_key: str) -> int:
    row = con.execute("select last_offset from ingest_state where source_key = ?", (source_key,)).fetchone()
    return int(row["last_offset"]) if row else 0


def _set_offset(con: sqlite3.Connection, source_key: str, offset: int) -> None:
    con.execute(
        """
        insert into ingest_state(source_key, last_offset, updated_at_ms, meta_json)
        values (?, ?, ?, '{}')
        on conflict(source_key) do update set
            last_offset = excluded.last_offset,
            updated_at_ms = excluded.updated_at_ms
        """,
        (source_key, offset, now_ms()),
    )


def _max_sequence(con: sqlite3.Connection, session_pk: int) -> int:
    row = con.execute(
        "select coalesce(max(sequence), 0) as seq from token_events where session_pk = ?",
        (session_pk,),
    ).fetchone()
    return int(row["seq"])


def _session_total(con: sqlite3.Connection, session_pk: int) -> int:
    row = con.execute("select total_tokens from sessions where id = ?", (session_pk,)).fetchone()
    return int(row["total_tokens"]) if row else 0


def _fallback_cwd(path: Path, claude_home: Path) -> Path:
    try:
        encoded_project = path.relative_to(claude_home / "projects").parts[0]
    except ValueError:
        return Path.cwd()
    if encoded_project.startswith("-") and "/" not in encoded_project:
        return Path("/" + encoded_project[1:].replace("-", "/"))
    return Path.cwd()


def _session_pk_for_event(con: sqlite3.Connection, event: ClaudeEvent, path: Path) -> tuple[int, bool]:
    existing = con.execute(
        "select id from sessions where provider = 'claude' and session_id = ?",
        (event.session_id,),
    ).fetchone()
    is_new = existing is None
    session_pk = upsert_session(
        con,
        provider="claude",
        session_id=event.session_id,
        cwd=event.cwd,
        transcript_path=path,
        model=event.model,
        model_provider="anthropic",
        source="claude-jsonl",
        git_sha=None,
        git_branch=event.git_branch,
        git_origin_url=None,
        created_at_ms=event.usage.timestamp_ms,
        updated_at_ms=event.usage.timestamp_ms,
        total_tokens=0,
        probe_git=False,
    )
    return session_pk, is_new


def _import_transcript(con: sqlite3.Connection, *, path: Path, claude_home: Path) -> SyncResult:
    if not path.exists():
        return SyncResult()
    source_key = f"claude-transcript:{path}"
    size = path.stat().st_size
    offset = _last_offset(con, source_key)
    if offset > size:
        offset = 0
    if offset == size:
        return SyncResult()

    sessions_imported = 0
    events_imported = 0
    session_by_id: dict[str, int] = {}
    sequence_by_session: dict[int, int] = {}
    running_by_session: dict[int, int] = {}
    fallback_session_id = path.stem
    fallback_cwd = _fallback_cwd(path, claude_home)
    new_offset = offset

    with path.open("rb") as handle:
        handle.seek(offset)
        for raw_line in handle:
            if not raw_line.endswith(b"\n"):
                break
            line_offset = new_offset
            new_offset += len(raw_line)
            line = raw_line.decode("utf-8", errors="replace")
            for event in parse_claude_token_events(
                [line],
                fallback_session_id=fallback_session_id,
                fallback_cwd=fallback_cwd,
            ):
                session_pk = session_by_id.get(event.session_id)
                if session_pk is None:
                    session_pk, is_new = _session_pk_for_event(con, event, path)
                    session_by_id[event.session_id] = session_pk
                    if is_new:
                        sessions_imported += 1
                sequence = sequence_by_session.get(session_pk)
                if sequence is None:
                    sequence = _max_sequence(con, session_pk)
                running_total = running_by_session.get(session_pk)
                if running_total is None:
                    running_total = _session_total(con, session_pk)
                sequence += 1
                running_total += event.usage.total_tokens
                sequence_by_session[session_pk] = sequence
                running_by_session[session_pk] = running_total
                cursor = con.execute(
                    """
                    insert or ignore into token_events(
                        session_pk, sequence, timestamp_ms, input_tokens, cached_input_tokens,
                        cache_creation_input_tokens, cache_creation_1h_input_tokens,
                        output_tokens, reasoning_output_tokens, total_tokens,
                        running_total_tokens, source_path, source_offset
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_pk,
                        sequence,
                        event.usage.timestamp_ms,
                        event.usage.input_tokens,
                        event.usage.cached_input_tokens,
                        event.usage.cache_creation_input_tokens,
                        event.usage.cache_creation_1h_input_tokens,
                        event.usage.output_tokens,
                        event.usage.reasoning_output_tokens,
                        event.usage.total_tokens,
                        running_total,
                        str(path),
                        line_offset,
                    ),
                )
                if cursor.rowcount > 0:
                    events_imported += 1
                    con.execute(
                        "update sessions set total_tokens = max(total_tokens, ?), updated_at_ms = max(updated_at_ms, ?) where id = ?",
                        (running_total, event.usage.timestamp_ms, session_pk),
                    )
    _set_offset(con, source_key, new_offset)
    return SyncResult(sessions_imported=sessions_imported, token_events_imported=events_imported)


def sync_claude_once(
    *,
    db_path: Path | str,
    claude_home: Path | str | None = None,
) -> SyncResult:
    home = Path(claude_home).expanduser() if claude_home else default_claude_home()
    sessions_imported = 0
    events_imported = 0
    with connect(db_path) as con:
        init_db(con)
        for path in _scan_claude_transcripts(home):
            result = _import_transcript(con, path=path, claude_home=home)
            sessions_imported += result.sessions_imported
            events_imported += result.token_events_imported
        con.commit()
    return SyncResult(sessions_imported=sessions_imported, token_events_imported=events_imported)
