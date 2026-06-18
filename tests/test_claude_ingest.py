import json
from pathlib import Path

from typer.testing import CliRunner

from aikeeper.claude import parse_claude_token_events, sync_claude_once
from aikeeper.cli import app
from aikeeper.db import connect, init_db
from aikeeper.service import overview as build_overview


def append_claude_line(
    path: Path,
    *,
    timestamp: str,
    input_tokens: int,
    cache_read_input_tokens: int,
    cache_creation_5m_input_tokens: int,
    cache_creation_1h_input_tokens: int = 0,
    output_tokens: int,
    content: str = "SECRET_CLAUDE_TEXT",
) -> None:
    event = {
        "sessionId": "claude-session-1",
        "cwd": str(path.parents[3] / "repo"),
        "gitBranch": "feature/AK-10-claude",
        "timestamp": timestamp,
        "type": "assistant",
        "message": {
            "model": "claude-sonnet-4-6",
            "role": "assistant",
            "content": content,
            "usage": {
                "input_tokens": input_tokens,
                "cache_read_input_tokens": cache_read_input_tokens,
                "cache_creation_input_tokens": cache_creation_5m_input_tokens + cache_creation_1h_input_tokens,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": cache_creation_5m_input_tokens,
                    "ephemeral_1h_input_tokens": cache_creation_1h_input_tokens,
                },
                "output_tokens": output_tokens,
            },
        },
    }
    with path.open("ab") as handle:
        handle.write(json.dumps(event).encode("utf-8") + b"\n")


def test_parse_claude_usage_includes_cache_read_and_write_tokens(tmp_path: Path) -> None:
    line = json.dumps(
        {
            "sessionId": "claude-session-1",
            "cwd": str(tmp_path),
            "timestamp": "2026-06-12T16:34:53.333Z",
            "message": {
                "model": "claude-sonnet-4-6",
                "usage": {
                    "input_tokens": 3,
                    "cache_creation_input_tokens": 7_241,
                    "cache_creation": {
                        "ephemeral_5m_input_tokens": 7_000,
                        "ephemeral_1h_input_tokens": 241,
                    },
                    "cache_read_input_tokens": 17_946,
                    "output_tokens": 8,
                },
                "content": "SECRET_CLAUDE_TEXT",
            },
        }
    )

    parsed = list(parse_claude_token_events([line]))

    assert parsed[0].session_id == "claude-session-1"
    assert parsed[0].model == "claude-sonnet-4-6"
    assert parsed[0].usage.input_tokens == 3
    assert parsed[0].usage.cached_input_tokens == 17_946
    assert parsed[0].usage.cache_creation_input_tokens == 7_000
    assert parsed[0].usage.cache_creation_1h_input_tokens == 241
    assert parsed[0].total_tokens == 25_198


