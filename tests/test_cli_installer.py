import json
from pathlib import Path

from typer.testing import CliRunner

from aikeeper.cli import app
from aikeeper.db import connect, init_db
from aikeeper.installer import install_codex_hooks, uninstall_codex_hooks


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


def test_uninstall_codex_hooks_removes_only_ai_keeper_entries(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    hooks_file = codex_home / "hooks.json"
    install_codex_hooks(scope="user", codex_home=codex_home, project_dir=tmp_path)
    data = json.loads(hooks_file.read_text())
    data["hooks"]["Stop"].append({"hooks": [{"type": "command", "command": "other-tool"}]})
    hooks_file.write_text(json.dumps(data), encoding="utf-8")

    removed = uninstall_codex_hooks(scope="user", codex_home=codex_home, project_dir=tmp_path)

    data = json.loads(hooks_file.read_text())
    assert removed == hooks_file
    assert hooks_file.with_suffix(".json.bak").exists()
    assert data["hooks"]["Stop"] == [{"hooks": [{"type": "command", "command": "other-tool"}]}]
    assert data["hooks"]["SessionStart"] == []
    assert data["hooks"]["UserPromptSubmit"] == []


def test_cli_install_all_initializes_db_installs_hooks_and_service(tmp_path: Path, monkeypatch) -> None:
    app_home = tmp_path / "home"
    codex_home = tmp_path / "codex"
    db_path = app_home / "aikeeper.sqlite"
    plist_path = tmp_path / "service.plist"
    monkeypatch.setenv("AIKEEPER_HOME", str(app_home))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    calls: list[tuple[str, object]] = []

    def fake_write_launch_agent_plist(**kwargs):
        calls.append(("write", kwargs))
        return plist_path

    def fake_bootstrap_launch_agent(path):
        calls.append(("bootstrap", path))

    monkeypatch.setattr("aikeeper.cli.write_launch_agent_plist", fake_write_launch_agent_plist)
    monkeypatch.setattr("aikeeper.cli.bootstrap_launch_agent", fake_bootstrap_launch_agent)
    runner = CliRunner()

    result = runner.invoke(app, ["install", "all", "--port", "8766"])

    assert result.exit_code == 0
    assert db_path.exists()
    assert (codex_home / "hooks.json").exists()
    assert calls[0][0] == "write"
    assert calls[0][1]["port"] == 8766
    assert calls[1] == ("bootstrap", plist_path)


def test_cli_install_workflow_harness_writes_git_hooks(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    hooks = tmp_path / "hooks"
    repo.mkdir()
    runner = CliRunner()

    result = runner.invoke(app, ["install", "workflow-harness", "--repo-root", str(repo), "--hooks-dir", str(hooks)])

    assert result.exit_code == 0
    assert (hooks / "pre-commit").exists()
    assert (hooks / "commit-msg").exists()
    assert (hooks / "pre-push").exists()
    assert "Workflow Harness" in result.stdout
    assert "Conventional Commits" in (hooks / "commit-msg").read_text(encoding="utf-8")


def test_cli_doctor_json_reports_installation_state(tmp_path: Path, monkeypatch) -> None:
    app_home = tmp_path / "home"
    codex_home = tmp_path / "codex"
    db_path = app_home / "aikeeper.sqlite"
    plist_path = tmp_path / "service.plist"
    monkeypatch.setenv("AIKEEPER_HOME", str(app_home))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    install_codex_hooks(scope="user", codex_home=codex_home, project_dir=tmp_path)
    plist_path.write_text("plist", encoding="utf-8")
    with connect(db_path) as con:
        init_db(con)
    monkeypatch.setattr("aikeeper.cli.default_launch_agent_path", lambda: plist_path)
    monkeypatch.setattr(
        "aikeeper.cli.launch_agent_status",
        lambda **kwargs: {
            "loaded": True,
            "ping": {"ok": True},
            "url": "http://127.0.0.1:8766",
            "plist_path": str(plist_path),
            "plist_exists": True,
        },
    )
    runner = CliRunner()

    result = runner.invoke(app, ["doctor", "--port", "8766", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["status"] == "ok"
    assert {check["name"]: check["status"] for check in data["checks"]} == {
        "app_home": "ok",
        "database": "ok",
        "codex_hooks": "ok",
        "launch_agent": "ok",
        "dashboard": "ok",
    }


def test_cli_doctor_fix_repairs_missing_installation_parts(tmp_path: Path, monkeypatch) -> None:
    app_home = tmp_path / "home"
    codex_home = tmp_path / "codex"
    db_path = app_home / "aikeeper.sqlite"
    plist_path = tmp_path / "service.plist"
    monkeypatch.setenv("AIKEEPER_HOME", str(app_home))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    state = {"plist_exists": False, "loaded": False, "ping": False}
    calls: list[tuple[str, object]] = []

    def fake_launch_agent_status(**kwargs):
        return {
            "loaded": state["loaded"],
            "ping": {"ok": state["ping"]},
            "url": "http://127.0.0.1:8766",
            "plist_path": str(plist_path),
            "plist_exists": state["plist_exists"],
        }

    def fake_write_launch_agent_plist(**kwargs):
        calls.append(("write", kwargs))
        state["plist_exists"] = True
        return plist_path

    def fake_bootstrap_launch_agent(path):
        calls.append(("bootstrap", path))
        state["loaded"] = True
        state["ping"] = True

    monkeypatch.setattr("aikeeper.cli.default_launch_agent_path", lambda: plist_path)
    monkeypatch.setattr("aikeeper.cli.launch_agent_status", fake_launch_agent_status)
    monkeypatch.setattr("aikeeper.cli.write_launch_agent_plist", fake_write_launch_agent_plist)
    monkeypatch.setattr("aikeeper.cli.bootstrap_launch_agent", fake_bootstrap_launch_agent)
    runner = CliRunner()

    result = runner.invoke(app, ["doctor", "--fix", "--port", "8766", "--json"])

    assert result.exit_code == 0
    assert db_path.exists()
    assert (codex_home / "hooks.json").exists()
    assert calls[0][0] == "write"
    assert calls[0][1]["port"] == 8766
    assert calls[1] == ("bootstrap", plist_path)
    data = json.loads(result.stdout)
    assert data["status"] == "ok"
    assert {fix["name"] for fix in data["fixes"]} == {"app_home", "database", "codex_hooks", "launch_agent"}


def test_cli_uninstall_all_removes_hooks_and_service_without_deleting_db(tmp_path: Path, monkeypatch) -> None:
    app_home = tmp_path / "home"
    codex_home = tmp_path / "codex"
    db_path = app_home / "aikeeper.sqlite"
    plist_path = tmp_path / "service.plist"
    monkeypatch.setenv("AIKEEPER_HOME", str(app_home))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    install_codex_hooks(scope="user", codex_home=codex_home, project_dir=tmp_path)
    with connect(db_path) as con:
        init_db(con)
    calls: list[Path | None] = []
    monkeypatch.setattr("aikeeper.cli.uninstall_launch_agent", lambda plist_path=None: calls.append(plist_path) or plist_path)
    runner = CliRunner()

    result = runner.invoke(app, ["uninstall", "all", "--plist-path", str(plist_path)])

    assert result.exit_code == 0
    assert db_path.exists()
    assert calls == [plist_path]
    data = json.loads((codex_home / "hooks.json").read_text())
    assert data["hooks"]["Stop"] == []
