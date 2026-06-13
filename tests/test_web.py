import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from aikeeper.db import connect, init_db
from aikeeper.web import create_app


def seed_usage(db_path: Path, cwd: Path) -> None:
    with connect(db_path) as con:
        init_db(con)
        now = 1_781_000_000_000
        con.execute(
            "insert into projects(root_path, name, git_origin, first_seen_ms, last_seen_ms) values (?, ?, ?, ?, ?)",
            (str(cwd), "repo", None, now, now),
        )
        project_id = con.execute("select id from projects").fetchone()[0]
        con.execute(
            """
            insert into tasks(project_id, task_key, source, git_branch, issue_id, display_name, first_seen_ms, last_seen_ms)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (project_id, "AIK-7", "git_branch", "feature/AIK-7-ui", "AIK-7", "AIK-7", now, now),
        )
        task_id = con.execute("select id from tasks").fetchone()[0]
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
                "session-1",
                "/tmp/rollout.jsonl",
                str(cwd),
                "gpt-5.5",
                "openai",
                "vscode",
                project_id,
                task_id,
                "abc123",
                "feature/AIK-7-ui",
                None,
                now,
                now,
                300,
                now,
            ),
        )
        session_pk = con.execute("select id from sessions").fetchone()[0]
        con.execute(
            """
            insert into token_events(
                session_pk, sequence, timestamp_ms, input_tokens, cached_input_tokens,
                output_tokens, reasoning_output_tokens, total_tokens,
                running_total_tokens, source_path, source_offset
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_pk, 1, now, 200, 50, 100, 10, 300, 300, "/tmp/rollout.jsonl", 120),
        )


def test_web_overview_api_and_pages_render_usage(tmp_path: Path) -> None:
    db_path = tmp_path / "keeper.sqlite"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    seed_usage(db_path, cwd)
    app = create_app(db_path=db_path)
    client = TestClient(app)

    overview = client.get("/api/overview").json()
    page = client.get("/")
    project_page = client.get("/projects/1")
    session_page = client.get("/sessions/1")

    assert overview["total_tokens"] == 300
    assert page.status_code == 200
    assert "AI Keeper" in page.text
    assert "repo" in page.text
    assert "AIK-7" in project_page.text
    assert "gpt-5.5" in session_page.text
    assert json.dumps(overview)
