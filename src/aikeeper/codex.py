from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from aikeeper.db import connect, init_db
from aikeeper.settings import codex_home as default_codex_home
from aikeeper.settings import default_db_path
from aikeeper.storage import upsert_session
from aikeeper.timeutils import now_ms, parse_timestamp_ms


@dataclass(frozen=True)
class TokenUsageEvent:
    timestamp_ms: int
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    total_tokens: int
    running_total_tokens: int
    cache_creation_input_tokens: int = 0
    cache_creation_1h_input_tokens: int = 0


@dataclass(frozen=True)
class SyncResult:
    sessions_imported: int = 0
    token_events_imported: int = 0


@dataclass(frozen=True)
class ExecIngestState:
    session_id: str = "codex-exec"
    sequence: int = 0


def _int(value: object) -> int:
    return int(value) if isinstance(value, int | float) else 0


def _event_from_usage(timestamp: str | None, usage: dict, running: dict | None = None) -> TokenUsageEvent:
    input_tokens = _int(usage.get("input_tokens"))
    cached_input_tokens = _int(usage.get("cached_input_tokens"))
    output_tokens = _int(usage.get("output_tokens"))
    reasoning_output_tokens = _int(usage.get("reasoning_output_tokens"))
    total_tokens = _int(usage.get("total_tokens")) or input_tokens + output_tokens
    running_total_tokens = _int((running or {}).get("total_tokens")) or total_tokens
    return TokenUsageEvent(
        timestamp_ms=parse_timestamp_ms(timestamp),
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        reasoning_output_tokens=reasoning_output_tokens,
        total_tokens=total_tokens,
        running_total_tokens=running_total_tokens,
    )


def parse_codex_token_events(lines: Iterable[str]) -> Iterable[TokenUsageEvent]:
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if event.get("type") == "event_msg" and payload.get("type") == "token_count":
            info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
            usage = info.get("last_token_usage")
            if isinstance(usage, dict):
                running = info.get("total_token_usage") if isinstance(info.get("total_token_usage"), dict) else None
                yield _event_from_usage(event.get("timestamp"), usage, running)
            continue

        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            yield _event_from_usage(event.get("timestamp"), event["usage"], None)


def _thread_columns(con: sqlite3.Connection) -> set[str]:
    return {row["name"] for row in con.execute("pragma table_info(threads)")}


def _value(row: sqlite3.Row, name: str, default: object = None) -> object:
    return row[name] if name in row.keys() else default


def _load_threads(codex_home: Path) -> list[sqlite3.Row]:
    state_db = codex_home / "state_5.sqlite"
    if not state_db.exists():
        return []
    with sqlite3.connect(state_db) as con:
        con.row_factory = sqlite3.Row
        columns = _thread_columns(con)
        wanted = [
            "id",
            "rollout_path",
            "created_at",
            "updated_at",
            "source",
            "model_provider",
            "cwd",
            "tokens_used",
            "git_sha",
            "git_branch",
            "git_origin_url",
            "model",
        ]
        selected = [name for name in wanted if name in columns]
        return list(con.execute(f"select {', '.join(selected)} from threads"))


def _path_from_value(value: object, codex_home: Path) -> Path | None:
    if not value:
        return None
    path = Path(str(value)).expanduser()
    return path if path.is_absolute() else codex_home / path


def _derived_session_id(path: Path) -> str:
    stem = path.stem
    return stem.removeprefix("rollout-") or stem


def _scan_transcripts(codex_home: Path) -> list[Path]:
    paths: list[Path] = []
    for root in (codex_home / "sessions", codex_home / "archived_sessions"):
        if root.exists():
            paths.extend(root.rglob("*.jsonl"))
    return sorted(set(paths))


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


def _import_transcript(con: sqlite3.Connection, *, session_pk: int, path: Path) -> int:
    if not path.exists():
        return 0
    source_key = f"codex-transcript:{path}"
    size = path.stat().st_size
    offset = _last_offset(con, source_key)
    if offset > size:
        offset = 0
    if offset == size:
        return 0

    imported = 0
    sequence = _max_sequence(con, session_pk)
    new_offset = offset
    with path.open("rb") as handle:
        handle.seek(offset)
        for raw_line in handle:
            if not raw_line.endswith(b"\n"):
                break
            line_offset = new_offset
            new_offset += len(raw_line)
            line = raw_line.decode("utf-8", errors="replace")
            for event in parse_codex_token_events([line]):
                sequence += 1
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
                        event.timestamp_ms,
                        event.input_tokens,
                        event.cached_input_tokens,
                        event.cache_creation_input_tokens,
                        event.cache_creation_1h_input_tokens,
                        event.output_tokens,
                        event.reasoning_output_tokens,
                        event.total_tokens,
                        event.running_total_tokens,
                        str(path),
                        line_offset,
                    ),
                )
                if cursor.rowcount > 0:
                    imported += 1
                con.execute(
                    "update sessions set total_tokens = max(total_tokens, ?), updated_at_ms = max(updated_at_ms, ?) where id = ?",
                    (event.running_total_tokens, event.timestamp_ms, session_pk),
                )
    _set_offset(con, source_key, new_offset)
    return imported


