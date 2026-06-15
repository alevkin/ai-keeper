from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from aikeeper.db import connect, init_db


ALLOWED_TEXT_COLUMNS = {
    "api_key_ref",
    "currency",
    "cwd",
    "display_name",
    "git_branch",
    "git_origin",
    "git_origin_url",
    "git_sha",
    "issue_id",
    "line_item",
    "meta_json",
    "model",
    "model_provider",
    "name",
    "project_ref",
    "provider",
    "raw_json",
    "root_path",
    "session_id",
    "source",
    "source_key",
    "source_path",
    "task_key",
    "transcript_path",
}

FORBIDDEN_COLUMN_NAMES = {
    "assistant",
    "body",
    "completion",
    "content",
    "message",
    "messages",
    "prompt",
    "request",
    "response",
    "raw_transcript",
    "text",
    "transcript_json",
}

FORBIDDEN_COLUMN_FRAGMENTS = (
    "assistant_message",
    "chat_content",
    "completion_text",
    "prompt_text",
    "raw_message",
    "raw_prompt",
    "raw_response",
)

SENSITIVE_SENTINELS = (
    "secret_prompt",
    "secret_claude_text",
    "secret_transcript_text",
)


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _is_text_column(declared_type: str | None) -> bool:
    lowered = (declared_type or "").lower()
    if not lowered:
        return True
    return any(fragment in lowered for fragment in ("char", "clob", "json", "text", "varchar"))


def _table_names(con: sqlite3.Connection) -> list[str]:
    rows = con.execute(
        """
        select name
        from sqlite_master
        where type = 'table' and name not like 'sqlite_%'
        order by name asc
        """
    ).fetchall()
    return [str(row["name"]) for row in rows]


def _column_is_forbidden(column: str) -> bool:
    lowered = column.lower()
    if lowered in ALLOWED_TEXT_COLUMNS:
        return False
    if lowered in FORBIDDEN_COLUMN_NAMES:
        return True
    return any(fragment in lowered for fragment in FORBIDDEN_COLUMN_FRAGMENTS)


def _value_looks_like_chat_text(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    lowered = value.lower()
    if any(sentinel in lowered for sentinel in SENSITIVE_SENTINELS):
        return True

    # A local database should not contain raw Chat/JSONL message payloads.
    # Keep the heuristic conservative so aggregate metadata JSON is not flagged.
    if len(value) < 20:
        return False
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return False
    if not isinstance(decoded, dict):
        return False
    keys = {str(key).lower() for key in decoded}
    if {"role", "content"} <= keys:
        return True
    if "message" in keys and any(key in keys for key in {"content", "role", "messages"}):
        return True
    message = decoded.get("message")
    if isinstance(message, dict) and any(key in message for key in ("content", "text", "role")):
        return True
    return False


def _append_finding(findings: list[dict], *, table: str, column: str, reason: str, rowid: int | None = None) -> None:
    finding = {"table": table, "column": column, "reason": reason}
    if rowid is not None:
        finding["rowid"] = rowid
    findings.append(finding)


def audit_privacy(db_path: Path | str) -> dict:
    with connect(db_path) as con:
        init_db(con)
        findings: list[dict] = []
        tables = _table_names(con)
        text_columns_checked = 0
        allowed_columns: set[str] = set()

        for table in tables:
            columns = con.execute(f"pragma table_info({_quote_identifier(table)})").fetchall()
            for column in columns:
                column_name = str(column["name"])
                if not _is_text_column(column["type"]):
                    continue
                text_columns_checked += 1
                if column_name.lower() in ALLOWED_TEXT_COLUMNS:
                    allowed_columns.add(column_name)
                if _column_is_forbidden(column_name):
                    _append_finding(
                        findings,
                        table=table,
                        column=column_name,
                        reason="column name can store chat text",
                    )

                table_sql = _quote_identifier(table)
                column_sql = _quote_identifier(column_name)
                rows = con.execute(
                    f"""
                    select rowid as rowid, {column_sql} as value
                    from {table_sql}
                    where {column_sql} is not null
                    limit 500
                    """
                ).fetchall()
                for row in rows:
                    if _value_looks_like_chat_text(row["value"]):
                        _append_finding(
                            findings,
                            table=table,
                            column=column_name,
                            rowid=int(row["rowid"]),
                            reason="value resembles raw chat content",
                        )
                        break

    return {
        "status": "pass" if not findings else "fail",
        "metadata_only": not findings,
        "tables_checked": len(tables),
        "text_columns_checked": text_columns_checked,
        "allowed_text_columns": sorted(allowed_columns),
        "findings": findings,
    }
