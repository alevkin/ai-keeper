import json
import sqlite3
from pathlib import Path

from aikeeper.db import connect, init_db
from aikeeper.hooks import _summary, handle_codex_hook


def test_summary_is_markdown_and_groups_large_counts() -> None:
    status = {
        "session": {"last_turn_tokens": 60_981, "total_tokens": 12_621_389},
        "task": {"today_tokens": 4_123_229},
        "project": {"today_tokens": 4_123_229},
    }

    assert (
        _summary(status)
        == "> **AI Keeper** | turn 60,981 tokens | session 12,621,389 tokens | "
        "task today 4,123,229 tokens | project today 4,123,229 tokens"
    )


def test_summary_includes_dashboard_link_when_daemon_is_running() -> None:
    status = {
        "session": {"last_turn_tokens": 60_981, "total_tokens": 12_621_389},
        "task": {"today_tokens": 4_123_229},
        "project": {"today_tokens": 4_123_229},
    }

    assert _summary(status, dashboard_url="http://127.0.0.1:8766").endswith(
        "| [dashboard](http://127.0.0.1:8766)"
    )


def test_stop_hook_returns_summary_json_and_discards_prompt_text(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "keeper.sqlite"
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    transcript = codex_home / "sessions" / "rollout.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        json.dumps(
            {
                "timestamp": "2026-06-12T16:34:53.333Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "last_token_usage": {
                            "input_tokens": 90,
                            "cached_input_tokens": 0,
                            "output_tokens": 10,
                            "reasoning_output_tokens": 0,
                            "total_tokens": 100,
                        },
                        "total_token_usage": {"total_tokens": 100},
                    },
                },
            }
        )
        + "\n"
    )
    with sqlite3.connect(codex_home / "state_5.sqlite") as con:
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
                git_branch text,
                model text
            )
            """
        )
        con.execute(
            """
            insert into threads values (
                'session-1', ?, 1780000000, 1780000100, 'vscode', 'openai',
                ?, 'title', 'workspace-write', 'never', 100,
                'feature/AIK-99-hook', 'gpt-5.5'
            )
            """,
            (str(transcript), str(tmp_path / "repo")),
        )
    with connect(db_path) as con:
        init_db(con)
    monkeypatch.setenv("AIKEEPER_HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr("aikeeper.hooks._find_dashboard_url", lambda: "http://127.0.0.1:8766")

    result = handle_codex_hook(
        {
            "session_id": "session-1",
            "transcript_path": str(transcript),
            "cwd": str(tmp_path / "repo"),
            "hook_event_name": "Stop",
            "model": "gpt-5.5",
            "prompt": "SECRET_PROMPT_FROM_HOOK",
        },
        db_path=db_path,
        codex_home=codex_home,
    )

    assert result["continue"] is True
    assert result["systemMessage"].startswith("> **AI Keeper** | turn 100 tokens | session 100 tokens")
    assert result["systemMessage"].endswith("| [dashboard](http://127.0.0.1:8766)")
    with connect(db_path) as con:
        task = con.execute("select * from tasks where task_key = 'AIK-99'").fetchone()
    assert task is not None
    assert b"SECRET_PROMPT_FROM_HOOK" not in db_path.read_bytes()


def test_user_prompt_submit_hook_adds_visible_usage_context_without_prompt_text(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "keeper.sqlite"
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    with connect(db_path) as con:
        init_db(con)
    monkeypatch.setenv("AIKEEPER_HOME", str(tmp_path))
    monkeypatch.setattr("aikeeper.hooks._find_dashboard_url", lambda: "http://127.0.0.1:8766")

    result = handle_codex_hook(
        {
            "session_id": "session-2",
            "cwd": str(tmp_path),
            "hook_event_name": "UserPromptSubmit",
            "model": "gpt-5.5",
            "prompt": "SECRET_PROMPT_FROM_HOOK",
        },
        db_path=db_path,
        codex_home=codex_home,
    )

    output = result["hookSpecificOutput"]
    assert output["hookEventName"] == "UserPromptSubmit"
    assert "> **AI Keeper**" in output["additionalContext"]
    assert "[dashboard](http://127.0.0.1:8766)" in output["additionalContext"]
    assert "session 0 tokens" in output["additionalContext"]
    with connect(db_path) as con:
        sessions_count = con.execute("select count(*) from sessions").fetchone()[0]
    assert sessions_count == 0
    assert b"SECRET_PROMPT_FROM_HOOK" not in db_path.read_bytes()
