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


def test_overview_exposes_live_burn_rate_and_model_efficiency(tmp_path: Path) -> None:
    db_path = tmp_path / "keeper.sqlite"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    now = 1_781_000_000_000
    with connect(db_path) as con:
        init_db(con)
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
            (project_id, "main", "git_branch", "main", None, "main", now, now),
        )
        task_id = con.execute("select id from tasks").fetchone()[0]
        for session_id, model, updated_at in (
            ("session-fast", "gpt-5.5", now),
            ("session-codex", "gpt-5.3-codex", now - 600_000),
        ):
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
                    f"/tmp/{session_id}.jsonl",
                    str(cwd),
                    model,
                    "openai",
                    "test",
                    project_id,
                    task_id,
                    "abc123",
                    "main",
                    None,
                    updated_at - 240_000,
                    updated_at,
                    0,
                    updated_at,
                ),
            )
        fast_pk = con.execute("select id from sessions where session_id = 'session-fast'").fetchone()[0]
        codex_pk = con.execute("select id from sessions where session_id = 'session-codex'").fetchone()[0]
        events = [
            (fast_pk, 1, now - 240_000, 100, 20, 50, 150, 150),
            (fast_pk, 2, now - 180_000, 100, 50, 50, 150, 300),
            (fast_pk, 3, now - 30_000, 200, 0, 100, 300, 600),
            (codex_pk, 1, now - 120_000, 100, 50, 100, 200, 200),
            (codex_pk, 2, now - 90_000, 100, 100, 100, 200, 400),
        ]
        for session_pk, sequence, timestamp_ms, input_tokens, cached_input_tokens, output_tokens, total_tokens, running in events:
            con.execute(
                """
                insert into token_events(
                    session_pk, sequence, timestamp_ms, input_tokens, cached_input_tokens,
                    output_tokens, reasoning_output_tokens, total_tokens,
                    running_total_tokens, source_path, source_offset
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_pk,
                    sequence,
                    timestamp_ms,
                    input_tokens,
                    cached_input_tokens,
                    output_tokens,
                    0,
                    total_tokens,
                    running,
                    f"/tmp/{session_pk}.jsonl",
                    sequence * 100,
                ),
            )
        con.execute("update sessions set total_tokens = 600 where id = ?", (fast_pk,))
        con.execute("update sessions set total_tokens = 400 where id = ?", (codex_pk,))

    data = build_overview(db_path, now_ms=now)

    assert data["burn_rate"]["active_window_ms"] == 600_000
    assert data["burn_rate"]["idle_gap_ms"] == 120_000
    assert data["burn_rate"]["current"]["session_id"] == "session-fast"
    assert data["burn_rate"]["current"]["tokens"] == 600
    assert data["burn_rate"]["current"]["active_ms"] == 180_000
    assert data["burn_rate"]["current"]["tokens_per_minute"] == pytest.approx(200)
    assert data["burn_rate"]["current"]["usd_per_minute"] > 0
    model_rows = {row["model"]: row for row in data["model_efficiency"]}
    assert model_rows["gpt-5.5"]["total_tokens"] == 600
    assert model_rows["gpt-5.5"]["event_count"] == 3
    assert model_rows["gpt-5.5"]["cached_input_ratio"] == pytest.approx(0.175)
    assert model_rows["gpt-5.5"]["tokens_per_minute"] == pytest.approx(200)
    assert model_rows["gpt-5.3-codex"]["session_count"] == 1
    assert model_rows["gpt-5.3-codex"]["estimated_cost_usd"] > 0


def test_overview_exposes_budget_warnings_from_config(tmp_path: Path) -> None:
    db_path = tmp_path / "keeper.sqlite"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    seed_usage(db_path, cwd)
    budget_path = tmp_path / "budgets.toml"
    budget_path.write_text(
        """
        [defaults]
        warn_at = 0.8
        project_daily_usd = 0.003
        task_daily_usd = 0.003
        session_usd = 0.003
        turn_usd = 0.003
        project_daily_tokens = 250
        """,
        encoding="utf-8",
    )

    data = build_overview(db_path, now_ms=1_781_000_000_000, budget_path=budget_path)

    assert data["budget"]["configured"] is True
    warnings = data["budget_warnings"]
    assert warnings
    labels = {warning["label"] for warning in warnings}
    assert "project daily USD" in labels
    assert "project daily tokens" in labels
    project_usd = next(warning for warning in warnings if warning["label"] == "project daily USD")
    assert project_usd["severity"] == "over"
    assert project_usd["used"] == pytest.approx(0.003775)
    assert project_usd["limit"] == pytest.approx(0.003)
    assert project_usd["ratio"] > 1


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


def test_overview_page_renders_budget_guards(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "keeper.sqlite"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    seed_usage(db_path, cwd)
    budget_path = tmp_path / "budgets.toml"
    budget_path.write_text("[defaults]\nturn_usd = 0.003\n", encoding="utf-8")
    monkeypatch.setattr("aikeeper.web.get_app_version", lambda: {"label": "v9.9.9", "commit": "abc123"})
    app = create_app(db_path=db_path, budget_path=budget_path)
    client = TestClient(app)

    page = client.get("/")

    assert "Budget Guards" in page.text
    assert "turn USD" in page.text
    assert "$0.0038" in page.text
    assert "$0.0030" in page.text


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
    assert "Active rate" in page.text
    assert "Model Efficiency" in page.text