def sync_codex_once(
    *,
    db_path: Path | str | None = None,
    codex_home: Path | str | None = None,
    transcript_path: Path | str | None = None,
    hook_context: dict | None = None,
) -> SyncResult:
    db = Path(db_path).expanduser() if db_path else default_db_path()
    home = Path(codex_home).expanduser() if codex_home else default_codex_home()
    threads = _load_threads(home)
    session_by_path: dict[Path, int] = {}
    sessions_imported = 0
    events_imported = 0

    with connect(db) as con:
        init_db(con)
        for row in threads:
            session_id = str(_value(row, "id"))
            path = _path_from_value(_value(row, "rollout_path"), home)
            created_at_ms = _int(_value(row, "created_at")) * 1000 or now_ms()
            updated_at_ms = _int(_value(row, "updated_at")) * 1000 or created_at_ms
            session_pk = upsert_session(
                con,
                provider="codex",
                session_id=session_id,
                cwd=str(_value(row, "cwd", Path.cwd())),
                transcript_path=path,
                model=str(_value(row, "model")) if _value(row, "model") else None,
                model_provider=str(_value(row, "model_provider")) if _value(row, "model_provider") else "openai",
                source=str(_value(row, "source")) if _value(row, "source") else None,
                git_sha=str(_value(row, "git_sha")) if _value(row, "git_sha") else None,
                git_branch=str(_value(row, "git_branch")) if _value(row, "git_branch") else None,
                git_origin_url=str(_value(row, "git_origin_url")) if _value(row, "git_origin_url") else None,
                created_at_ms=created_at_ms,
                updated_at_ms=updated_at_ms,
                total_tokens=_int(_value(row, "tokens_used")),
                probe_git=False,
            )
            sessions_imported += 1
            if path:
                session_by_path[path] = session_pk

        if hook_context and hook_context.get("session_id"):
            path = _path_from_value(hook_context.get("transcript_path"), home)
            existing = con.execute(
                "select id from sessions where provider = 'codex' and session_id = ?",
                (str(hook_context["session_id"]),),
            ).fetchone()
            if existing:
                session_pk = int(existing["id"])
            else:
                session_pk = upsert_session(
                    con,
                    provider="codex",
                    session_id=str(hook_context["session_id"]),
                    cwd=str(hook_context.get("cwd") or Path.cwd()),
                    transcript_path=path,
                    model=str(hook_context.get("model")) if hook_context.get("model") else None,
                    model_provider="openai",
                    source="hook",
                    git_sha=None,
                    git_branch=None,
                    git_origin_url=None,
                    created_at_ms=now_ms(),
                    updated_at_ms=now_ms(),
                    total_tokens=0,
                )
                sessions_imported += 1
            if path:
                session_by_path[path] = session_pk

        explicit = _path_from_value(transcript_path, home)
        if explicit and explicit not in session_by_path:
            session_pk = upsert_session(
                con,
                provider="codex",
                session_id=(str(hook_context.get("session_id")) if hook_context else _derived_session_id(explicit)),
                cwd=str((hook_context or {}).get("cwd") or Path.cwd()),
                transcript_path=explicit,
                model=str((hook_context or {}).get("model")) if (hook_context or {}).get("model") else None,
                model_provider="openai",
                source="transcript",
                git_sha=None,
                git_branch=None,
                git_origin_url=None,
                created_at_ms=now_ms(),
                updated_at_ms=now_ms(),
                total_tokens=0,
            )
            session_by_path[explicit] = session_pk

        if not transcript_path and not session_by_path:
            for path in _scan_transcripts(home):
                session_pk = upsert_session(
                    con,
                    provider="codex",
                    session_id=_derived_session_id(path),
                    cwd=Path.cwd(),
                    transcript_path=path,
                    model=None,
                    model_provider="openai",
                    source="transcript-scan",
                    git_sha=None,
                    git_branch=None,
                    git_origin_url=None,
                    created_at_ms=now_ms(),
                    updated_at_ms=now_ms(),
                    total_tokens=0,
                )
                session_by_path[path] = session_pk

        for path, session_pk in session_by_path.items():
            events_imported += _import_transcript(con, session_pk=session_pk, path=path)

        con.commit()

    return SyncResult(sessions_imported=sessions_imported, token_events_imported=events_imported)


def ingest_codex_exec_line(
    db_path: Path | str,
    line: str,
    *,
    cwd: Path | str,
    state: ExecIngestState | None = None,
    model: str | None = None,
) -> ExecIngestState:
    current = state or ExecIngestState()
    try:
        raw_event = json.loads(line)
    except json.JSONDecodeError:
        return current

    session_id = str(raw_event.get("thread_id") or current.session_id)
    seen_ms = parse_timestamp_ms(raw_event.get("timestamp")) if raw_event.get("timestamp") else now_ms()
    with connect(db_path) as con:
        init_db(con)
        session_pk = upsert_session(
            con,
            provider="codex",
            session_id=session_id,
            cwd=cwd,
            transcript_path=None,
            model=model,
            model_provider="openai",
            source="codex-exec",
            git_sha=None,
            git_branch=None,
            git_origin_url=None,
            created_at_ms=seen_ms,
            updated_at_ms=seen_ms,
            total_tokens=0,
        )
        sequence = current.sequence or _max_sequence(con, session_pk)
        for event in parse_codex_token_events([line]):
            sequence += 1
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
                    event.timestamp_ms,
                    event.input_tokens,
                    event.cached_input_tokens,
                    event.cache_creation_input_tokens,
                    event.cache_creation_1h_input_tokens,
                    event.output_tokens,
                    event.reasoning_output_tokens,
                    event.total_tokens,
                    event.running_total_tokens,
                    "codex-exec",
                    sequence,
                ),
            )
            if cursor.rowcount > 0:
                con.execute(
                    "update sessions set total_tokens = max(total_tokens, ?), updated_at_ms = max(updated_at_ms, ?) where id = ?",
                    (event.running_total_tokens, event.timestamp_ms, session_pk),
                )
        con.commit()
    return ExecIngestState(session_id=session_id, sequence=sequence)
