import json
from pathlib import Path

from typer.testing import CliRunner

from aikeeper.cli import app
from aikeeper.db import connect, init_db
from aikeeper.installer import HOOK_EVENTS
from aikeeper.installer import _codex_hook_state_key
from aikeeper.installer import codex_hooks_trust_status
from aikeeper.installer import install_codex_hooks
from aikeeper.installer import uninstall_codex_hooks


def _trust_codex_hooks(codex_home: Path, hooks_file: Path, *, enabled: bool = True) -> None:
    config = codex_home / "config.toml"
    blocks = []
    for event_name in HOOK_EVENTS:
        state_key = _codex_hook_state_key(hooks_file, event_name, 0, 0)
        blocks.append(
            "\n".join(
                [
                    f'[hooks.state."{state_key}"]',
                    f'trusted_hash = "sha256:test-{event_name}"',
                    f"enabled = {str(enabled).lower()}",
                    "",
                ]
            )
        )
    config.write_text("\n".join(blocks), encoding="utf-8")


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


def test_install_codex_hooks_replaces_previous_aikeeper_versions(tmp_path: Path, monkeypatch) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    homebrew_prefix = tmp_path / "homebrew"
    current_root = homebrew_prefix / "Cellar" / "aikeeper" / "0.30.6" / "libexec"
    stable_executable = homebrew_prefix / "opt" / "aikeeper" / "libexec" / ".venv" / "bin" / "aikeeper"
    stable_executable.parent.mkdir(parents=True)
    stable_executable.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    monkeypatch.setattr("aikeeper.installer._project_root", lambda: current_root)
    hooks_file = codex_home / "hooks.json"
    old_0303 = "uv --directory /opt/homebrew/Cellar/aikeeper/0.30.3/libexec run aikeeper hook codex"
    old_0305 = "uv --directory /opt/homebrew/Cellar/aikeeper/0.30.5/libexec run aikeeper hook codex"
    hooks_file.write_text(
        json.dumps(
            {
                "hooks": {
                    event: [
                        {"hooks": [{"type": "command", "command": old_0303}]},
                        {"hooks": [{"type": "command", "command": old_0305}]},
                    ]
                    for event in ("SessionStart", "UserPromptSubmit", "Stop")
                }
            }
        ),
        encoding="utf-8",
    )

    install_codex_hooks(scope="user", codex_home=codex_home, project_dir=tmp_path)
    data = json.loads(hooks_file.read_text())

    expected_command = f"{stable_executable} hook codex"
    for event_name in ("SessionStart", "UserPromptSubmit", "Stop"):
        groups = data["hooks"][event_name]
        commands = [hook["command"] for group in groups for hook in group["hooks"]]
        assert commands == [expected_command]


def test_install_codex_hooks_preserves_non_aikeeper_hooks_when_replacing_versions(
    tmp_path: Path, monkeypatch
) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    current_root = tmp_path / "aikeeper" / "libexec"
    current_executable = current_root / ".venv" / "bin" / "aikeeper"
    current_executable.parent.mkdir(parents=True)
    current_executable.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    monkeypatch.setattr("aikeeper.installer._project_root", lambda: current_root)
    hooks_file = codex_home / "hooks.json"
    hooks_file.write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "uv --directory /opt/homebrew/Cellar/aikeeper/0.30.5/libexec run aikeeper hook codex",
                                },
                                {"type": "command", "command": "other-tool"},
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    install_codex_hooks(scope="user", codex_home=codex_home, project_dir=tmp_path)
    data = json.loads(hooks_file.read_text())

    stop_commands = [hook["command"] for group in data["hooks"]["Stop"] for hook in group["hooks"]]
    assert stop_commands == ["other-tool", f"{current_executable} hook codex"]
    assert data["hooks"]["SessionStart"] == [
        {
            "hooks": [
                {
                    "command": f"{current_executable} hook codex",
                    "statusMessage": "AI Keeper: prepare local session tracking",
                    "timeout": 30,
                    "type": "command",
                }
            ]
        }
    ]


def test_install_codex_hooks_writes_descriptive_status_messages(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()

    install_codex_hooks(scope="user", codex_home=codex_home, project_dir=tmp_path)

    data = json.loads((codex_home / "hooks.json").read_text(encoding="utf-8"))
    messages = {
        event_name: data["hooks"][event_name][0]["hooks"][0]["statusMessage"]
        for event_name in HOOK_EVENTS
    }
    assert messages == {
        "SessionStart": "AI Keeper: prepare local session tracking",
        "UserPromptSubmit": "AI Keeper: attach local budget context",
        "Stop": "AI Keeper: sync local usage metadata",
    }
    assert "Syncing AI Keeper" not in messages.values()


def test_install_codex_hooks_falls_back_to_direct_command_without_uv_run(tmp_path: Path, monkeypatch) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    monkeypatch.setattr("aikeeper.installer._project_root", lambda: tmp_path)

    install_codex_hooks(scope="user", codex_home=codex_home, project_dir=tmp_path)

    data = json.loads((codex_home / "hooks.json").read_text(encoding="utf-8"))
    commands = [
        hook["command"]
        for event_name in HOOK_EVENTS
        for group in data["hooks"][event_name]
        for hook in group["hooks"]
    ]
    assert commands == ["aikeeper hook codex", "aikeeper hook codex", "aikeeper hook codex"]
    assert not any("uv" in command for command in commands)


def test_codex_hook_trust_status_requires_trust_and_enabled_toggles(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    hooks_file = install_codex_hooks(scope="user", codex_home=codex_home, project_dir=tmp_path)

    status = codex_hooks_trust_status(scope="user", codex_home=codex_home, project_dir=tmp_path)

    assert status.installed is True
    assert status.ready is False
    assert status.untrusted_events == HOOK_EVENTS
    assert status.disabled_events == ()

    _trust_codex_hooks(codex_home, hooks_file, enabled=False)
    status = codex_hooks_trust_status(scope="user", codex_home=codex_home, project_dir=tmp_path)

    assert status.installed is True
    assert status.ready is False
    assert status.untrusted_events == ()
    assert status.disabled_events == HOOK_EVENTS

    _trust_codex_hooks(codex_home, hooks_file, enabled=True)
    status = codex_hooks_trust_status(scope="user", codex_home=codex_home, project_dir=tmp_path)

    assert status.installed is True
    assert status.ready is True
    assert status.untrusted_events == ()
    assert status.disabled_events == ()


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
    hooks_file = install_codex_hooks(scope="user", codex_home=codex_home, project_dir=tmp_path)
    _trust_codex_hooks(codex_home, hooks_file)
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


def test_cli_doctor_warns_when_codex_hooks_are_not_trusted(tmp_path: Path, monkeypatch) -> None:
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
    assert data["status"] == "warn"
    codex_check = next(check for check in data["checks"] if check["name"] == "codex_hooks")
    assert codex_check["status"] == "warn"
    assert "Trust" in codex_check["detail"]
    assert "Codex Settings" in codex_check["fix"]


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
    assert data["status"] == "warn"
    assert {fix["name"] for fix in data["fixes"]} == {"app_home", "database", "codex_hooks", "launch_agent"}
    codex_check = next(check for check in data["checks"] if check["name"] == "codex_hooks")
    assert codex_check["status"] == "warn"
    assert "Trust" in codex_check["detail"]


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
