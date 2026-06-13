import json
from pathlib import Path

from typer.testing import CliRunner

from aikeeper.budgets import load_budget_config
from aikeeper.claude import parse_claude_token_events, sync_claude_once
from aikeeper.cli import app
from aikeeper.db import connect, init_db
from aikeeper.exports import export_usage
from aikeeper.openai_costs import import_costs_payload
from aikeeper.service import project_detail, session_detail, simulate_model_cost


NOW = 1_781_000_000_000


def seed_backlog_usage(db_path: Path, cwd: Path) -> tuple[int, int]:
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
            (project_id, "AIK-42", "git_branch", "feature/AIK-42-context", "AIK-42", "AIK-42", NOW, NOW),
        )
        task_id = con.execute("select id from tasks").fetchone()[0]
        con.execute(
            """
            insert into sessions(
                provider, session_id, transcript_path, cwd, model, model_provider, source,
                project_id, task_id, git_sha, git_branch, git_origin_url,
                created_at_ms, updated_at_ms, total_tokens, last_seen_ms
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "codex",
                "session-1",
                "/tmp/session-1.jsonl",
                str(cwd),
                "gpt-5.5",
                "openai",
                "test",
                project_id,
                task_id,
                "abc",
                "feature/AIK-42-context",
                None,
                NOW - 180_000,
                NOW,
                0,
                NOW,
            ),
        )
        session_pk = con.execute("select id from sessions").fetchone()[0]
        events = [
            (1, NOW - 180_000, 10_000, 8_000, 1_000, 11_000, 11_000),
            (2, NOW - 120_000, 40_000, 2_000, 3_000, 43_000, 54_000),
            (3, NOW - 60_000, 200_000, 1_000, 20_000, 220_000, 274_000),
        ]
        for sequence, timestamp_ms, input_tokens, cached_input_tokens, output_tokens, total_tokens, running in events:
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
                    5_000,
                    total_tokens,
                    running,
                    "/tmp/session-1.jsonl",
                    sequence * 100,
                ),
            )
        con.execute("update sessions set total_tokens = 274000 where id = ?", (session_pk,))
    return project_id, session_pk


def test_task_budget_overrides_are_reflected_on_project_tasks(tmp_path: Path) -> None:
    db_path = tmp_path / "keeper.sqlite"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    project_id, _session_pk = seed_backlog_usage(db_path, cwd)
    budget_path = tmp_path / "budgets.toml"
    budget_path.write_text(
        """
        [defaults]
        task_daily_tokens = 999999

        [tasks.AIK-42]
        task_daily_tokens = 100000
        task_daily_usd = 1
        """,
        encoding="utf-8",
    )

    data = project_detail(db_path, project_id, budget_path=budget_path, now_ms=NOW)

    task = data["tasks"][0]
    assert task["budget"]["configured"] is True
    assert task["budget"]["limits"]["task_daily_tokens"] == 100000
    assert task["budget_warnings"][0]["label"] == "task daily tokens"
    assert task["budget_warnings"][0]["severity"] == "over"


def test_session_detail_exposes_context_bloat_and_anomalies(tmp_path: Path) -> None:
    db_path = tmp_path / "keeper.sqlite"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    _project_id, session_pk = seed_backlog_usage(db_path, cwd)

    data = session_detail(db_path, session_pk)

    assert data["context_health"]["input_growth_ratio"] == 20
    assert data["context_health"]["cached_input_ratio"] < 0.1
    assert data["context_health"]["cache_regression"] is True
    assert "compaction" in data["context_health"]["recommendation"].lower()
    reasons = {anomaly["reason"] for anomaly in data["anomalies"]}
    assert "large turn" in reasons
    assert "cache regression" in reasons
    assert "cost jump" in reasons


def test_savings_simulator_reprices_existing_events(tmp_path: Path) -> None:
    db_path = tmp_path / "keeper.sqlite"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    seed_backlog_usage(db_path, cwd)

    result = simulate_model_cost(db_path, target_model="gpt-5.4-mini")

    assert result["target_model"] == "gpt-5.4-mini"
    assert result["event_count"] == 3
    assert result["target_estimated_cost_usd"] < result["actual_estimated_cost_usd"]
    assert result["estimated_savings_usd"] > 0


def test_exports_include_usage_and_task_budget_status(tmp_path: Path) -> None:
    db_path = tmp_path / "keeper.sqlite"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    seed_backlog_usage(db_path, cwd)
    budget_path = tmp_path / "budgets.toml"
    budget_path.write_text("[tasks.AIK-42]\ntask_daily_tokens = 100000\n", encoding="utf-8")

    markdown = export_usage(db_path, "markdown", budget_path=budget_path, now_ms=NOW)
    csv = export_usage(db_path, "csv", budget_path=budget_path, now_ms=NOW)
    payload = json.loads(export_usage(db_path, "json", budget_path=budget_path, now_ms=NOW))

    assert "# AI Keeper Usage Export" in markdown
    assert "AIK-42" in markdown
    assert "budget over" in markdown
    assert "project,task,total_tokens" in csv
    assert payload["privacy"] == "metadata-only"
    assert payload["task_budget_status"][0]["task_key"] == "AIK-42"


def test_openai_cost_payload_import_stores_aggregate_buckets(tmp_path: Path) -> None:
    db_path = tmp_path / "keeper.sqlite"
    payload = {
        "data": [
            {
                "start_time": 1730419200,
                "end_time": 1730505600,
                "results": [
                    {
                        "amount": {"value": 0.06, "currency": "usd"},
                        "line_item": "tokens",
                        "project_id": "proj_123",
                        "api_key_id": None,
                        "quantity": 10,
                    }
                ],
            }
        ]
    }

    imported = import_costs_payload(db_path, payload, source="fixture")

    assert imported == 1
    with connect(db_path) as con:
        row = con.execute("select * from external_costs").fetchone()
    assert row["provider"] == "openai"
    assert row["amount_value"] == 0.06
    assert row["project_ref"] == "proj_123"


def test_claude_jsonl_parser_and_sync_are_metadata_only(tmp_path: Path) -> None:
    claude_home = tmp_path / "claude"
    project_dir = claude_home / "projects" / "-Users-test-repo"
    project_dir.mkdir(parents=True)
    transcript = project_dir / "session.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "sessionId": "claude-session-1",
                "cwd": str(tmp_path / "repo"),
                "model": "claude-sonnet-4-5",
                "timestamp": "2026-06-12T16:34:53.333Z",
                "message": {
                    "usage": {
                        "input_tokens": 120,
                        "cache_read_input_tokens": 40,
                        "output_tokens": 30,
                    },
                    "content": "SECRET_CLAUDE_TEXT",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "keeper.sqlite"

    parsed = list(parse_claude_token_events(transcript.read_text().splitlines()))
    result = sync_claude_once(db_path=db_path, claude_home=claude_home)

    assert parsed[0].total_tokens == 150
    assert parsed[0].cached_input_tokens == 40
    assert result.token_events_imported == 1
    with connect(db_path) as con:
        session = con.execute("select * from sessions where provider = 'claude'").fetchone()
    assert session["model"] == "claude-sonnet-4-5"
    assert b"SECRET_CLAUDE_TEXT" not in db_path.read_bytes()


def test_cli_export_and_simulate_commands(tmp_path: Path) -> None:
    db_path = tmp_path / "keeper.sqlite"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    seed_backlog_usage(db_path, cwd)
    runner = CliRunner()

    export_result = runner.invoke(app, ["export", "--format", "json", "--db-path", str(db_path)])
    simulate_result = runner.invoke(
        app,
        ["simulate", "--target-model", "gpt-5.4-mini", "--db-path", str(db_path)],
    )

    assert export_result.exit_code == 0
    assert json.loads(export_result.stdout)["privacy"] == "metadata-only"
    assert simulate_result.exit_code == 0
    assert json.loads(simulate_result.stdout)["target_model"] == "gpt-5.4-mini"
