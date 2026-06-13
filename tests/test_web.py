import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aikeeper.db import connect, init_db
from aikeeper.service import overview as build_overview
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


def test_overview_exposes_v2_dashboard_metadata(tmp_path: Path) -> None:
    db_path = tmp_path / "keeper.sqlite"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    seed_usage(db_path, cwd)
    now = 1_781_000_000_000

    data = build_overview(db_path, now_ms=now)

    assert data["current_activity"]["session_id"] == "session-1"
    assert data["current_activity"]["project_name"] == "repo"
    assert data["current_activity"]["task_name"] == "AIK-7"
    assert data["current_activity"]["last_turn_tokens"] == 300
    assert len(data["daily_tokens"]) == 7
    assert data["daily_tokens"][-1]["tokens"] == 300
    assert data["daily_tokens"][-1]["estimated_cost_usd"] == pytest.approx(0.003775)
    assert data["estimated_cost"]["today_usd"] == pytest.approx(0.003775)
    assert data["current_activity"]["last_turn_cost_usd"] == pytest.approx(0.003775)
    assert data["projects"][0]["estimated_cost_usd"] == pytest.approx(0.003775)
    assert data["generated_at_ms"] == now


def test_overview_page_renders_version_and_current_activity(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "keeper.sqlite"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    seed_usage(db_path, cwd)
    monkeypatch.setattr("aikeeper.web.get_app_version", lambda: {"label": "v9.9.9", "commit": "abc123"})
    app = create_app(db_path=db_path)
    client = TestClient(app)

    page = client.get("/")

    assert "v9.9.9" in page.text
    assert "Current activity" in page.text
    assert "Estimated spend" in page.text
    assert "$0.0038" in page.text
    assert "session-1" in page.text
    assert "7-day trend" in page.text
