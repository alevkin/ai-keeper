from __future__ import annotations

import json
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
    usage: TokenUsageEvent

    @property
    def total_tokens(self) -> int:
        return self.usage.total_tokens

    @property
    def cached_input_tokens(self) -> int:
        return self.usage.cached_input_tokens


def _int(value: object) -> int:
    return int(value) if isinstance(value, int | float) else 0


def _usage_from_message(raw: dict) -> dict:
    message = raw.get("message") if isinstance(raw.get("message"), dict) else {}
    usage = message.get("usage") if isinstance(message.get("usage"), dict) else raw.get("usage")
    return usage if isinstance(usage, dict) else {}


def parse_claude_token_events(lines: Iterable[str]) -> Iterable[ClaudeEvent]:
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
        input_tokens = _int(usage.get("input_tokens"))
        cached_input = _int(usage.get("cache_read_input_tokens")) + _int(usage.get("cached_input_tokens"))
        output_tokens = _int(usage.get("output_tokens"))
        total_tokens = _int(usage.get("total_tokens")) or input_tokens + output_tokens
        session_id = str(raw.get("sessionId") or raw.get("session_id") or raw.get("uuid") or "claude-session")
        cwd = str(raw.get("cwd") or Path.cwd())
        model = raw.get("model") or (raw.get("message") or {}).get("model") if isinstance(raw.get("message"), dict) else raw.get("model")
        yield ClaudeEvent(
            session_id=session_id,
            cwd=cwd,
            model=str(model) if model else None,
            usage=TokenUsageEvent(
                timestamp_ms=parse_timestamp_ms(raw.get("timestamp")),
                input_tokens=input_tokens,
                cached_input_tokens=cached_input,
                output_tokens=output_tokens,
                reasoning_output_tokens=0,
                total_tokens=total_tokens,
                running_total_tokens=total_tokens,
            ),
        )


def _scan_claude_transcripts(claude_home: Path) -> list[Path]:
    root = claude_home / "projects"
    return sorted(root.rglob("*.jsonl")) if root.exists() else []


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
        seen_sessions = set()
        for path in _scan_claude_transcripts(home):
            sequence_by_session: dict[str, int] = {}
            with path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    events = parse_claude_token_events([line])
                    for event in events:
                        existing = con.execute(
                            "select 1 from token_events where source_path = ? and source_offset = ?",
                            (str(path), line_number),
                        ).fetchone()
                        if existing:
                            continue
                        if event.session_id not in seen_sessions:
                            sessions_imported += 1
                            seen_sessions.add(event.session_id)
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
                            git_branch=None,
                            git_origin_url=None,
                            created_at_ms=event.usage.timestamp_ms,
                            updated_at_ms=event.usage.timestamp_ms,
                            total_tokens=0,
                        )
                        sequence = sequence_by_session.get(event.session_id)
                        if sequence is None:
                            row = con.execute(
                                "select coalesce(max(sequence), 0) as seq from token_events where session_pk = ?",
                                (session_pk,),
                            ).fetchone()
                            sequence = int(row["seq"])
                        sequence += 1
                        sequence_by_session[event.session_id] = sequence
                        cursor = con.execute(
                            """
                            insert or ignore into token_events(
                                session_pk, sequence, timestamp_ms, input_tokens, cached_input_tokens,
                                output_tokens, reasoning_output_tokens, total_tokens,
                                running_total_tokens, source_path, source_offset
                            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                session_pk,
                                sequence,
                                event.usage.timestamp_ms,
                                event.usage.input_tokens,
                                event.usage.cached_input_tokens,
                                event.usage.output_tokens,
                                0,
                                event.usage.total_tokens,
                                event.usage.running_total_tokens,
                                str(path),
                                line_number,
                            ),
                        )
                        if cursor.rowcount > 0:
                            events_imported += 1
                            con.execute(
                                "update sessions set total_tokens = total_tokens + ?, updated_at_ms = max(updated_at_ms, ?) where id = ?",
                                (event.usage.total_tokens, event.usage.timestamp_ms, session_pk),
                            )
        con.commit()
    return SyncResult(sessions_imported=sessions_imported, token_events_imported=events_imported)