def test_sync_claude_imports_metadata_only_and_deduplicates_by_offset(tmp_path: Path) -> None:
    claude_home = tmp_path / "claude"
    project_dir = claude_home / "projects" / "-tmp-repo"
    project_dir.mkdir(parents=True)
    (tmp_path / "repo").mkdir()
    transcript = project_dir / "claude-session-1.jsonl"
    append_claude_line(
        transcript,
        timestamp="2026-06-12T16:34:53.333Z",
        input_tokens=3,
        cache_creation_5m_input_tokens=7_000,
        cache_creation_1h_input_tokens=241,
        cache_read_input_tokens=17_946,
        output_tokens=8,
    )
    append_claude_line(
        transcript,
        timestamp="2026-06-12T16:35:53.333Z",
        input_tokens=100,
        cache_creation_5m_input_tokens=0,
        cache_read_input_tokens=5_000,
        output_tokens=50,
        content="SECOND_SECRET_CLAUDE_TEXT",
    )
    with transcript.open("ab") as handle:
        handle.write(b'{"sessionId":"claude-session-1","message":')

    db_path = tmp_path / "keeper.sqlite"
    with connect(db_path) as con:
        init_db(con)

    first = sync_claude_once(db_path=db_path, claude_home=claude_home)
    second = sync_claude_once(db_path=db_path, claude_home=claude_home)
    with transcript.open("ab") as handle:
        handle.write(
            json.dumps(
                {
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                    "model": "claude-sonnet-4-6",
                    "content": "PARTIAL_SECRET",
                }
            ).encode("utf-8")
            + b"}\n"
        )
    third = sync_claude_once(db_path=db_path, claude_home=claude_home)

    assert first.sessions_imported == 1
    assert first.token_events_imported == 2
    assert second.token_events_imported == 0
    assert third.token_events_imported == 1

    with connect(db_path) as con:
        session = con.execute("select * from sessions where provider = 'claude'").fetchone()
        events = con.execute("select * from token_events where session_pk = ? order by sequence", (session["id"],)).fetchall()
        ingest = con.execute("select * from ingest_state where source_key = ?", (f"claude-transcript:{transcript}",)).fetchone()
        data = build_overview(db_path, now_ms=1_781_282_500_000)

    assert session["session_id"] == "claude-session-1"
    assert session["model"] == "claude-sonnet-4-6"
    assert session["model_provider"] == "anthropic"
    assert session["source"] == "claude-jsonl"
    assert session["git_branch"] == "feature/AK-10-claude"
    assert session["total_tokens"] == 30_350
    assert events[0]["input_tokens"] == 3
    assert events[0]["cached_input_tokens"] == 17_946
    assert events[0]["cache_creation_input_tokens"] == 7_000
    assert events[0]["cache_creation_1h_input_tokens"] == 241
    assert events[0]["total_tokens"] == 25_198
    assert events[0]["running_total_tokens"] == 25_198
    assert events[1]["running_total_tokens"] == 30_348
    assert events[2]["running_total_tokens"] == 30_350
    assert ingest["last_offset"] == transcript.stat().st_size
    assert data["estimated_cost"]["total_usd"] > 0
    assert "claude-sonnet-4-6" not in data["estimated_cost"]["unpriced_models"]
    db_bytes = db_path.read_bytes()
    assert b"SECRET_CLAUDE_TEXT" not in db_bytes
    assert b"SECOND_SECRET_CLAUDE_TEXT" not in db_bytes
    assert b"PARTIAL_SECRET" not in db_bytes


def test_sync_claude_does_not_probe_project_cwd_git_metadata(tmp_path: Path, monkeypatch) -> None:
    claude_home = tmp_path / "claude"
    project_dir = claude_home / "projects" / "-Users-me-Documents-PrivateProject"
    project_dir.mkdir(parents=True)
    transcript = project_dir / "claude-session-1.jsonl"
    append_claude_line(
        transcript,
        timestamp="2026-06-12T16:34:53.333Z",
        input_tokens=10,
        cache_creation_5m_input_tokens=0,
        cache_read_input_tokens=20,
        output_tokens=5,
    )

    def fail_git_probe(_cwd: Path | str):
        raise AssertionError("background sync must not run git in project cwd")

    monkeypatch.setattr("aikeeper.storage.get_git_metadata", fail_git_probe)
    db_path = tmp_path / "keeper.sqlite"

    result = sync_claude_once(db_path=db_path, claude_home=claude_home)

    assert result.token_events_imported == 1
    with connect(db_path) as con:
        project = con.execute("select * from projects").fetchone()
    assert project["root_path"].endswith("/repo")


def test_cli_sync_claude_once(tmp_path: Path, monkeypatch) -> None:
    claude_home = tmp_path / "claude"
    project_dir = claude_home / "projects" / "-tmp-repo"
    project_dir.mkdir(parents=True)
    (tmp_path / "repo").mkdir()
    transcript = project_dir / "claude-session-1.jsonl"
    append_claude_line(
        transcript,
        timestamp="2026-06-12T16:34:53.333Z",
        input_tokens=10,
        cache_creation_5m_input_tokens=0,
        cache_read_input_tokens=20,
        output_tokens=5,
    )
    db_path = tmp_path / "keeper.sqlite"
    monkeypatch.setenv("CLAUDE_HOME", str(claude_home))
    runner = CliRunner()

    result = runner.invoke(app, ["sync", "claude", "--once", "--db-path", str(db_path)])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"sessions_imported": 1, "token_events_imported": 1}
