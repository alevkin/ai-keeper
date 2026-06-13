import json
from pathlib import Path

from typer.testing import CliRunner

from aikeeper.cli import app
from aikeeper.db import connect, init_db
from aikeeper.installer import install_codex_hooks


def test_install_codex_hooks_merges_idempotently_and_backs_up_existing_file(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    hooks_file = codex_home / "hooks.json"
    hooks_file.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "existing"}]}]}}))

    first = install_codex_hooks(scope="user", codex_home=codex_home, project_dir=tmp_path)
    second = install_codex_hooks(scope="user", codex_home=codex_home, project_dir=tmp_path)
    data = json.loads(hooks_file.read_text())

    assert first == hooks_file
    assert second == hooks_file
    assert hooks_file.with_suffix(".json.bak").exists()
    assert len(data["hooks"]["SessionStart"]) == 1
    assert len(data["hooks"]["UserPromptSubmit"]) == 1
    assert sum(
        hook["command"].endswith("aikeeper hook codex")
        for group in data["hooks"]["Stop"]
        for hook in group["hooks"]
    ) == 1


def test_cli_status_json_reads_configured_db(tmp_path: Path) -> None:
    db_path = tmp_path / "keeper.sqlite"
    cwd = tmp_path / "repo"
    cwd.mkdir()
    with connect(db_path) as con:
        init_db(con)
    runner = CliRunner()

    result = runner.invoke(app, ["status", "--cwd", str(cwd), "--json", "--db-path", str(db_path)])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["session"]["total_tokens"] == 0
    assert data["project"]["root_path"] == str(cwd)
