import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aikeeper.budgets import load_budget_config_from_db, save_budget_settings
from aikeeper.db import connect, init_db
from aikeeper.service import overview as build_overview
from aikeeper.service import status_for_cwd
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
    trend = data["burn_rate"]["trend"]
    assert trend["bucket_ms"] == 60_000
    assert len(trend["points"]) == 10
    assert sum(point["tokens"] for point in trend["points"]) == 600
    assert trend["recent_tokens_per_minute"] > trend["previous_tokens_per_minute"]
    assert trend["direction"] == "up"
    model_rows = {row["model"]: row for row in data["model_efficiency"]}
    assert model_rows["gpt-5.5"]["total_tokens"] == 600
    assert model_rows["gpt-5.5"]["event_count"] == 3
    assert model_rows["gpt-5.5"]["cached_input_ratio"] == pytest.approx(0.175)
    assert model_rows["gpt-5.5"]["tokens_per_minute"] == pytest.approx(200)
    assert model_rows["gpt-5.3-codex"]["session_count"] == 1
    assert model_rows["gpt-5.3-codex"]["estimated_cost_usd"] > 0


def test_api_sync_claude_imports_local_metadata(tmp_path: Path) -> None:
    claude_home = tmp_path / "claude"
    project_dir = claude_home / "projects" / "-tmp-repo"
    project_dir.mkdir(parents=True)
    transcript = project_dir / "session.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "sessionId": "claude-session-1",
                "cwd": str(tmp_path / "repo"),
                "timestamp": "2026-06-12T16:34:53.333Z",
                "message": {
                    "model": "claude-sonnet-4-6",
                    "usage": {"input_tokens": 10, "cache_read_input_tokens": 20, "output_tokens": 5},
                    "content": "SECRET_CLAUDE_TEXT",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "repo").mkdir()
    db_path = tmp_path / "keeper.sqlite"
    client = TestClient(create_app(db_path=db_path, claude_home=claude_home))

    response = client.post("/api/sync/claude")

    assert response.status_code == 200
    assert response.json() == {"sessions_imported": 1, "token_events_imported": 1}
    with connect(db_path) as con:
        session = con.execute("select * from sessions where provider = 'claude'").fetchone()
    overview = client.get("/api/overview").json()
    page = client.get("/").text
    providers = {row["provider"]: row for row in overview["provider_totals"]}

    assert session["model_provider"] == "anthropic"
    assert providers["claude"]["session_count"] == 1
    assert providers["claude"]["event_count"] == 1
    assert providers["claude"]["total_tokens"] == 35
    assert "Providers" in page
    assert "claude" in page
    assert b"SECRET_CLAUDE_TEXT" not in db_path.read_bytes()


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

    ping = client.get("/api/ping")
    overview = client.get("/api/overview").json()
    page = client.get("/")
    project_page = client.get("/projects/1")
    session_page = client.get("/sessions/1")

    assert ping.status_code == 200
    assert ping.json()["service"] == "aikeeper"
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
    assert data["current_activity"]["provider"] == "codex"
    assert data["current_activity"]["project_name"] == "repo"
    assert data["current_activity"]["task_name"] == "AIK-7"
    assert data["current_activity"]["last_turn_tokens"] == 300
    assert len(data["daily_tokens"]) == 7
    assert data["daily_tokens"][-1]["tokens"] == 300
    assert data["daily_tokens"][-1]["estimated_cost_usd"] == pytest.approx(0.003775)
    assert data["estimated_cost"]["today_usd"] == pytest.approx(0.003775)
    assert data["current_activity"]["last_turn_cost_usd"] == pytest.approx(0.003775)
    assert data["projects"][0]["estimated_cost_usd"] == pytest.approx(0.003775)
    economics = data["task_economics"]
    assert economics["configured"] is True
    assert economics["task"]["key"] == "AIK-7"
    assert economics["spent"]["tokens"] == 300
    assert economics["spent"]["estimated_cost_usd"] == pytest.approx(0.003775)
    assert economics["projection_minutes"] == 30
    assert economics["projection"]["estimated_cost_usd"] >= economics["spent"]["estimated_cost_usd"]
    assert economics["baseline"]["sample_size"] == 0
    assert economics["status"] == "learning"
    assert economics["next_best_move"]["title"]
    assert len(economics["drivers"]) == 4
    assert economics["ledger"][0]["tokens"] == 300
    harness = data["workflow_harness"]
    assert harness["configured"] is True
    assert harness["status"] == "attention"
    assert harness["outcome_summary"]["useful"] == 0
    assert any(item["label"] == "Git hooks" for item in harness["coverage"])
    assert any("Mark the useful outcome" in gap for gap in harness["gaps"])
    assert any("aikeeper outcome done" in command["command"] for command in harness["commands"])
    assert data["generated_at_ms"] == now


