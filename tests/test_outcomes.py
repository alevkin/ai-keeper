import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from aikeeper.audit import audit_privacy
from aikeeper.cli import app
from aikeeper.db import connect, init_db
from aikeeper.outcomes import record_outcome, workflow_harness_state_for_cwd
from aikeeper.storage import ensure_project_and_task


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _repo_with_commit(tmp_path: Path, branch: str = "feature/AIK-77-harness") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Andrei Levkin")
    _git(repo, "config", "user.email", "alevkin@gmail.com")
    _git(repo, "checkout", "-b", branch)
    (repo / "app.py").write_text("print('ok')\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "feat: add harness test slice")
    return repo


def _seed_task_usage(db_path: Path, repo: Path) -> int:
    with connect(db_path) as con:
        init_db(con)
        project_id, task_id, branch, origin, sha, _root = ensure_project_and_task(con, cwd=repo, seen_ms=1_781_000_000_000)
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
                "/tmp/session.jsonl",
                str(repo),
                "gpt-5.5",
                "openai",
                "test",
                project_id,
                task_id,
                sha,
                branch,
                origin,
                1_781_000_000_000,
                1_781_000_010_000,
                300,
                1_781_000_010_000,
            ),
        )
        session_pk = con.execute("select id from sessions where session_id = 'session-1'").fetchone()[0]
        con.execute(
            """
            insert into token_events(
                session_pk, sequence, timestamp_ms, input_tokens, cached_input_tokens,
                output_tokens, reasoning_output_tokens, total_tokens,
                running_total_tokens, source_path, source_offset
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_pk, 1, 1_781_000_010_000, 200, 50, 100, 0, 300, 300, "/tmp/session.jsonl", 120),
        )
        con.commit()
        return task_id


def test_record_outcome_captures_metadata_only_task_cost(tmp_path: Path) -> None:
    repo = _repo_with_commit(tmp_path)
    db_path = tmp_path / "keeper.sqlite"
    _seed_task_usage(db_path, repo)

    outcome = record_outcome(db_path, cwd=repo, status="useful", outcome_type="code", created_at_ms=1_781_000_020_000)

    assert outcome["status"] == "useful"
    assert outcome["confidence"] == "high"
    assert outcome["type"] == "code"
    assert outcome["tokens"] == 300
    assert outcome["estimated_cost_usd"] > 0
    assert outcome["changed_files"] == 1
    assert outcome["commit_sha"]
    assert audit_privacy(db_path)["status"] == "pass"
    assert b"SECRET_PROMPT" not in db_path.read_bytes()


def test_workflow_harness_suggests_commit_candidate_until_recorded(tmp_path: Path) -> None:
    repo = _repo_with_commit(tmp_path)
    db_path = tmp_path / "keeper.sqlite"
    _seed_task_usage(db_path, repo)

    before = workflow_harness_state_for_cwd(db_path, repo)
    record_outcome(db_path, cwd=repo, status="verified", outcome_type="code", created_at_ms=1_781_000_020_000)
    after = workflow_harness_state_for_cwd(db_path, repo)

    assert before["configured"] is True
    assert before["suggested_outcome"]["status"] == "candidate"
    assert before["suggested_outcome"]["confidence"] == "high"
    assert before["outcome_summary"]["useful"] == 0
    assert after["suggested_outcome"] is None
    assert after["outcome_summary"]["useful"] == 1
    assert after["status"] == "tracked"


def test_cli_outcome_done_and_status_are_json_metadata(tmp_path: Path) -> None:
    repo = _repo_with_commit(tmp_path)
    db_path = tmp_path / "keeper.sqlite"
    _seed_task_usage(db_path, repo)
    runner = CliRunner()

    done = runner.invoke(
        app,
        ["outcome", "done", "--cwd", str(repo), "--db-path", str(db_path), "--status", "useful", "--type", "code", "--json"],
    )
    status = runner.invoke(app, ["outcome", "status", "--cwd", str(repo), "--db-path", str(db_path), "--json"])

    assert done.exit_code == 0, done.stdout
    assert status.exit_code == 0, status.stdout
    done_data = json.loads(done.stdout)
    status_data = json.loads(status.stdout)
    assert done_data["tokens"] == 300
    assert status_data["outcome_summary"]["useful"] == 1
    assert status_data["coverage"][0]["label"] == "Named task"
