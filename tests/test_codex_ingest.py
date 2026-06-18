import json
import sqlite3
from pathlib import Path

from aikeeper.codex import ExecIngestState, ingest_codex_exec_line, parse_codex_token_events, sync_codex_once
from aikeeper.db import connect, init_db
from aikeeper.service import status_for_cwd


def write_state_db(codex_home: Path, rollout_path: Path, cwd: Path) -> str:
    state_db = codex_home / "state_5.sqlite"
    session_id = "019ebcaf-6c10-7642-9ab0-ccd8f6a1e8fe"
    with sqlite3.connect(state_db) as con:
        con.execute(
            """
            create table threads (
                id text primary key,
                rollout_path text not null,
                created_at integer not null,
                updated_at integer not null,
                source text not null,
                model_provider text not null,
                cwd text not null,
                title text not null,
                sandbox_policy text not null,
                approval_mode text not null,
                tokens_used integer not null default 0,
                git_sha text,
                git_branch text,
                git_origin_url text,
                cli_version text not null default '',
                first_user_message text not null default '',
                model text
            )
            """
        )
        con.execute(
            """
            insert into threads (
                id, rollout_path, created_at, updated_at, source,
                model_provider, cwd, title, sandbox_policy, approval_mode,
                tokens_used, git_sha, git_branch, git_origin_url,
                cli_version, first_user_message, model
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                str(rollout_path),
                1_780_000_000,
                1_780_000_100,
                "vscode",
                "openai",
                str(cwd),
                "Sensitive title should not be stored",
                "workspace-write",
                "never",
                48_297,
                "abc123",
                "feature/AIK-42-token-meter",
                "git@example.com:team/repo.git",
                "0.129.0",
                "SECRET_PROMPT_FROM_STATE",
                "gpt-5.5",
            ),
        )
    return session_id


def append_token_line(path: Path, timestamp: str, last_total: int, running_total: int) -> None:
    event = {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "last_token_usage": {
                    "input_tokens": last_total - 100,
                    "cached_input_tokens": 50,
                    "output_tokens": 100,
                    "reasoning_output_tokens": 40,
                    "total_tokens": last_total,
                },
                "total_token_usage": {
                    "input_tokens": running_total - 100,
                    "cached_input_tokens": 50,
                    "output_tokens": 100,
                    "reasoning_output_tokens": 40,
                    "total_tokens": running_total,
                },
            },
        },
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event) + "\n")


def test_parse_codex_rollout_and_exec_usage_events() -> None:
    rollout = {
        "timestamp": "2026-06-12T16:35:06.658Z",
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "last_token_usage": {
                    "input_tokens": 25761,
                    "cached_input_tokens": 4992,
                    "output_tokens": 662,
                    "reasoning_output_tokens": 238,
                    "total_tokens": 26423,
                },
                "total_token_usage": {"total_tokens": 48297},
            },
        },
    }
    exec_event = {
        "type": "turn.completed",
        "usage": {
            "input_tokens": 24763,
            "cached_input_tokens": 24448,
            "output_tokens": 122,
            "reasoning_output_tokens": 0,
        },
    }

    parsed = list(parse_codex_token_events([json.dumps(rollout), json.dumps(exec_event)]))

    assert parsed[0].total_tokens == 26423
    assert parsed[0].running_total_tokens == 48297
    assert parsed[1].total_tokens == 24885
    assert parsed[1].running_total_tokens == 24885


def test_sync_codex_imports_metadata_only_and_deduplicates_by_offset(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    cwd = tmp_path / "repo"
    cwd.mkdir()
    rollout = codex_home / "sessions" / "2026" / "06" / "12" / "rollout.jsonl"
    rollout.parent.mkdir(parents=True)
    append_token_line(rollout, "2026-06-12T16:34:53.333Z", 21_874, 21_874)
    append_token_line(rollout, "2026-06-12T16:35:06.658Z", 26_423, 48_297)
    session_id = write_state_db(codex_home, rollout, cwd)

    db_path = tmp_path / "keeper.sqlite"
    with connect(db_path) as con:
        init_db(con)

    first = sync_codex_once(db_path=db_path, codex_home=codex_home)
    second = sync_codex_once(db_path=db_path, codex_home=codex_home)
    append_token_line(rollout, "2026-06-12T16:35:33.117Z", 30_849, 79_146)
    third = sync_codex_once(db_path=db_path, codex_home=codex_home)

    assert first.token_events_imported == 2
    assert second.token_events_imported == 0
    assert third.token_events_imported == 1

    with connect(db_path) as con:
        assert con.execute("select count(*) from token_events").fetchone()[0] == 3
        session = con.execute("select * from sessions where session_id = ?", (session_id,)).fetchone()
        task = con.execute("select * from tasks where id = ?", (session["task_id"],)).fetchone()

    assert session["model"] == "gpt-5.5"
    assert session["total_tokens"] == 79_146
    assert task["issue_id"] == "AIK-42"
    assert task["task_key"] == "AIK-42"
    assert b"SECRET_PROMPT_FROM_STATE" not in db_path.read_bytes()
    assert b"Sensitive title should not be stored" not in db_path.read_bytes()


def test_sync_codex_does_not_probe_project_cwd_git_metadata(tmp_path: Path, monkeypatch) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    documents_cwd = tmp_path / "Documents" / "PrivateProject"
    documents_cwd.mkdir(parents=True)
    rollout = codex_home / "sessions" / "rollout.jsonl"
    rollout.parent.mkdir(parents=True, exist_ok=True)
    append_token_line(rollout, "2026-06-12T16:34:53.333Z", 100, 100)
    write_state_db(codex_home, rollout, documents_cwd)

    def fail_git_probe(_cwd: Path | str):
        raise AssertionError("background sync must not run git in project cwd")

    monkeypatch.setattr("aikeeper.storage.get_git_metadata", fail_git_probe)
    db_path = tmp_path / "keeper.sqlite"

    result = sync_codex_once(db_path=db_path, codex_home=codex_home)

    assert result.token_events_imported == 1
    with connect(db_path) as con:
        project = con.execute("select * from projects").fetchone()
    assert project["root_path"] == str(documents_cwd)


def test_status_for_cwd_groups_today_by_project_and_task(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    cwd = tmp_path / "repo"
    cwd.mkdir()
    rollout = codex_home / "sessions" / "rollout.jsonl"
    rollout.parent.mkdir(parents=True, exist_ok=True)
    append_token_line(rollout, "2026-06-12T16:34:53.333Z", 100, 100)
    write_state_db(codex_home, rollout, cwd)
    db_path = tmp_path / "keeper.sqlite"
    with connect(db_path) as con:
        init_db(con)
    sync_codex_once(db_path=db_path, codex_home=codex_home)

    status = status_for_cwd(db_path, cwd, now_ms=1_781_282_500_000)

    assert status["project"]["today_tokens"] == 100
    assert status["task"]["today_tokens"] == 100
    assert status["session"]["last_turn_tokens"] == 100
    assert status["session"]["total_tokens"] == 48_297


def test_ingest_codex_exec_json_stream_records_turn_usage(tmp_path: Path) -> None:
    db_path = tmp_path / "keeper.sqlite"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    with connect(db_path) as con:
        init_db(con)

    state = ingest_codex_exec_line(
        db_path,
        json.dumps({"type": "thread.started", "thread_id": "thread-123"}),
        cwd=cwd,
        state=ExecIngestState(),
    )
    state = ingest_codex_exec_line(
        db_path,
        json.dumps(
            {
                "type": "turn.completed",
                "timestamp": "2026-06-12T16:34:53.333Z",
                "usage": {
                    "input_tokens": 200,
                    "cached_input_tokens": 50,
                    "output_tokens": 25,
                    "reasoning_output_tokens": 5,
                },
            }
        ),
        cwd=cwd,
        state=state,
    )

    with connect(db_path) as con:
        session = con.execute("select * from sessions where session_id = 'thread-123'").fetchone()
        event = con.execute("select * from token_events where session_pk = ?", (session["id"],)).fetchone()

    assert state.session_id == "thread-123"
    assert session["source"] == "codex-exec"
    assert session["total_tokens"] == 225
    assert event["total_tokens"] == 225
    assert b"thread.started" not in db_path.read_bytes()
