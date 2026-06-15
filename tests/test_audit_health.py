import json
from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from aikeeper.audit import audit_privacy
from aikeeper.cli import app
from aikeeper.db import connect, init_db
from aikeeper.health import ingest_health
from aikeeper.web import create_app


NOW = 1_781_000_000_000


def seed_health_usage(db_path: Path, cwd: Path, transcript: Path) -> None:
    with connect(db_path) as con:
        init_db(con)
        con.execute(
            "insert into projects(root_path, name, git_origin, first_seen_ms, last_seen_ms) values (?, ?, ?, ?, ?)",
            (str(cwd), "repo", None, NOW, NOW),
        )
        project_id = con.execute("select id from projects").fetchone()[0]
        con.execute(
            """
            insert into tasks(project_id, task_key, source, git_branch, issue_id, display_name, first_seen_ms, last_seen_ms)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (project_id, "main", "git_branch", "main", None, "main", NOW, NOW),
        )
        task_id = con.execute("select id from tasks").fetchone()[0]
        sessions = [
            ("codex-ok", str(transcript), "gpt-5.5", NOW),
            ("codex-missing", str(transcript.with_name("missing.jsonl")), "unknown-model", NOW - 90_000_000),
        ]
        for session_id, transcript_path, model, updated_at_ms in sessions:
            con.execute(
                """
                insert into sessions(
                    provider, session_id, transcript_path, cwd, model, model_provider,
                    source, project_id, task_id, git_sha, git_branch, git_origin_url,
                    created_at_ms, updated_at_ms, total_tokens, last_seen_ms
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "codex",
                    session_id,
                    transcript_path,
                    str(cwd),
                    model,
                    "openai",
                    "test",
                    project_id,
                    task_id,
                    "abc123",
                    "main",
                    None,
                    updated_at_ms - 1_000,
                    updated_at_ms,
                    300,
                    updated_at_ms,
                ),
            )
        session_pk = con.execute("select id from sessions where session_id = 'codex-ok'").fetchone()[0]
        con.execute(
            """
            insert into token_events(
                session_pk, sequence, timestamp_ms, input_tokens, cached_input_tokens,
                output_tokens, reasoning_output_tokens, total_tokens,
                running_total_tokens, source_path, source_offset
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_pk, 1, NOW, 200, 50, 100, 0, 300, 300, str(transcript), 120),
        )
        con.execute(
            """
            insert into ingest_state(source_key, last_offset, updated_at_ms, meta_json)
            values (?, ?, ?, ?), (?, ?, ?, ?)
            """,
            (
                f"codex-transcript:{transcript}",
                1,
                NOW,
                "{}",
                f"codex-transcript:{transcript.with_name('missing.jsonl')}",
                240,
                NOW - 90_000_000,
                "{}",
            ),
        )


def test_privacy_audit_passes_metadata_only_database(tmp_path: Path) -> None:
    db_path = tmp_path / "keeper.sqlite"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    transcript = tmp_path / "session.jsonl"
    transcript.write_text('{"message":"SECRET_TRANSCRIPT_TEXT"}\n', encoding="utf-8")
    seed_health_usage(db_path, cwd, transcript)

    result = audit_privacy(db_path)

    assert result["status"] == "pass"
    assert result["metadata_only"] is True
    assert result["findings"] == []
    assert result["tables_checked"] >= 5
    assert result["text_columns_checked"] > 0
    assert b"SECRET_TRANSCRIPT_TEXT" not in db_path.read_bytes()


def test_privacy_audit_fails_without_echoing_sensitive_value(tmp_path: Path) -> None:
    db_path = tmp_path / "keeper.sqlite"
    with connect(db_path) as con:
        init_db(con)
        con.execute("create table bad_leak(id integer primary key, prompt text)")
        con.execute("insert into bad_leak(prompt) values (?)", ("SECRET_PROMPT_FROM_TEST",))

    result = audit_privacy(db_path)
    serialized = json.dumps(result)

    assert result["status"] == "fail"
    assert result["metadata_only"] is False
    assert result["findings"]
    assert "bad_leak" in serialized
    assert "prompt" in serialized
    assert "SECRET_PROMPT_FROM_TEST" not in serialized


def test_ingest_health_reports_missing_sources_and_quality_counts(tmp_path: Path) -> None:
    db_path = tmp_path / "keeper.sqlite"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    seed_health_usage(db_path, cwd, transcript)

    result = ingest_health(db_path, now_ms=NOW + 10_000)

    assert result["status"] == "warn"
    assert result["sessions"]["total"] == 2
    assert result["sessions"]["by_provider"] == {"codex": 2}
    assert result["token_events"]["total"] == 1
    assert result["transcripts"]["tracked"] == 2
    assert result["transcripts"]["missing"] == 1
    assert result["ingest_state"]["sources"] == 2
    assert result["ingest_state"]["stale_sources"] == 1
    assert result["models"]["unpriced"] == ["unknown-model"]


def test_cli_audit_and_health_commands_emit_json(tmp_path: Path) -> None:
    db_path = tmp_path / "keeper.sqlite"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    seed_health_usage(db_path, cwd, transcript)
    runner = CliRunner()

    audit_result = runner.invoke(app, ["audit", "privacy", "--db-path", str(db_path), "--json"])
    health_result = runner.invoke(app, ["health", "ingest", "--db-path", str(db_path), "--json"])

    assert audit_result.exit_code == 0
    assert json.loads(audit_result.stdout)["status"] == "pass"
    assert health_result.exit_code == 0
    assert json.loads(health_result.stdout)["transcripts"]["missing"] == 1


def test_web_exposes_ingest_health_and_privacy_audit(tmp_path: Path) -> None:
    db_path = tmp_path / "keeper.sqlite"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    seed_health_usage(db_path, cwd, transcript)
    client = TestClient(create_app(db_path=db_path))

    health = client.get("/api/health/ingest")
    audit = client.get("/api/audit/privacy")
    page = client.get("/")

    assert health.status_code == 200
    assert health.json()["transcripts"]["missing"] == 1
    assert audit.status_code == 200
    assert audit.json()["metadata_only"] is True
    assert "Ingest Health" in page.text
    assert "Privacy Audit" in page.text