def test_task_economics_compares_current_task_against_baseline(tmp_path: Path) -> None:
    db_path = tmp_path / "keeper.sqlite"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    seed_usage(db_path, cwd)
    now = 1_781_000_000_000
    with connect(db_path) as con:
        project_id = con.execute("select id from projects").fetchone()[0]
        con.execute(
            """
            insert into tasks(project_id, task_key, source, git_branch, issue_id, display_name, first_seen_ms, last_seen_ms)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (project_id, "BASE-1", "git_branch", "baseline", "BASE-1", "BASE-1", now - 1_000_000, now - 1_000_000),
        )
        baseline_task_id = con.execute("select id from tasks where task_key = 'BASE-1'").fetchone()[0]
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
                "baseline-session",
                "/tmp/baseline.jsonl",
                str(cwd),
                "gpt-5.5",
                "openai",
                "test",
                project_id,
                baseline_task_id,
                "abc123",
                "baseline",
                None,
                now - 1_000_000,
                now - 1_000_000,
                100,
                now - 1_000_000,
            ),
        )
        baseline_session_pk = con.execute("select id from sessions where session_id = 'baseline-session'").fetchone()[0]
        con.execute(
            """
            insert into token_events(
                session_pk, sequence, timestamp_ms, input_tokens, cached_input_tokens,
                output_tokens, reasoning_output_tokens, total_tokens,
                running_total_tokens, source_path, source_offset
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (baseline_session_pk, 1, now - 1_000_000, 50, 0, 50, 0, 100, 100, "/tmp/baseline.jsonl", 100),
        )

    data = build_overview(db_path, now_ms=now)
    economics = data["task_economics"]

    assert economics["baseline"]["sample_size"] == 1
    assert economics["baseline"]["estimated_cost_usd"] is not None
    assert economics["baseline"]["delta_ratio"] is not None
    assert economics["status"] in {"watch", "risk"}
    assert economics["projection"]["additional_cost_usd"] >= 0
    assert economics["drivers"][0]["label"] == "Context load"


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

    page = client.get("/budgets")

    assert "Budget Guards" in page.text
    assert "turn USD" in page.text
    assert "$0.0038" in page.text
    assert "$0.0030" in page.text


def test_overview_uses_db_budget_settings_by_default(tmp_path: Path) -> None:
    db_path = tmp_path / "keeper.sqlite"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    seed_usage(db_path, cwd)
    save_budget_settings(
        db_path,
        scope="defaults",
        warn_at=0.8,
        limits={"turn_usd": 0.003, "project_daily_tokens": 250},
    )

    data = build_overview(db_path, now_ms=1_781_000_000_000)
    status = status_for_cwd(db_path, cwd, now_ms=1_781_000_000_000)

    assert data["budget"]["configured"] is True
    assert data["budget"]["source_path"] == "sqlite"
    assert data["budget"]["limits"]["turn_usd"] == pytest.approx(0.003)
    labels = {warning["label"] for warning in data["budget_warnings"]}
    assert "turn USD" in labels
    assert "project daily tokens" in labels
    assert any(warning["label"] == "turn USD" for warning in status["budget_warnings"])


def test_budget_form_updates_db_defaults_and_task_overrides(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "keeper.sqlite"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    seed_usage(db_path, cwd)
    monkeypatch.setattr("aikeeper.web.get_app_version", lambda: {"label": "v9.9.9", "commit": "abc123"})
    app = create_app(db_path=db_path)
    client = TestClient(app)

    defaults_response = client.post(
        "/budgets",
        data={"scope": "defaults", "warn_at": "0.75", "turn_usd": "0.003", "project_daily_tokens": "250"},
        follow_redirects=False,
    )
    task_response = client.post(
        "/budgets",
        data={"scope": "task", "task_key": "AIK-7", "task_daily_tokens": "200", "turn_usd": "0.002"},
        follow_redirects=False,
    )

    config = load_budget_config_from_db(db_path)
    overview = client.get("/api/overview").json()
    page = client.get("/budgets")

    assert defaults_response.status_code == 303
    assert defaults_response.headers["location"] == "/budgets"
    assert task_response.status_code == 303
    assert task_response.headers["location"] == "/budgets"
    assert config.warn_at == pytest.approx(0.75)
    assert config.limits["turn_usd"] == pytest.approx(0.003)
    assert config.task_limits["AIK-7"]["task_daily_tokens"] == pytest.approx(200)
    assert config.task_limits["AIK-7"]["turn_usd"] == pytest.approx(0.002)
    assert overview["budget"]["limits"]["task_daily_tokens"] == pytest.approx(200)
    assert overview["budget"]["limits"]["turn_usd"] == pytest.approx(0.002)
    assert any(warning["label"] == "turn USD" for warning in overview["budget_warnings"])
    assert "Budget Settings" in page.text
    assert 'name="turn_usd"' in page.text
    assert 'name="task_daily_tokens"' in page.text


def test_dashboard_pages_render_navigation_and_split_surfaces(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "keeper.sqlite"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    seed_usage(db_path, cwd)
    monkeypatch.setattr("aikeeper.web.get_app_version", lambda: {"label": "v9.9.9", "commit": "abc123"})
    app = create_app(db_path=db_path)
    client = TestClient(app)

    page = client.get("/")
    favicon = client.get("/favicon.ico")
    usage_page = client.get("/usage")
    models_page = client.get("/models")
    budgets_page = client.get("/budgets")
    health_page = client.get("/health")
    system_page = client.get("/system")
    diagnostics_page = client.get("/diagnostics")

    assert "v9.9.9" in page.text
    assert 'href="/static/styles.css?v=v9.9.9"' in page.text
    assert favicon.status_code == 204
    assert 'aria-current="page">Efficiency' in page.text
    assert "Task Economics" in page.text
    assert "Current useful outcome" in page.text
    assert "Next best move" in page.text
    assert "Workflow Harness" in page.text
    assert "Task Ledger" in page.text
    assert "Cost drivers" in page.text
    assert "Useful outcomes" in page.text
    assert "Install workflow hooks" in page.text
    assert "$0.0038 estimated" in page.text
    assert "$0.0038" in page.text
    assert "session-1" in page.text
    assert "Spend rhythm" in page.text
    assert "Active rate" in page.text
    assert "Active rate trend" in page.text
    assert "previous 5m" in page.text
    assert 'data-rate-trend-bars' in page.text
    assert "Operator alerts" in page.text
    assert "Providers" in page.text
    assert "Model Efficiency" not in page.text

    assert usage_page.status_code == 200
    assert "Projects" in usage_page.text
    assert "Top Tasks" in usage_page.text
    assert 'aria-current="page">Usage' in usage_page.text

    assert models_page.status_code == 200
    assert "Model Efficiency" in models_page.text
    assert "Savings Simulator" in models_page.text

    assert budgets_page.status_code == 200
    assert "Budget Settings" in budgets_page.text

    assert health_page.status_code == 200
    assert "Privacy Audit" in health_page.text
    assert "Ingest Health" in health_page.text

    assert diagnostics_page.status_code == 200
    assert 'aria-current="page">Diagnostics' in diagnostics_page.text
    assert "Diagnostics Bundles" in diagnostics_page.text

    assert system_page.status_code == 200
    assert 'aria-current="page">System' in system_page.text
    assert "System" in system_page.text
    assert "Doctor" in system_page.text
    assert "LaunchAgent" in system_page.text
    assert "aikeeper doctor --fix --port 8766" in system_page.text
    assert "uv run aikeeper" not in system_page.text
    assert 'action="/system/actions/repair"' in system_page.text


def test_system_actions_require_confirmation_and_queue_background_command(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "keeper.sqlite"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    seed_usage(db_path, cwd)
    launched: list[int] = []
    monkeypatch.setattr("aikeeper.web._launch_system_job_runner", lambda db, job_id: launched.append(job_id))
    app = create_app(db_path=db_path)
    client = TestClient(app)

    rejected = client.post("/system/actions/repair", data={"confirm": "nope"}, follow_redirects=False)
    accepted = client.post("/system/actions/repair", data={"confirm": "repair"}, follow_redirects=False)
    invalid = client.post("/system/actions/unknown", data={"confirm": "unknown"}, follow_redirects=False)
    page = client.get("/system")
    api = client.get("/api/system").json()

    assert rejected.status_code == 400
    assert accepted.status_code == 303
    assert accepted.headers["location"] == "/system?job=1"
    assert invalid.status_code == 404
    assert launched == [1]
    assert "Recent Jobs" in page.text
    assert "repair" in page.text
    assert "queued" in page.text
    assert api["jobs"][0]["action"] == "repair"
    assert api["jobs"][0]["status"] == "queued"

    diagnostics = client.post("/system/actions/diagnostics", data={"confirm": "diagnostics"}, follow_redirects=False)
    diagnostics_api = client.get("/api/system").json()

    assert diagnostics.status_code == 303
    assert diagnostics_api["jobs"][0]["action"] == "diagnostics"
    assert "--json" in diagnostics_api["jobs"][0]["command"]


def test_diagnostics_page_lists_bundles_actions_and_downloads_archive(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "keeper.sqlite"
    cwd = tmp_path / "repo"
    app_home = tmp_path / "home"
    bundle_dir = app_home / "diagnostics"
    log_dir = app_home / "logs"
    cwd.mkdir()
    bundle_dir.mkdir(parents=True)
    log_dir.mkdir()
    seed_usage(db_path, cwd)
    bundle = bundle_dir / "aikeeper-diagnostics-1781000000000.zip"
    bundle.write_bytes(b"diagnostics zip")
    (log_dir / "system-actions.log").write_text("repair queued\nCreated AI Keeper diagnostics bundle\n", encoding="utf-8")
    monkeypatch.setenv("AIKEEPER_HOME", str(app_home))
    with connect(db_path) as con:
        con.execute(
            """
            insert into system_jobs(action, status, command_json, cwd, log_path, created_at_ms)
            values (?, ?, ?, ?, ?, ?)
            """,
            ("repair", "ok", '["aikeeper", "doctor"]', str(cwd), str(log_dir / "system-actions.log"), 1_781_000_000_000),
        )
    app = create_app(db_path=db_path)
    client = TestClient(app)

    page = client.get("/diagnostics")
    api = client.get("/api/diagnostics").json()
    download = client.get(f"/diagnostics/bundles/{bundle.name}")
    missing = client.get("/diagnostics/bundles/../aikeeper.sqlite")

    assert page.status_code == 200
    assert "Diagnostics Bundles" in page.text
    assert bundle.name in page.text
    assert "repair queued" in page.text
    assert f'href="/diagnostics/bundles/{bundle.name}"' in page.text
    assert api["bundles"][0]["filename"] == bundle.name
    assert api["jobs"][0]["action"] == "repair"
    assert api["jobs"][0]["status"] == "ok"
    assert api["action_log"][-1] == "Created AI Keeper diagnostics bundle"
    assert download.status_code == 200
    assert download.content == b"diagnostics zip"
    assert download.headers["content-type"] == "application/zip"
    assert missing.status_code == 404


def test_diagnostics_post_creates_bundle_and_redirects_to_page(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "keeper.sqlite"
    cwd = tmp_path / "repo"
    app_home = tmp_path / "home"
    cwd.mkdir()
    seed_usage(db_path, cwd)
    monkeypatch.setenv("AIKEEPER_HOME", str(app_home))
    monkeypatch.setattr(
        "aikeeper.diagnostics.launch_agent_status",
        lambda **kwargs: {
            "loaded": True,
            "ping": {"ok": True},
            "url": "http://127.0.0.1:8766",
            "plist_path": str(tmp_path / "service.plist"),
            "plist_exists": True,
        },
    )
    app = create_app(db_path=db_path)
    client = TestClient(app)

    response = client.post("/diagnostics/bundles", follow_redirects=False)

    bundles = list((app_home / "diagnostics").glob("aikeeper-diagnostics-*.zip"))
    action_log = app_home / "logs" / "system-actions.log"
    assert response.status_code == 303
    assert response.headers["location"].startswith("/diagnostics?created=aikeeper-diagnostics-")
    assert len(bundles) == 1
    assert bundles[0].name in action_log.read_text(encoding="utf-8")
